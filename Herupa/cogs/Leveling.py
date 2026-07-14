'''
Purpose: XP / leveling system (replaces MEE6 + Amari leveling).

Members earn XP by being active:
  - Messages: a random MSG_XP amount, at most once every MSG_COOLDOWN seconds.
  - Voice: a random VOICE_XP amount every VOICE_INTERVAL seconds, but only when
    they're not alone, not in the AFK channel, and not self-deafened.

Levels use MEE6's curve. On a level-up Herupa announces in the channel where it
happened (the message's channel, or the voice channel's text chat for voice).
$rank shows a member's level and progress. Seed starting XP from the migrated
Amari/MEE6 levels with tools/scripts (see ~/level_migration on the Pi).
'''

import os
import random
import sys
import time

import discord
from discord.ext import commands, tasks

current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
sys.path.append(parent_dir)

from tools.HerupaMongo import HerupaMongo

DB, COL = "leveling", "members"
MSG_XP = (15, 25)
MSG_COOLDOWN = 60          # seconds between XP-earning messages, per member
VOICE_XP = 5               # flat XP granted per minute in voice
VOICE_INTERVAL = 60        # seconds; the voice XP loop runs on this cadence
PINK = discord.Colour.from_rgb(255, 183, 197)


# ----- MEE6 level curve --------------------------------------------------------
def xp_to_advance(level):
    """XP needed to go from `level` to `level`+1."""
    return 5 * level * level + 50 * level + 100


def total_xp_for_level(level):
    """Total XP required to have reached `level`."""
    return sum(xp_to_advance(n) for n in range(level))


def level_for_xp(total_xp):
    """(level, xp_into_level, xp_needed_for_next) for a total XP amount."""
    level, remaining = 0, int(total_xp)
    while remaining >= xp_to_advance(level):
        remaining -= xp_to_advance(level)
        level += 1
    return level, remaining, xp_to_advance(level)


class Leveling(commands.Cog):

    def __init__(self, client):
        self.client = client
        self.mongo = HerupaMongo()
        self._msg_cooldown = {}  # user_id -> unix ts of last XP-earning message

    async def cog_load(self):
        self.voice_xp.start()

    async def cog_unload(self):
        self.voice_xp.cancel()

    # ----- storage -----
    def _col(self):
        return self.mongo.client[DB][COL]

    def _xp(self, user_id):
        doc = self._col().find_one({"_id": str(user_id)})
        return int(doc["xp"]) if doc and "xp" in doc else 0

    def _add_xp(self, user_id, amount):
        """Add XP; return (old_level, new_level)."""
        old = self._xp(user_id)
        self._col().update_one({"_id": str(user_id)}, {"$inc": {"xp": amount}}, upsert=True)
        return level_for_xp(old)[0], level_for_xp(old + amount)[0]

    async def _announce(self, channel, member, new_level):
        if channel is None:
            return
        try:
            await channel.send(f"🎉 GG {member.mention}, you reached **level {new_level}**!")
        except discord.HTTPException:
            pass

    # ----- earning: messages -----
    @commands.Cog.listener()
    async def on_message(self, message):
        if message.author.bot or message.guild is None:
            return
        now = time.time()
        if now - self._msg_cooldown.get(message.author.id, 0) < MSG_COOLDOWN:
            return
        self._msg_cooldown[message.author.id] = now
        old, new = self._add_xp(message.author.id, random.randint(*MSG_XP))
        if new > old:
            await self._announce(message.channel, message.author, new)

    # ----- earning: voice -----
    @tasks.loop(seconds=VOICE_INTERVAL)
    async def voice_xp(self):
        for guild in self.client.guilds:
            afk_id = guild.afk_channel.id if guild.afk_channel else None
            for vc in guild.voice_channels:
                if vc.id == afk_id:
                    continue
                humans = [m for m in vc.members if not m.bot]
                if len(humans) < 2:   # not alone: needs at least one other person
                    continue
                for m in humans:
                    if m.voice and m.voice.self_deaf:
                        continue
                    old, new = self._add_xp(m.id, VOICE_XP)
                    if new > old:
                        await self._announce(vc, m, new)

    # ----- lookup -----
    @commands.guild_only()
    @commands.command(name="rank", aliases=["level", "lvl"])
    async def rank(self, ctx, member: discord.Member = None):
        """Show a member's level and XP progress."""
        member = member or ctx.author
        total = self._xp(member.id)
        level, into, need = level_for_xp(total)

        # rank position among everyone with XP
        all_xp = sorted((int(d.get("xp", 0)) for d in self._col().find()), reverse=True)
        position = all_xp.index(total) + 1 if total in all_xp else len(all_xp) + 1

        filled = int((into / need) * 12) if need else 0
        bar = "▰" * filled + "▱" * (12 - filled)

        embed = discord.Embed(colour=PINK)
        embed.set_author(name=f"{member.display_name} · Level {level}",
                         icon_url=member.display_avatar.url)
        embed.add_field(name="Progress", value=f"{bar}\n{into:,} / {need:,} XP to level {level + 1}", inline=False)
        embed.add_field(name="Total XP", value=f"{total:,}", inline=True)
        embed.add_field(name="Server rank", value=f"#{position}", inline=True)
        await ctx.send(embed=embed)


async def setup(client):
    await client.add_cog(Leveling(client))
