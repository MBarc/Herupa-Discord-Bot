'''
Purpose: Keep Herupa from lingering in voice channels.

Two rules:
  1. Idle timeout: if Herupa is connected to a voice channel and nothing has
     happened for IDLE_TIMEOUT seconds (no voice command used and no audio
     playing), she disconnects.
  2. Never alone: if Herupa is the only member left in a voice channel with no
     humans present, she leaves immediately.

The idle timer is reset when Herupa joins/moves, when a voice command is used
(uwu / herupasay), and while audio is actively playing.
'''

import time

import discord
from discord.ext import commands, tasks

IDLE_TIMEOUT = 600      # seconds of no interaction before Herupa leaves (10 min)
CHECK_INTERVAL = 30     # how often (seconds) the idle check runs
VOICE_COMMANDS = {"uwu", "herupasay"}  # commands that count as interacting with her


class VoiceManager(commands.Cog):

    def __init__(self, client):
        self.client = client
        self.last_active = {}  # guild_id -> unix timestamp of last interaction

    async def cog_load(self):
        self.idle_check.start()

    async def cog_unload(self):
        self.idle_check.cancel()

    def _touch(self, guild_id):
        self.last_active[guild_id] = time.time()

    @staticmethod
    def _has_humans(channel):
        return any(not m.bot for m in channel.members)

    async def _leave(self, voice_client):
        guild_id = voice_client.guild.id
        try:
            await voice_client.disconnect(force=True)
        except Exception:
            pass
        self.last_active.pop(guild_id, None)

    async def _leave_if_alone(self):
        """Leave any voice channel Herupa is in that has no humans left."""
        for vc in list(self.client.voice_clients):
            if vc.channel is not None and not self._has_humans(vc.channel):
                await self._leave(vc)

    # Using a voice command counts as interacting with her -> reset idle timer.
    @commands.Cog.listener()
    async def on_command_completion(self, ctx):
        if ctx.guild and ctx.command and ctx.command.name in VOICE_COMMANDS:
            self._touch(ctx.guild.id)

    @commands.Cog.listener()
    async def on_voice_state_update(self, member, before, after):
        # When Herupa herself connects or moves, (re)start her idle timer.
        if member.id == self.client.user.id and after.channel is not None:
            self._touch(member.guild.id)

        # Any voice movement could have emptied her channel of humans.
        await self._leave_if_alone()

    @tasks.loop(seconds=CHECK_INTERVAL)
    async def idle_check(self):
        now = time.time()
        for vc in list(self.client.voice_clients):
            if vc.channel is None:
                continue
            # Never sit alone, even if this fires between voice-state updates.
            if not self._has_humans(vc.channel):
                await self._leave(vc)
                continue
            # Actively playing audio counts as active.
            if vc.is_playing():
                self._touch(vc.guild.id)
                continue
            last = self.last_active.get(vc.guild.id)
            if last is None:
                # No record yet (e.g. just after a restart) -> start the clock.
                self._touch(vc.guild.id)
                continue
            if now - last >= IDLE_TIMEOUT:
                await self._leave(vc)


async def setup(client):
    await client.add_cog(VoiceManager(client))
