# The mock machine: Herupa joins a voice channel and, for a while, repeats
# everything one member says right back at them. Sold through the level shop
# ($buy mock @user, see Shop.py) — the $mock command just points there.
#
# Fleeing doesn't help: time left on the clock is stored as a debt in Mongo
# (db "mockdebt"), and the moment the target shows up in any voice channel in
# the guild again, Herupa follows them in and serves the remainder.
#
# Audio never touches disk; each clip lives in memory only and is replayed
# solely into the same channel that just heard it live, then dropped.

import asyncio
import io
import logging

import discord
from discord.ext import commands, voice_recv

from tools.HerupaMongo import HerupaMongo

# The bot never configures logging (custom client.start() path), so the
# extension's warnings — e.g. dropped/undecryptable voice packets — would
# vanish. Bridge them to stderr where journald can see them.
_vr_logger = logging.getLogger("discord.ext.voice_recv")
if not _vr_logger.handlers:
    _handler = logging.StreamHandler()
    _handler.setFormatter(logging.Formatter("[voice_recv] %(levelname)s %(message)s"))
    _vr_logger.addHandler(_handler)
    _vr_logger.setLevel(logging.INFO)

UTTERANCE_CAP_SECONDS = 10  # chop monologues into clips this long
MIN_CLIP_SECONDS = 0.4      # ignore blips shorter than this
DEBT_FLOOR_SECONDS = 3      # fleeing with less than this left counts as served
# Discord voice PCM: 48kHz, 16-bit, stereo
BYTES_PER_SECOND = 48000 * 2 * 2


class ParrotSink(voice_recv.AudioSink):
    """Buffers PCM from one member and queues a clip each time they pause.

    write() and the speaking listener run on the receive thread, so clips are
    handed to the event loop with call_soon_threadsafe.
    """

    def __init__(self, loop, target_id, clips):
        super().__init__()
        self.loop = loop
        self.target_id = target_id
        self.clips = clips
        self.buffer = bytearray()
        self._seen = set()  # user ids we've logged a first packet for

    def wants_opus(self):
        return False

    def _flush(self):
        if len(self.buffer) >= MIN_CLIP_SECONDS * BYTES_PER_SECOND:
            clip = bytes(self.buffer)
            print(f"[Mock] queueing clip: {len(clip) / BYTES_PER_SECOND:.1f}s")
            self.loop.call_soon_threadsafe(self.clips.put_nowait, clip)
        self.buffer.clear()

    def write(self, user, data):
        uid = getattr(user, "id", None)
        if uid not in self._seen:
            self._seen.add(uid)
            print(f"[Mock] first packet from {user} (want {self.target_id})")
        if user is None or user.id != self.target_id:
            return
        self.buffer += data.pcm
        if len(self.buffer) >= UTTERANCE_CAP_SECONDS * BYTES_PER_SECOND:
            self._flush()

    @voice_recv.AudioSink.listener()
    def on_voice_member_speaking_stop(self, member):
        print(f"[Mock] speaking stop: {member} (buffered "
              f"{len(self.buffer) / BYTES_PER_SECOND:.1f}s)")
        if member.id == self.target_id:
            self._flush()

    def cleanup(self):
        pass


