# The Hibiki worker pool: a set of voice-only Discord clients (Red/Green/Blue
# Hibiki) that Herupa dispatches to play music. The workers never read messages
# or register commands; Herupa's Music cog owns all command handling and text
# replies, so adding a worker is just another token in MUSIC_BOT_TOKENS.
#
# Concurrency model: every worker runs on the same asyncio loop as Herupa, so
# the pool's bookkeeping needs no locks as long as state is mutated before the
# first await (see acquire()).

import asyncio
import time

import discord
import yt_dlp

# One bot can hold one voice connection per guild, so "free" is per guild.
MAX_QUEUE = 25          # tracks per session, incl. the one playing
IDLE_TIMEOUT = 300      # seconds an empty-queue worker waits before leaving
VOLUME = 0.75

YTDL_OPTS = {
    "format": "bestaudio/best",
    "noplaylist": True,
    "default_search": "ytsearch1",
    "quiet": True,
    "no_warnings": True,
    "socket_timeout": 10,
}
# The stream URL is a long-lived HTTPS link; let ffmpeg ride out CDN hiccups.
FFMPEG_BEFORE = "-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5"
FFMPEG_OPTS = "-vn"

# Personality is looked up by color word in the bot's username, so a future
# "Yellow Hibiki" only needs an entry here (or falls back to the default).
PERSONALITIES = {
    "red": {
        "color": (255, 92, 100),
        "join": "🔥 RED HIBIKI ON THE DECKS. Let's make some noise!",
        "status": "🔥 waiting for the drop | $music",
        "footer": "LET'S GOOOO",
    },
    "green": {
        "color": (98, 225, 137),
        "join": "🌿 Green Hibiki sliding in. Let's vibe.",
        "status": "🌿 vibing | $music",
        "footer": "no rush, just tunes",
    },
    "blue": {
        "color": (105, 165, 255),
        "join": "🌙 blue hibiki in the mix. late night mode engaged.",
        "status": "🌙 late night frequencies | $music",
        "footer": "no skips, all mood",
    },
    "default": {
        "color": (185, 185, 195),
        "join": "🎧 {name} joining the decks.",
        "status": "🎧 ready to play | $music",
        "footer": "hibiki means echo",
    },
}


class SessionPrepareError(Exception):
    """A pre-connect check failed; str(exc) is the user-facing explanation."""


class Track:
    def __init__(self, info, requested_by):
        self.title = info.get("title") or "Unknown title"
        self.stream_url = info["url"]
        self.webpage_url = info.get("webpage_url") or ""
        self.duration = info.get("duration")  # seconds or None (live)
        self.requested_by = requested_by
        self.resolved_at = time.monotonic()

    def pretty_duration(self):
        if not self.duration:
            return "live/unknown"
        m, s = divmod(int(self.duration), 60)
        h, m = divmod(m, 60)
        return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


async def resolve_track(loop, query, requested_by):
    """Search YouTube (or take a direct URL) and return a Track.

    yt-dlp is blocking, so it runs in the default executor. Raises
    yt_dlp.utils.DownloadError (or KeyError on a weird extractor result)
    for the caller to turn into a user-facing message.
    """
    def _extract():
        with yt_dlp.YoutubeDL(YTDL_OPTS) as ydl:
            info = ydl.extract_info(query, download=False)
        if info and "entries" in info:
            entries = [e for e in info["entries"] if e]
            info = entries[0] if entries else None
        if not info:
            raise yt_dlp.utils.DownloadError("no results")
        return info

    info = await loop.run_in_executor(None, _extract)
    return Track(info, requested_by)


class HibikiWorker(discord.Client):
    """A command-less, voice-only client. Needs no privileged intents."""

    def __init__(self, pool):
        intents = discord.Intents.none()
        intents.guilds = True
        intents.voice_states = True
        super().__init__(intents=intents)
        self.pool = pool

    @property
    def personality(self):
        # Computed on demand instead of in on_ready, because on_ready is not
        # reliable on initial startup in this bot's runtime (see the
        # InviteTracker cache-priming workaround for the same issue).
        name = (self.user.name if self.user else "").lower()
        for color, p in PERSONALITIES.items():
            if color != "default" and color in name:
                return p
        return PERSONALITIES["default"]

    async def on_voice_state_update(self, member, before, after):
        # If everyone human has left a channel we're playing in, pack up.
        self.pool.check_abandoned(self)


