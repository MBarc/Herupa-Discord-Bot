'''
Purpose: This file contains the commands a user can use to manage their favorites.
'''
from discord.ext import commands
import discord

import re
import sys
import os
import time

from discord.utils import get

# Get the parent directory of the current script
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)

# Add the parent directory to the Python path so we can import our custom library
sys.path.append(parent_dir)

from tools.HerupaMongo import HerupaMongo

class Favorites(commands.Cog):

    def __init__(self, client):
        self.client = client
        self.dbName = "favorites"
        self.mongo_instance = HerupaMongo()

        # Anti-spam: don't re-notify about the same joiner within this window.
        self.notify_cooldown_seconds = 300  # 5 minutes
        self._last_notified = {}  # joiner_id -> unix timestamp of last DM sent

    @commands.command(name="addFavorite",
                      description="Adds a favorite member from the author's favorites list",
                      brief="Adds a favorite.",
                      aliases=["af"])
    async def addfavorite(self, ctx):

        # Getting the author
        authorID = str(ctx.author.id)

        # If the author doesn't have a collection, create it
        if not self.mongo_instance.doesCollectionExist(database_name=self.dbName, collection_name=authorID):
            self.mongo_instance.createCollection(database_name=self.dbName, collection_name=authorID)

        # If there isn't any or too many mentions
        if len(ctx.message.mentions) != 1:
            raise Exception("You have to specify 1 person at a time.")

        # Grabbing the member that we're adding as a favorite
        mention = str(ctx.message.mentions[0].id)

        # You can't favorite yourself (it would just DM you about your own joins).
        if mention == authorID:
            await ctx.channel.send("You can't favorite yourself!")
            return

        # Adding the member as a favorite for the author
        self.mongo_instance.addCollectionEntry(database_name=self.dbName, collection_name=authorID, payload={"id": mention})

        # Sending feedback to the user
        await ctx.channel.send(f"You have successfully added {ctx.message.mentions[0].name} as a favorite!")

    async def _favorite_users(self, authorID):
        """Ordered (user_id, user_or_None) pairs for authorID's favorites, in
        the same order displayfavorites lists them (so list numbers line up)."""
        pairs = []
        for document in self.mongo_instance.returnCollectionEntries(database_name=self.dbName, collection_name=authorID):
            uid = str(document["id"])
            user = self.client.get_user(int(uid))
            if user is None:
                try:
                    user = await self.client.fetch_user(int(uid))
                except discord.HTTPException:
                    user = None  # deleted account etc.; still removable by ID/number
            pairs.append((uid, user))
        return pairs

    def _match_favorite(self, query, favorites):
        """Resolve query (a name, raw user ID, <@id> text, or 1-based list
        number) against the ordered favorites. Returns (user_id, error)."""
        query = query.strip().lstrip("@")

        mention_match = re.fullmatch(r"<@!?(\d+)>", query)
        if mention_match:
            query = mention_match.group(1)

        if query.isdigit():
            # Real Discord IDs are 17+ digit snowflakes; anything short is a
            # position on the $displayfavorites list.
            if len(query) >= 15:
                if any(uid == query for uid, _ in favorites):
                    return query, None
                return None, "That ID isn't in your favorites."
            index = int(query)
            if 1 <= index <= len(favorites):
                return favorites[index - 1][0], None
            return None, (f"That number isn't on your list. You have "
                          f"{len(favorites)} favorite(s), see **$displayfavorites**.")

        wanted = query.casefold()
        exact, partial = [], []
        for uid, user in favorites:
            if user is None:
                continue
            names = {n.casefold() for n in
                     (user.name, user.display_name, getattr(user, "global_name", None))
                     if n}
            if wanted in names:
                exact.append((uid, user))
            elif any(wanted in n for n in names):
                partial.append((uid, user))
        matches = exact or partial
        if not matches:
            return None, (f"I couldn't find **{query}** in your favorites. "
                          f"Check **$displayfavorites**.")
        if len(matches) > 1:
            names = ", ".join(user.name for _, user in matches)
            return None, (f"That matches more than one favorite ({names}). "
                          f"Use their number from **$displayfavorites**.")
        return matches[0][0], None

    @commands.command(name="removeFavorite",
                      description="Removes a favorite by name, user ID, or list number (no @-ping needed; a mention still works too)",
                      brief="Removes a favorite.",
                      aliases=["rf"])
    async def removefavorite(self, ctx, *, who: str = None):

        # Getting the author
        authorID = str(ctx.author.id)

        # If the author doesn't have a collection, create it
        if not self.mongo_instance.doesCollectionExist(database_name=self.dbName, collection_name=authorID):
            self.mongo_instance.createCollection(database_name=self.dbName, collection_name=authorID)

        favorites = await self._favorite_users(authorID)
        if not favorites:
            await ctx.channel.send("You don't have any favorites to remove!")
            return

        # Mentions still work for anyone who doesn't mind the ping, but the
        # whole point of the other forms is removing someone quietly.
        if ctx.message.mentions:
            if len(ctx.message.mentions) != 1:
                raise Exception("You have to specify 1 person at a time.")
            target_id = str(ctx.message.mentions[0].id)
            if not any(uid == target_id for uid, _ in favorites):
                await ctx.channel.send(f"{ctx.message.mentions[0].name} isn't in your favorites.")
                return
        elif who:
            target_id, error = self._match_favorite(who, favorites)
            if error:
                await ctx.channel.send(error)
                return
        else:
            await ctx.channel.send(
                "Tell me who to remove: **$removefavorite <name, user ID, or list number>** "
                "(numbers are in **$displayfavorites**). No need to @-ping them.")
            return

        # Removing the member as a favorite for the author
        self.mongo_instance.removeCollectionEntry(database_name=self.dbName, collection_name=authorID, payload={"id": target_id})

        # Leave no trace in the channel: the invoking command names who got
        # removed, so it goes too (not possible in DMs, hence the guard).
        try:
            await ctx.message.delete()
        except (discord.Forbidden, discord.HTTPException):
            pass

        # Sending feedback to the user (plain name, never a pinging mention);
        # the confirmation cleans itself up as well
        name = next((user.name for uid, user in favorites if uid == target_id and user), target_id)
        await ctx.channel.send(f"You have successfully removed {name} as a favorite.",
                               delete_after=10)

    @commands.command(name='displayfavorites',
                      description='Returns the full list of favorites for the user who issued the command.',
                      brief='Displays your favorites.',
                      aliases=["df"])
    async def displayfavorites(self, ctx):
        """
        Displays the favorites of the user who issued the command.
        """

        # Getting the author
        authorID = str(ctx.author.id)

        favorites = await self._favorite_users(authorID)

        # If there are documents in the collection; if the user has favorites specified
        if favorites:

            # Numbered so entries can be removed by position, without a ping
            message = "Here are your favorites:\n"
            for position, (uid, user) in enumerate(favorites, start=1):
                name = user.name if user else f"unknown user ({uid})"
                message += f"{position}. {name}\n"
            message += "\nRemove one anytime with **$removefavorite <name or number>** (no @-ping needed)."

        else: # If the user doesn't have any favorites specified

            message = "You don't have any favorites! Use **$addfavorite @mention** to add a favorite!"

        # Sending the list to the channel.
        await ctx.channel.send(message)

    def _favorite_ids(self, memberID):
        """The set of user IDs (as strings) that memberID has favorited."""
        return {str(d["id"]) for d in self.mongo_instance.returnCollectionEntries(
            database_name=self.dbName, collection_name=memberID)}

    @commands.Cog.listener()
    async def on_voice_state_update(self, member, before, after):
        """DM a member's mutual favorites when they CONNECT to a voice channel —
        but only those who can actually see that channel (so private rooms never
        ping, or reveal themselves to, someone who can't join)."""

        # Only fire on a fresh connect (ignore mutes, moves, and disconnects).
        if member.bot or before.channel is not None or after.channel is None:
            return

        joiner_id = str(member.id)

        # Rate limit: if we already notified about this person recently, skip —
        # otherwise a rapid leave/rejoin would spam their favorites.
        now = time.time()
        if now - self._last_notified.get(joiner_id, 0) < self.notify_cooldown_seconds:
            return

        channel = after.channel
        guild = member.guild
        sent = 0

        for recipient_id in self._favorite_ids(joiner_id):
            # Never notify yourself about your own join (e.g. a stale self-favorite).
            if recipient_id == joiner_id:
                continue
            recipient = guild.get_member(int(recipient_id))
            if recipient is None or recipient.bot:
                continue

            # Already in the channel the joiner joined? They'd see it, no DM needed.
            if recipient.voice and recipient.voice.channel and recipient.voice.channel.id == channel.id:
                continue

            # (1) Mutual: the recipient must also have the joiner favorited.
            if joiner_id not in self._favorite_ids(recipient_id):
                continue

            # (2) The recipient must be able to see the channel the joiner joined.
            if not channel.permissions_for(recipient).view_channel:
                continue

            try:
                await recipient.send(
                    f"🔔 **{member.display_name}** just joined **{channel.name}**! Come hang out!")
                sent += 1
            except discord.HTTPException:
                pass  # recipient has DMs closed, etc.

        # Only start the cooldown once a DM actually went out, so joining a room
        # nobody could see doesn't suppress a real ping moments later.
        if sent:
            self._last_notified[joiner_id] = now


async def setup(client):
    await client.add_cog(Favorites(client))