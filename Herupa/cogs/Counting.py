'''
Purpose: A counting game for the counting channel, replacing the third-party
counting bot. Members post consecutive numbers starting from 1. Herupa reacts
✅ to each correct number and tracks the all-time high score. If someone posts
the wrong number or counts twice in a row, the count resets to 0 and everyone
starts over from 1.

Single-server build for Chill Club: the counting channel is matched by name.
Non-number messages (chatter, other bots) are ignored so they never break the
count. State (current count, last counter, high score) is stored in Mongo.
'''

import os
import sys

import discord
from discord.ext import commands

current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
sys.path.append(parent_dir)

from tools.HerupaMongo import HerupaMongo

# The channel the game runs in (matched by name).
COUNTING_CHANNEL = "🔟chill-counting🔟"
# Whether the same member may count twice in a row.
ALLOW_DOUBLE_COUNT = False
DB_NAME = "counting"


def evaluate_count(number, author_id, count, last_user_id, allow_double=False):
    """Pure decision for a single count attempt (no I/O, so it's unit-testable).
    Returns one of:
      ("correct", new_count)
      ("wrong_number", expected)
      ("double",)
    """
    expected = count + 1
    if number != expected:
        return ("wrong_number", expected)
    if not allow_double and last_user_id is not None and author_id == last_user_id:
        return ("double",)
    return ("correct", expected)


class Counting(commands.Cog):

    def __init__(self, client):
        self.client = client
        self.mongo = HerupaMongo()

    # --------------------------- persistence ---------------------------

    def _col(self, guild_id):
        return self.mongo.client[DB_NAME][str(guild_id)]

    def _state(self, guild_id):
        doc = self._col(guild_id).find_one({"_id": "state"})
        if doc is None:
            doc = {"_id": "state", "count": 0, "last_user_id": None, "high_score": 0}
            self._col(guild_id).insert_one(doc)
        return doc

    def _save(self, guild_id, count, last_user_id, high_score):
        self._col(guild_id).update_one(
            {"_id": "state"},
            {"$set": {"count": count, "last_user_id": last_user_id, "high_score": high_score}},
            upsert=True)

    @staticmethod
    def _parse_number(content):
        text = content.strip()
        # Only a message that is EXACTLY a non-negative integer counts as an
        # attempt; anything else is ignored so chatter never breaks the count.
        return int(text) if text.isdigit() else None

    # ---------------------------- listener -----------------------------

    @commands.Cog.listener()
    async def on_message(self, message):
        if message.author.bot or message.guild is None:
            return
        if getattr(message.channel, "name", None) != COUNTING_CHANNEL:
            return
        number = self._parse_number(message.content)
        if number is None:
            return

        state = self._state(message.guild.id)
        result = evaluate_count(number, message.author.id, state["count"],
                                state["last_user_id"], ALLOW_DOUBLE_COUNT)

        if result[0] == "correct":
            new_count = result[1]
            high_score = max(state["high_score"], new_count)
            self._save(message.guild.id, new_count, message.author.id, high_score)
            await self._react(message, "✅")
            if new_count % 100 == 0:
                await self._react(message, "💯")
            return

        if result[0] == "wrong_number":
            await self._break(message, state,
                              f"**{number}** wasn't the next number. It was **{result[1]}**.")
        elif result[0] == "double":
            await self._break(message, state, "you can't count twice in a row!")

    async def _break(self, message, state, reason):
        reached = state["count"]
        high_score = state["high_score"]
        record_note = ""
        if reached > high_score:
            high_score = reached
            record_note = f"\n🏆 That's a new high score of **{reached}**!"
        self._save(message.guild.id, 0, None, high_score)
        await self._react(message, "❌")
        await message.channel.send(
            f"💥 {message.author.mention} broke the count at **{reached}**, {reason} "
            f"The next number is **1**.{record_note}")

    @staticmethod
    async def _react(message, emoji):
        try:
            await message.add_reaction(emoji)
        except discord.HTTPException:
            pass


async def setup(client):
    await client.add_cog(Counting(client))