class Session:
    """One worker playing in one voice channel: its queue and player loop."""

    def __init__(self, pool, worker, guild_id, channel_id, text_channel,
                 prepare=None):
        self.pool = pool
        self.worker = worker
        self.guild_id = guild_id
        self.channel_id = channel_id
        self.text_channel = text_channel  # Herupa-side channel for announcements
        self.prepare = prepare  # optional pre-connect hook, may return a cleanup
        self._prepare_cleanup = None
        self.tracks = []
        self.now = None
        self.voice = None
        self.closed = False
        self._user_skipped = False
        self._wakeup = asyncio.Event()
        self.task = None

    # -- controls (called by the Music cog) --

    def add(self, track):
        self.tracks.append(track)
        self._wakeup.set()

    def skip(self):
        if self.voice and (self.voice.is_playing() or self.voice.is_paused()):
            self._user_skipped = True
            self.voice.stop()  # the after-callback advances the loop

    def pause(self):
        if self.voice and self.voice.is_playing():
            self.voice.pause()

    def resume(self):
        if self.voice and self.voice.is_paused():
            self.voice.resume()

    def stop(self):
        self.closed = True
        self.tracks.clear()
        if self.voice and (self.voice.is_playing() or self.voice.is_paused()):
            self.voice.stop()
        self._wakeup.set()

    # -- player loop --

    async def run(self):
        try:
            channel = self.worker.get_channel(self.channel_id)
            if channel is None:
                raise RuntimeError("worker cannot see the voice channel")
            if self.prepare is not None:
                self._prepare_cleanup = await self.prepare(self)
            self.voice = await channel.connect(timeout=15)
        except SessionPrepareError as e:
            self.closed = True
            await self._announce_text(str(e))
            self.pool.release(self)
            return
        except Exception as e:
            print(f"Hibiki connect failed ({self.worker.user}): {e!r}")
            self.closed = True
            await self._announce_text(
                "I couldn't get my DJ into your voice channel. Check that the "
                "bot can see and join it, then try again.")
            self.pool.release(self)
            return

        try:
            while not self.closed:
                if not self.tracks:
                    # Empty queue: linger a bit in case more songs come in.
                    self._wakeup.clear()
                    try:
                        await asyncio.wait_for(self._wakeup.wait(), IDLE_TIMEOUT)
                    except asyncio.TimeoutError:
                        break
                    continue

                track = self.tracks.pop(0)
                self.now = track
                done = asyncio.Event()
                loop = asyncio.get_running_loop()

                # Stream URLs go stale while a track waits its turn (YouTube
                # links expire and get 403'd), so re-resolve any track that
                # wasn't extracted in the last couple of minutes.
                if track.webpage_url and time.monotonic() - track.resolved_at > 120:
                    try:
                        fresh = await resolve_track(loop, track.webpage_url,
                                                    track.requested_by)
                        track.stream_url = fresh.stream_url
                    except Exception as e:
                        print(f"Hibiki re-resolve failed for {track.title}: {e!r}")

                self._user_skipped = False
                started = loop.time()
                try:
                    source = discord.PCMVolumeTransformer(
                        discord.FFmpegPCMAudio(track.stream_url,
                                               before_options=FFMPEG_BEFORE,
                                               options=FFMPEG_OPTS),
                        volume=VOLUME)
                    self.voice.play(
                        source,
                        after=lambda err: loop.call_soon_threadsafe(done.set))
                except Exception as e:
                    print(f"Hibiki playback failed: {e!r}")
                    await self._announce_text(
                        f"I couldn't play **{track.title}**, skipping it.")
                    self.now = None
                    continue

                await self._announce_now_playing(track)
                await done.wait()
                # ffmpeg exiting almost instantly on a long track means the CDN
                # refused the stream (403 etc.) - say so instead of moving on
                # like nothing happened.
                if (not self.closed and not self._user_skipped
                        and track.duration and track.duration > 30
                        and loop.time() - started < 5):
                    print(f"Hibiki stream refused for {track.title} "
                          f"(ffmpeg exited in {loop.time() - started:.1f}s)")
                    await self._announce_text(
                        f"⚠️ **{track.title}** wouldn't stream (the source refused "
                        f"the connection), so I had to skip it.")
                self.now = None
        finally:
            try:
                if self.voice and self.voice.is_connected():
                    await self.voice.disconnect()
            except Exception:
                pass
            if self._prepare_cleanup is not None:
                try:
                    await self._prepare_cleanup()
                except Exception:
                    pass
            self.pool.release(self)

    # -- announcements (sent by Herupa, not the worker, so workers need no
    #    text permissions anywhere) --

    async def _announce_text(self, text):
        try:
            await self.text_channel.send(text)
        except discord.HTTPException:
            pass

    async def _announce_now_playing(self, track):
        p = self.worker.personality
        embed = discord.Embed(
            colour=discord.Colour.from_rgb(*p["color"]),
            description=(f"🎶 Now playing: **[{track.title}]({track.webpage_url})**"
                         if track.webpage_url else
                         f"🎶 Now playing: **{track.title}**"))
        embed.set_author(name=str(self.worker.user.name))
        embed.set_footer(text=f"{p['footer']}  •  {track.pretty_duration()}  •  "
                              f"requested by {track.requested_by}")
        try:
            await self.text_channel.send(embed=embed)
        except discord.HTTPException:
            pass


