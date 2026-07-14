'''
Purpose: Keep the server's bump-based discovery alive across multiple listing
bots.

For each configured bump bot, when it confirms a successful bump Herupa awards
the member who ran /bump 10x a normal message's worth of XP (via the Leveling
cog) and thanks them. After that bot's cooldown, Herupa pings the opt-in "bump
squad" role in that channel so someone bumps again.

Each bot's confirmation carries the bumper's identity in its interaction
metadata, so we credit the right person. Reminder state is per (guild, bot) in
Mongo, so different bots with different cooldowns each get their own timer and
everything survives restarts. Add a new bump bot by adding a BUMP_BOTS entry.
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

# bot user id -> how to detect its "bump succeeded" message + its cooldown
BUMP_BOTS = {
    302050872383242240: {"name": "DISBOARD", "phrase": "bump done", "cooldown": 2 * 60 * 60},
    1222548162741538938: {"name": "Discadia", "phrase": "has been successfully bumped", "cooldown": 24 * 60 * 60},
}
BUMP_SQUAD_ROLE = "bump squad"
BUMP_XP = (150, 250)   # 10x a normal message (15-25)
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

        # Reset this bot's reminder clock for this guild.
        self._col().update_one(
            {"_id": f"{message.guild.id}:{message.author.id}"},
            {"$set": {"guild_id": message.guild.id, "bot_id": message.author.id,
                      "last_bump": time.time(), "channel_id": message.channel.id, "reminded": False}},
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

    @tasks.loop(minutes=5)
    async def reminder_check(self):
        now = time.time()
        for doc in self._col().find():
            bot = BUMP_BOTS.get(doc.get("bot_id"))
            if bot is None or doc.get("reminded") or not doc.get("last_bump"):
                continue
            if now - doc["last_bump"] < bot["cooldown"]:
                continue
            guild = self.client.get_guild(int(doc["guild_id"]))
            channel = guild.get_channel(doc.get("channel_id")) if guild else None
            if channel is None:
                continue
            role = discord.utils.get(guild.roles, name=BUMP_SQUAD_ROLE)
            mention = role.mention if role else "@here"
            try:
                await channel.send(
                    f"🔔 {mention} the server can be bumped on **{bot['name']}** again! "
                    f"Run `/bump` (pick {bot['name']}) to keep us growing. 🚀",
                    allowed_mentions=discord.AllowedMentions(roles=True, everyone=True))
                self._col().update_one({"_id": doc["_id"]}, {"$set": {"reminded": True}})
            except discord.HTTPException:
                pass


async def setup(client):
    await client.add_cog(BumpReminder(client))
