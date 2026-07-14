'''
Purpose: Keep DISBOARD bumping alive so the server stays discoverable.

- When DISBOARD confirms a bump ("Bump done!"), award the member who ran /bump
  10x a normal message's worth of XP (via the Leveling cog) and thank them.
- Two hours later (the bump cooldown) ping the opt-in "bump squad" role in that
  channel so someone remembers to bump again.

DISBOARD's confirmation carries the bumper's identity in its interaction
metadata, so we can credit the right person. Reminder state lives in Mongo so
it survives restarts. Easy to extend to other bump bots (Discadia, Disforge) by
adding their bot IDs and "done" phrases.
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

DISBOARD_ID = 302050872383242240
BUMP_COOLDOWN = 2 * 60 * 60      # 2 hours, DISBOARD's cooldown
BUMP_SQUAD_ROLE = "bump squad"
BUMP_XP = (150, 250)             # 10x a normal message (15-25)
DB, COL = "bump", "state"


class BumpReminder(commands.Cog):

    def __init__(self, client):
        self.client = client
        self.mongo = HerupaMongo()

    async def cog_load(self):
        self.reminder_check.start()

    async def cog_unload(self):
        self.reminder_check.cancel()

    def _col(self):
        return self.mongo.client[DB][COL]

    @staticmethod
    def _bumper_id(message):
        """Who ran /bump, from the confirmation's interaction metadata."""
        im = getattr(message, "interaction_metadata", None)
        if im is not None and getattr(im, "user", None):
            return im.user.id
        it = getattr(message, "interaction", None)
        if it is not None and getattr(it, "user", None):
            return it.user.id
        return None

    @commands.Cog.listener()
    async def on_message(self, message):
        if message.guild is None or message.author.id != DISBOARD_ID:
            return
        if not any("bump done" in ((e.description or "").lower()) for e in message.embeds):
            return

        # Reset the reminder clock for this channel.
        self._col().update_one(
            {"_id": str(message.guild.id)},
            {"$set": {"last_bump": time.time(), "channel_id": message.channel.id, "reminded": False}},
            upsert=True)

        # Reward the bumper.
        bumper_id = self._bumper_id(message)
        if not bumper_id:
            return
        amount = random.randint(*BUMP_XP)
        member = message.guild.get_member(bumper_id)
        lvl = self.client.get_cog("Leveling")
        if lvl is not None:
            old, new = lvl._add_xp(bumper_id, amount)
            if new > old and member is not None:
                await lvl._announce(message.channel, member, new)
        who = member.mention if member else "friend"
        try:
            await message.channel.send(f"🔝 Thanks for the bump, {who}! (+{amount} XP)")
        except discord.HTTPException:
            pass

    @tasks.loop(minutes=5)
    async def reminder_check(self):
        now = time.time()
        for doc in self._col().find():
            if doc.get("reminded") or not doc.get("last_bump"):
                continue
            if now - doc["last_bump"] < BUMP_COOLDOWN:
                continue
            guild = self.client.get_guild(int(doc["_id"]))
            channel = guild.get_channel(doc.get("channel_id")) if guild else None
            if channel is None:
                continue
            role = discord.utils.get(guild.roles, name=BUMP_SQUAD_ROLE)
            mention = role.mention if role else "@here"
            try:
                await channel.send(
                    f"🔔 {mention} it's been 2 hours! The server can be bumped again. "
                    f"Run `/bump` to keep us growing. 🚀",
                    allowed_mentions=discord.AllowedMentions(roles=True, everyone=True))
                self._col().update_one({"_id": doc["_id"]}, {"$set": {"reminded": True}})
            except discord.HTTPException:
                pass


async def setup(client):
    await client.add_cog(BumpReminder(client))
