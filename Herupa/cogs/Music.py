# Herupa is the DJ dispatcher: she owns every music command and hands the
# actual playing to whichever Hibiki worker bot is free (see tools/HibikiPool).
# Workers are configured with MUSIC_BOT_TOKENS (comma-separated bot tokens);
# adding a fourth bot is just appending its token and restarting.

import os

import discord
import yt_dlp
from discord.ext import commands

from tools.HibikiPool import (HibikiPool, SessionPrepareError, resolve_track,
                              MAX_QUEUE)


class Music(commands.Cog):

    def __init__(self, client):
        self.client = client
        self.pool = HibikiPool([])

    async def cog_load(self):
        tokens = [t.strip() for t in
                  os.environ.get("MUSIC_BOT_TOKENS", "").split(",") if t.strip()]
        self.pool = HibikiPool(tokens)
        if tokens:
            self.pool.start()
            print(f"Music: starting {len(tokens)} Hibiki worker(s)")
        else:
            print("Music: MUSIC_BOT_TOKENS not set, music commands are disabled")

    async def cog_unload(self):
        # cogwatch hot-reloads cogs on file changes; without this the old
        # worker clients would stay logged in alongside the new ones.
        await self.pool.shutdown()

    # -- helpers --

    async def _prepare_channel(self, session):
        """Get the worker into a private voice channel before it connects.

        Private rooms deny @everyone View Channel, which blocks voice
        connects outright (Discord ignores a connect into a channel the bot
        can't see, so it would just time out). If the assigned worker can't
        see/join the channel, Herupa grants it a channel overwrite and hands
        back a cleanup that removes the overwrite when the session ends.
        The permission checks are local cache reads; the only API calls are
        the grant/ungrant, and only for locked channels.
        """
        worker_guild = session.worker.get_guild(session.guild_id)
        channel = worker_guild.get_channel(session.channel_id) if worker_guild else None
        if channel is None:
            return None
        worker_me = worker_guild.me
        perms = channel.permissions_for(worker_me)
        if perms.view_channel and perms.connect and perms.speak:
            return None

        cannot_fix = SessionPrepareError(
            f"**{channel.name}** is private and I'm not able to unlock it. "
            f"Give **{session.worker.user.name}** access to it, then try again.")
        my_channel = self.client.get_channel(session.channel_id)
        if (my_channel is None or
                not my_channel.permissions_for(my_channel.guild.me).manage_roles):
            raise cannot_fix
        try:
            await my_channel.set_permissions(
                worker_me, view_channel=True, connect=True, speak=True,
                reason="Hibiki DJ dispatched to a private voice channel")
        except discord.HTTPException:
            raise cannot_fix

        async def remove_grant():
            await my_channel.set_permissions(
                worker_me, overwrite=None,
                reason="Hibiki DJ session ended, removing temporary access")
        return remove_grant

    def _author_session(self, ctx):
        """The session playing in the invoker's current voice channel, if any."""
        if ctx.guild is None or ctx.author.voice is None:
            return None
        return self.pool.session_for(ctx.guild.id, ctx.author.voice.channel.id)

    async def _require_session(self, ctx):
        if ctx.guild is None:
            return None
        if ctx.author.voice is None:
            await ctx.channel.send("You need to be in a voice channel for that.")
            return None
        session = self._author_session(ctx)
        if session is None:
            await ctx.channel.send("No Hibiki is playing in your voice channel.")
        return session

    # -- commands --

    @commands.command(name="music", aliases=["play"])
    async def music(self, ctx):
        if ctx.guild is None:
            return
        if not self.pool.workers:
            await ctx.channel.send("My music crew isn't set up yet.")
            return

        parts = ctx.message.content.split(" ", 1)
        query = parts[1].strip() if len(parts) > 1 else ""
        if not query:
            await ctx.channel.send("Tell me what to play: `$music <song name or link>`")
            return

        if ctx.author.voice is None:
            await ctx.channel.send("Hop into a voice channel first, then ask again!")
            return
        channel = ctx.author.voice.channel

        session = self.pool.session_for(ctx.guild.id, channel.id)
        is_new = session is None
        if is_new:
            session = self.pool.acquire(ctx.guild.id, channel.id, ctx.channel,
                                        prepare=self._prepare_channel)
            if session is None:
                n = len(self.pool.workers)
                await ctx.channel.send(
                    f"All {n} of my DJs are on the decks right now. "
                    "Try again in a bit!")
                return

        if len(session.tracks) >= MAX_QUEUE:
            await ctx.channel.send(
                f"That channel's queue is full ({MAX_QUEUE} songs). "
                "Let a few finish first.")
            return

        async with ctx.typing():
            try:
                track = await resolve_track(self.client.loop, query, ctx.author.display_name)
            except (yt_dlp.utils.DownloadError, KeyError):
                await ctx.channel.send(f"I couldn't find anything for **{query}**.")
                if is_new:
                    session.stop()
                return

        if session.closed:
            # The session died while we were resolving (couldn't join the
            # channel); it already announced why, so don't cheer over it.
            return

        if is_new:
            p = session.worker.personality
            join_line = p["join"].format(name=session.worker.user.name)
            embed = discord.Embed(colour=discord.Colour.from_rgb(*p["color"]),
                                  description=join_line)
            await ctx.channel.send(embed=embed)

        session.add(track)
        if session.now is not None:
            await ctx.channel.send(
                f"Queued **{track.title}** (position {len(session.tracks)}).")
        # If nothing is playing, the session announces "Now playing" itself.

    @commands.command(name="skip")
    async def skip(self, ctx):
        session = await self._require_session(ctx)
        if session is None:
            return
        if session.now is None:
            await ctx.channel.send("Nothing is playing to skip.")
            return
        await ctx.channel.send(f"Skipping **{session.now.title}**.")
        session.skip()

    @commands.command(name="pause")
    async def pause(self, ctx):
        session = await self._require_session(ctx)
        if session is None:
            return
        session.pause()
        await ctx.message.add_reaction("⏸️")

    @commands.command(name="resume")
    async def resume(self, ctx):
        session = await self._require_session(ctx)
        if session is None:
            return
        session.resume()
        await ctx.message.add_reaction("▶️")

    @commands.command(name="stop")
    async def stop(self, ctx):
        session = await self._require_session(ctx)
        if session is None:
            return
        name = session.worker.user.name
        session.stop()
        await ctx.channel.send(f"Sending {name} home. Thanks for listening!")

    @commands.command(name="queue", aliases=["q"])
    async def queue(self, ctx):
        session = await self._require_session(ctx)
        if session is None:
            return
        p = session.worker.personality
        embed = discord.Embed(colour=discord.Colour.from_rgb(*p["color"]))
        embed.set_author(name=f"{session.worker.user.name}'s queue")
        now = session.now.title if session.now else "nothing (queue is warming up)"
        embed.add_field(name="Now playing", value=now, inline=False)
        if session.tracks:
            upcoming = "\n".join(f"{i + 1}. {t.title}"
                                 for i, t in enumerate(session.tracks[:10]))
            if len(session.tracks) > 10:
                upcoming += f"\n...and {len(session.tracks) - 10} more"
            embed.add_field(name="Up next", value=upcoming, inline=False)
        await ctx.channel.send(embed=embed)

    @commands.command(name="np", aliases=["nowplaying"])
    async def np(self, ctx):
        session = await self._require_session(ctx)
        if session is None:
            return
        if session.now is None:
            await ctx.channel.send("Nothing is playing right now.")
            return
        await session._announce_now_playing(session.now)


async def setup(client):
    await client.add_cog(Music(client))
