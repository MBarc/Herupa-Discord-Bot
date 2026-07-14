'''
Purpose: Reward members for welcoming new arrivals.

Discord posts a join system message ("X just joined" with a "Wave to say hi 👋"
prompt) in the system channel. When a member REPLIES to that join message, they
get a bonus dose of XP through the Leveling cog and Herupa waves back with a 👋.

Guardrails so it can't be farmed:
  - Only replies to an actual join system message count.
  - You can't welcome yourself, and welcoming a bot's join earns nothing.
  - The join must be recent (WELCOME_WINDOW) so old joins can't be necro-farmed.
  - Each person is credited once per newcomer (deduped in Mongo).
'''

import os
import random
import sys

import discord
from discord.ext import commands

current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
sys.path.append(parent_dir)

from tools.HerupaMongo import HerupaMongo

WELCOME_XP = (25, 40)                # bonus per welcome (a normal message is 15-25)
WELCOME_WINDOW = 7 * 24 * 60 * 60    # welcomes within a week of the join count (people
                                     # often welcome a newcomer a day+ after they join)
DB, COL = "welcomes", "credited"


class WelcomeReward(commands.Cog):

    def __init__(self, client):
        self.client = client
        self.mongo = HerupaMongo()

    def _col(self):
        return self.mongo.client[DB][COL]

    @commands.Cog.listener()
    async def on_message(self, message):
        if message.guild is None or message.author.bot:
            return
        ref = message.reference
        if ref is None or ref.message_id is None:
            return

        # Resolve the replied-to message (use the cached copy if we have it).
        joinmsg = ref.resolved if isinstance(ref.resolved, discord.Message) else None
        if joinmsg is None:
            try:
                joinmsg = await message.channel.fetch_message(ref.message_id)
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                return
        if joinmsg.type != discord.MessageType.new_member:
            return

        newcomer, welcomer = joinmsg.author, message.author
        if newcomer.bot or welcomer.id == newcomer.id:
            return
        if (message.created_at - joinmsg.created_at).total_seconds() > WELCOME_WINDOW:
            return

        # Credit each welcomer once per newcomer (atomic upsert; no double-dip on
        # multiple replies to the same join message).
        key = f"{joinmsg.id}:{welcomer.id}"
        res = self._col().update_one(
            {"_id": key}, {"$setOnInsert": {"welcomer": welcomer.id}}, upsert=True)
        if res.upserted_id is None:
            return

        leveling = self.client.get_cog("Leveling")
        if leveling is None:
            return
        amount = random.randint(*WELCOME_XP)
        old, new = leveling._add_xp(welcomer.id, amount)
        try:
            await message.add_reaction("👋")
        except discord.HTTPException:
            pass
        if new > old:
            await leveling._announce(message.channel, welcomer, new)


async def setup(client):
    await client.add_cog(WelcomeReward(client))
