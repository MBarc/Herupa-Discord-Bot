'''
Purpose: This file contains the commands a user can use to manage their favorites.
'''
from discord.ext import commands
import discord

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

    @commands.command(name="removeFavorite",
                      description="Removes a favorite member from the author's favorites list",
                      brief="Removes a favorite.",
                      aliases=["rf"])
    async def removefavorite(self, ctx):

        # Getting the author
        authorID = str(ctx.author.id)

        # If the author doesn't have a collection, create it
        if not self.mongo_instance.doesCollectionExist(database_name=self.dbName, collection_name=authorID):
            self.mongo_instance.createCollection(database_name=self.dbName, collection_name=authorID)

        # If there isn't any or too many mentions
        if len(ctx.message.mentions) != 1:
            raise Exception("You have to specify 1 person at a time.")

        # Grabbing the member that we're removing as a favorite
        mention = str(ctx.message.mentions[0].id)

        # Removing the member as a favorite for the author
        self.mongo_instance.removeCollectionEntry(database_name=self.dbName, collection_name=authorID, payload={"id": mention})

        # Sending feedback to the user
        await ctx.channel.send(f"You have successfully removed {ctx.message.mentions[0].name} as a favorite.")

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

        # Retrieve documents from the MongoDB collection
        documents = self.mongo_instance.returnCollectionEntries(database_name=self.dbName, collection_name=authorID)

        # If there are documents in the collection; if the user has favorites specified
        if len(documents) != 0:

            # Initialize the message
            message = "Here are your favorites:\n"

            # Iterate through the documents and retrieve user names
            for document in documents:

                # Retrieve user information using user ID
                user = await self.client.fetch_user(document['id'])

                # Append user name to the message
                message += f"- {user.name}\n"

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