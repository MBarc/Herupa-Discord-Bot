'''
Purpose: Mirror Herupa's activity to a dedicated logging server.

Additive and passive — it only listens to gateway events and forwards them to
the logging server (see tools/HerupaLogger). It changes nothing about Chill
Club's existing in-server logging. Streams:
  - error   : command errors
  - mod     : bans / unbans / timeouts
  - activity: message deletes & edits, voice changes, joins & leaves
  - ops     : connect / resume (bot health)

Create these channels in the logging server: error-log, mod-log,
activity-log, ops-log.
'''

import sys
import os

import discord
from discord.ext import commands

current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
sys.path.append(parent_dir)

from tools.HerupaLogger import HerupaLogger, LOG_GUILD_ID


def _who(user):
    return f"{user} (`{user.id}`)"


class CentralLog(commands.Cog):

    def __init__(self, client):
        self.client = client
        self.log = HerupaLogger(client)

    async def _send(self, kind, title, desc, colour, guild=None):
        embed = discord.Embed(title=title, description=desc, colour=colour,
                              timestamp=discord.utils.utcnow())
        if guild:
            embed.set_footer(text=guild.name)
        await self.log.send(kind, embed=embed)

    def _skip_guild(self, guild):
        # Don't log the logging server's own noise back into itself.
        return guild is None or guild.id == LOG_GUILD_ID

    # ------------------------- ops -------------------------

    @commands.Cog.listener()
    async def on_ready(self):
        await self._send("ops", "✅ Herupa connected",
                         f"Logged in as **{self.client.user}** · watching {len(self.client.guilds)} server(s).",
                         0x3ECF8E)

    @commands.Cog.listener()
    async def on_resumed(self):
        await self._send("ops", "🔄 Session resumed",
                         "Gateway session resumed after a disconnect.", 0xF2B24E)

    # ------------------------- activity -------------------------

    @commands.Cog.listener()
    async def on_message_delete(self, message):
        if message.author.bot or self._skip_guild(message.guild):
            return
        content = message.content or "*(no text — embed or attachment)*"
        await self._send("activity", "🗑️ Message deleted",
                         f"**Author:** {_who(message.author)}\n**Channel:** {message.channel.mention}\n"
                         f"**Content:** {content[:1500]}", 0xF0546C, guild=message.guild)

    @commands.Cog.listener()
    async def on_message_edit(self, before, after):
        if after.author.bot or self._skip_guild(after.guild) or before.content == after.content:
            return
        await self._send("activity", "✏️ Message edited",
                         f"**Author:** {_who(after.author)}\n**Channel:** {after.channel.mention}\n"
                         f"**Before:** {(before.content or '')[:700]}\n**After:** {(after.content or '')[:700]}",
                         0xF2B24E, guild=after.guild)

    @commands.Cog.listener()
    async def on_voice_state_update(self, member, before, after):
        if self._skip_guild(member.guild) or before.channel == after.channel:
            return
        if before.channel is None:
            desc = f"{_who(member)} joined **{after.channel.name}**"
        elif after.channel is None:
            desc = f"{_who(member)} left **{before.channel.name}**"
        else:
            desc = f"{_who(member)} moved **{before.channel.name}** → **{after.channel.name}**"
        await self._send("activity", "🔊 Voice update", desc, 0x5865F2, guild=member.guild)

    @commands.Cog.listener()
    async def on_member_join(self, member):
        if self._skip_guild(member.guild):
            return
        await self._send("activity", "📥 Member joined", _who(member), 0x3ECF8E, guild=member.guild)

    @commands.Cog.listener()
    async def on_member_remove(self, member):
        if self._skip_guild(member.guild):
            return
        await self._send("activity", "📤 Member left", _who(member), 0x888888, guild=member.guild)

    # ------------------------- moderation -------------------------

    @commands.Cog.listener()
    async def on_member_ban(self, guild, user):
        if self._skip_guild(guild):
            return
        await self._send("mod", "🔨 Member banned", _who(user), 0xF0546C, guild=guild)

    @commands.Cog.listener()
    async def on_member_unban(self, guild, user):
        if self._skip_guild(guild):
            return
        await self._send("mod", "♻️ Member unbanned", _who(user), 0x3ECF8E, guild=guild)

    @commands.Cog.listener()
    async def on_member_update(self, before, after):
        if self._skip_guild(after.guild) or before.timed_out_until == after.timed_out_until:
            return
        if after.timed_out_until:
            desc = f"{_who(after)} timed out until {discord.utils.format_dt(after.timed_out_until, 'f')}"
            await self._send("mod", "⏳ Member timed out", desc, 0xF2B24E, guild=after.guild)
        else:
            await self._send("mod", "⌛ Timeout removed", _who(after), 0x3ECF8E, guild=after.guild)

    # ------------------------- errors -------------------------

    @commands.Cog.listener()
    async def on_command_error(self, ctx, error):
        if isinstance(error, commands.CommandNotFound):
            return
        await self._send("error", "⚠️ Command error",
                         f"**Command:** {ctx.message.content[:500]}\n**By:** {_who(ctx.author)}\n"
                         f"**Error:** `{str(error)[:800]}`", 0xF0546C, guild=ctx.guild)


async def setup(client):
    await client.add_cog(CentralLog(client))