class HibikiPool:
    def __init__(self, tokens):
        self.tokens = tokens
        self.workers = []
        self.sessions = {}  # (guild_id, channel_id) -> Session
        self._tasks = []

    def start(self):
        loop = asyncio.get_running_loop()
        for token in self.tokens:
            worker = HibikiWorker(self)
            self.workers.append(worker)
            self._tasks.append(loop.create_task(self._run_worker(worker, token)))
            self._tasks.append(loop.create_task(self._post_ready(worker)))

    async def _run_worker(self, worker, token):
        try:
            await worker.start(token)
        except Exception as e:
            print(f"Hibiki worker died: {e!r}")

    async def _post_ready(self, worker):
        # wait_until_ready (internal ready flag) works even when the on_ready
        # EVENT never fires on initial startup, which is a known quirk here.
        await worker.wait_until_ready()
        print(f"Hibiki worker ready: {worker.user} ({worker.user.id})")
        try:
            await worker.change_presence(
                activity=discord.CustomActivity(name=worker.personality["status"]))
        except Exception:
            pass

    async def shutdown(self):
        for session in list(self.sessions.values()):
            session.stop()
        for worker in self.workers:
            try:
                await worker.close()
            except Exception:
                pass
        for t in self._tasks:
            t.cancel()
        self.sessions.clear()
        self.workers.clear()
        self._tasks.clear()

    # -- assignment --

    def session_for(self, guild_id, channel_id):
        # A stopping session is still winding down its voice connection; treat
        # it as gone so commands don't enqueue into a dead player loop.
        session = self.sessions.get((guild_id, channel_id))
        return None if (session and session.closed) else session

    def busy_count(self, guild_id):
        return sum(1 for (g, _c) in self.sessions if g == guild_id)

    def acquire(self, guild_id, channel_id, text_channel, prepare=None):
        """Reserve a free worker for this voice channel, or None if all busy.

        Everything before create_task is synchronous, so two commands arriving
        back to back can never grab the same worker.
        """
        existing = self.session_for(guild_id, channel_id)
        if existing:
            return existing

        taken = {s.worker for (g, _c), s in self.sessions.items() if g == guild_id}
        for worker in self.workers:
            if worker in taken or not worker.is_ready():
                continue
            if worker.get_guild(guild_id) is None:
                continue  # not invited to this server (yet)
            session = Session(self, worker, guild_id, channel_id, text_channel,
                              prepare=prepare)
            self.sessions[(guild_id, channel_id)] = session
            session.task = asyncio.get_running_loop().create_task(session.run())
            return session
        return None

    def release(self, session):
        key = (session.guild_id, session.channel_id)
        if self.sessions.get(key) is session:
            del self.sessions[key]

    def check_abandoned(self, worker):
        """Stop any of this worker's sessions whose channel has no humans left."""
        for (g, c), session in list(self.sessions.items()):
            if session.worker is not worker or session.voice is None:
                continue
            channel = worker.get_channel(c)
            if channel is not None and not any(not m.bot for m in channel.members):
                session.stop()
