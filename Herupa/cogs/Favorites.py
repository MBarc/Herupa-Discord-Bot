'''
Purpose: This file contains the commands a user can use to manage their favorites.
'''
from discord.ext import commands

import sys
import os

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

    @commands.command(name="addFavorite",
                      description="Adds a favorite member from the author's favorites list",
                      brief="Adds a favorite.")
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

        # Adding the member as a favorite for the author
        self.mongo_instance.addCollectionEntry(database_name=self.dbName, collection_name=authorID, payload={"id": mention})

        # Sending feedback to the user
        await ctx.channel.send(f"You have successfully added {ctx.message.mentions[0].name} as a favorite!")

    @commands.command(name="removeFavorite",
                      description="Removes a favorite member from the author's favorites list",
                      brief="Removes a favorite.")
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

    @commands.command(name='displayFavorites',
                      description='Returns the full list of favorites for the user who issued the command.',
                      brief='Displays the users favorites.')
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
            message = "Here are your favorites: \n"

            # Iterate through the documents and retrieve user names
            for document in documents:

                # Retrieve user information using user ID
                user = await self.client.fetch_user(document['id'])

                # Append user name to the message
                message += f"- {user.name}\n"

        else: # If the user doesn't have any favorites specified

            message = "You don't have have favorites! Use **$addfavorite @mention** to add a favorite!"

        # Sending feedback
        await ctx.channel.send(message)

async def setup(client):
    await client.add_cog(Favorites(client))