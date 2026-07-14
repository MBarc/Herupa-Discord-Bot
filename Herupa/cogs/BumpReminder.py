'''
Purpose: Keep the server's bump-based discovery alive without spamming pings.

For each configured bump bot, when it confirms a successful bump Herupa awards
the member who ran /bump 10x a normal message's worth of XP (via the Leveling
cog) and thanks them.

Reminders are a gentle nudge, not a per-cooldown alarm: Herupa pings the opt-in
"bump squad" role only if NOBODY has bumped (on any listing) for REMINDER_INTERVAL.
If people bump on their own, no one ever gets pinged. Any bump resets the timer.

Each bot's confirmation carries the bumper's identity in its interaction
metadata. State is per guild in Mongo and survives restarts. Add a bump bot by
adding a BUMP_BOTS entry (its user id + a phrase from its success message).
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

# bot user id -> {name, phrase from its "bump succeeded" message}
BUMP_BOTS = {
    302050872383242240: {"name": "DISBOARD", "phrase": "bump done"},
    1222548162741538938: {"name": "Discadia", "phrase": "has been successfully bumped"},
}
BUMP_SQUAD_ROLE = "bump squad"
BUMP_XP = (150, 250)                     # 10x a normal message (15-25)
REMINDER_INTERVAL = 3 * 24 * 60 * 60     # nudge only after 3 days with no bump
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
        im = getattr(message, "interaction_metadata", None)
        if im is not None and getattr(im, "user", None):
            return im.user.id
        it = getattr(message, "interaction", None)
        if it is not None and getattr(it, "user", None):
            return it.user.id
        return None

    @staticmethod
    def _matches(message, phrase):
        if phrase in ((message.content or "").lower()):
            return True
        return any(phrase in ((e.description or "").lower()) for e in message.embeds)

    @commands.Cog.listener()
    async def on_message(self, message):
        if message.guild is None:
            return
        bot = BUMP_BOTS.get(message.author.id)
        if bot is None or not self._matches(message, bot["phrase"]):
            return

        # Any bump resets the guild's nudge timer.
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
            await message.channel.send(f"🔝 Thanks for bumping on {bot['name']}, {who}! (+{amount} XP)")
        except discord.HTTPException:
            pass

    @tasks.loop(hours=1)
    async def reminder_check(self):
        now = time.time()
        for doc in self._col().find():
            if doc.get("reminded") or not doc.get("last_bump"):
                continue
            if now - doc["last_bump"] < REMINDER_INTERVAL:
                continue
            guild = self.client.get_guild(int(doc["_id"]))
            channel = guild.get_channel(doc.get("channel_id")) if guild else None
            if channel is None:
                continue
            role = discord.utils.get(guild.roles, name=BUMP_SQUAD_ROLE)
            mention = role.mention if role else "@here"
            try:
                await channel.send(
                    f"🔔 {mention} it's been a few days since our last bump. A quick `/bump` on "
                    f"DISBOARD or Discadia helps new people find us. Thanks! 🚀",
                    allowed_mentions=discord.AllowedMentions(roles=True, everyone=True))
                self._col().update_one({"_id": doc["_id"]}, {"$set": {"reminded": True}})
            except discord.HTTPException:
                pass


async def setup(client):
    await client.add_cog(BumpReminder(client))