class Mock(commands.Cog):

    def __init__(self, client):
        self.client = client
        self.mongo = HerupaMongo()
        self.active_guilds = set()

    # --------------------------- mock debts ---------------------------

    def _debts(self):
        return self.mongo.client["mockdebt"]["pending"]

    def add_debt(self, guild_id, target_id, buyer_id, channel_id, remaining):
        """Bank unserved mock seconds; stacks if the target already owes."""
        self._debts().update_one(
            {"_id": f"{guild_id}:{target_id}"},
            {"$inc": {"remaining": float(remaining)},
             "$set": {"guild_id": guild_id, "target_id": target_id,
                      "buyer_id": buyer_id, "channel_id": channel_id}},
            upsert=True)

    @commands.Cog.listener()
    async def on_voice_state_update(self, member, before, after):
        # Debt collection: any voice appearance by a debtor (join, move, even
        # an unmute while Herupa happened to be busy earlier) can trigger it.
        if member.bot or after.channel is None:
            return
        if (member.guild.id in self.active_guilds
                or member.guild.voice_client is not None):
            return
        doc = self._debts().find_one_and_delete(
            {"_id": f"{member.guild.id}:{member.id}"})
        if not doc:
            return
        text = self.client.get_channel(doc.get("channel_id"))
        if text is not None:
            try:
                await text.send(
                    f"🦜 {member.mention} thought they escaped... "
                    f"**{int(doc['remaining'])}s** of mocking left on the clock!")
            except discord.HTTPException:
                pass
        status, remaining = await self.run_mock(after.channel, member,
                                                doc["remaining"])
        if status in ("fled", "nojoin"):
            # still owed — bank it again for their next appearance
            self.add_debt(member.guild.id, member.id,
                          doc.get("buyer_id"), doc.get("channel_id"), remaining)

    # --------------------------- the mock itself ---------------------------

    async def run_mock(self, voice_channel, target, duration):
        """Parrot `target` in `voice_channel` for `duration` seconds.

        Returns (status, remaining_seconds):
          "done"   — clock ran out with them present and clips were played
          "silent" — clock ran out and they never said a word
          "fled"   — they left early; `remaining` seconds still owed
          "nojoin" — couldn't (or shouldn't) connect to the channel
        """
        guild = voice_channel.guild
        if guild.id in self.active_guilds or guild.voice_client is not None:
            return "nojoin", duration
        self.active_guilds.add(guild.id)
        vc = None
        delivered = False
        try:
            try:
                vc = await voice_channel.connect(cls=voice_recv.VoiceRecvClient,
                                                 timeout=15)
            except Exception as e:
                print(f"[Mock] connect failed: {e!r}")
                return "nojoin", duration
            print(f"[Mock] connected to {voice_channel.name}, "
                  f"listening for {target} ({duration:.0f}s)")

            # A server-deafened bot receives no audio at all (while still
            # able to play), so make sure we can actually hear.
            me_voice = guild.me.voice
            if me_voice is not None:
                print(f"[Mock] my voice state: deaf={me_voice.deaf} "
                      f"self_deaf={me_voice.self_deaf} mute={me_voice.mute}")
                if me_voice.deaf:
                    try:
                        await guild.me.edit(deafen=False)
                        print("[Mock] I was server-deafened; undeafened myself")
                    except discord.HTTPException as e:
                        print(f"[Mock] couldn't undeafen myself: {e!r}")

            loop = asyncio.get_running_loop()
            clips = asyncio.Queue()
            vc.listen(ParrotSink(loop, target.id, clips))

            end = loop.time() + duration
            while True:
                remaining = end - loop.time()
                if remaining <= 0:
                    break
                if target.voice is None or target.voice.channel != voice_channel:
                    if remaining > DEBT_FLOOR_SECONDS:
                        return "fled", remaining
                    break
                try:
                    clip = await asyncio.wait_for(clips.get(),
                                                  timeout=min(2.0, remaining))
                except asyncio.TimeoutError:
                    continue
                finished = asyncio.Event()
                print(f"[Mock] playing clip: {len(clip) / BYTES_PER_SECOND:.1f}s")
                vc.play(discord.PCMAudio(io.BytesIO(clip)),
                        after=lambda err: loop.call_soon_threadsafe(finished.set))
                delivered = True
                await finished.wait()

            print(f"[Mock] finished, delivered={delivered}")
            return ("done" if delivered else "silent"), 0
        finally:
            self.active_guilds.discard(guild.id)
            if vc is not None:
                try:
                    await vc.disconnect()
                except Exception:
                    pass

    @commands.command(name="mock")
    async def mock(self, ctx):
        if ctx.guild is None:
            return
        await ctx.channel.send(
            "Mocking is a shop item! While you're in a voice channel with your "
            "victim, use `$buy mock @member` and I'll repeat everything they "
            "say for a whole minute. See `$shop`.")


async def setup(client):
    await client.add_cog(Mock(client))
