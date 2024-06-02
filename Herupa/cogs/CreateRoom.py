'''
Purpose: An automatic task to create a room, with a specific configuration, when a member joins the create room VC.
'''
import discord
from discord.ext import commands

# Add the parent directory to the Python path so we can import our custom library
# Get the parent directory of the current script
import sys
import os
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)

# Add the parent directory to the Python path so we can import our custom library
sys.path.append(parent_dir)
from tools.HerupaMongo import HerupaMongo

class CreateRoom(commands.Cog):

    def __init__(self, client):
        self.client = client
        self.createRoomName = "🔧create room🔧"
        self.dbName = "createroom"
        self.mongo_instance = HerupaMongo()


    @commands.command(name='crpm',
                    description='Switches the privacy mode for the create room feature for the user',
                    brief='Switches the privacy mode for the create room feature.')
    async def crpm(self, ctx):

        # Getting the user who issued the command
        authorID = str(ctx.author.id)

        privacyModeDocument = self.mongo_instance.findSpecificDocumentsByKey(database_name=self.dbName, collection_name=authorID, key="privacy_mode")

        privacyMode = privacyModeDocument[0]["privacy_mode"]

        if privacyMode == "public":

            self.mongo_instance.updateDocumentsByKey(database_name=self.dbName, collection_name=authorID, IDkey="_id", IDvalue=privacyModeDocument[0]["_id"], key="privacy_mode", value="private")
            await ctx.channel.send("Your privacy mode has been switched to PRIVATE.")

        if privacyMode == "private":

            print(privacyMode)
            self.mongo_instance.updateDocumentsByKey(database_name=self.dbName, collection_name=authorID, IDkey="_id", IDvalue=privacyModeDocument[0]["_id"], key="privacy_mode", value="public")
            await ctx.channel.send("Your privacy mode has been switched to PUBLIC.")


    @commands.Cog.listener()
    async def on_voice_state_update(self, member, before, after):

        # If the member joins the create room channel
        if after.channel and after.channel.name == self.createRoomName:

            # Get the category of the create room channel
            category = after.channel.category

            # Creating the voice channel and saving it to a variable
            memberChannel = await category.create_voice_channel(member.name)

            # Making sure the newbie role can't view the newly created channel
            role = discord.utils.get(memberChannel.guild.roles, name="newbie")
            await memberChannel.set_permissions(role, overwrite=discord.PermissionOverwrite(view_channel=False))

            # Getting the ID of our member so we can query the database
            memberID = str(member.id)

            # If the member doesn't have a collection, create it
            if not self.mongo_instance.doesCollectionExist(database_name=self.dbName, collection_name=memberID):
                
                # Creating the member's collection so we have a place to put data into
                self.mongo_instance.createCollection(database_name=self.dbName, collection_name=memberID)

                # Creating the default document that makes the privacy mode of the member's channel public
                self.mongo_instance.addCollectionEntry(database_name=self.dbName, collection_name=memberID, payload={"privacy_mode": "public"})

            privacyMode = self.mongo_instance.findSpecificDocumentsByKey(database_name=self.dbName, collection_name=memberID, key="privacy_mode")[0]["privacy_mode"]
            
            # Define the permissions you want to grant or deny for everyone in the voice channel
            permissions = discord.PermissionOverwrite(
                connect=True,  # Allow everyone to connect to the channel
                speak=True,    # Allow everyone to speak in the channel
                read_messages=True,
                send_messages=True,
                view_channel=True,
                use_voice_activation=True
            )

            guild = memberChannel.guild

            if privacyMode == "public":

                await memberChannel.set_permissions(guild.default_role, overwrite=permissions)

            if privacyMode == "private":

                documents = self.mongo_instance.returnCollectionEntries(database_name="favorites", collection_name=memberID)

                if len(documents) > 0:

                    for favorite in documents:

                        targetFavoite = guild.get_member(int(favorite["id"]))

                        await memberChannel.set_permissions(targetFavoite, overwrite=permissions)

            # Moving the member to the newly created voice channel
            await member.move_to(memberChannel)

        # Getting the category for create rooms
        channel = discord.utils.get(member.guild.channels, name=self.createRoomName)

        # If the member was in a channel before, and that channel now has 0 members in it, and the channel was in the same
        # channel as our create room channel
        if before.channel and len(before.channel.members) == 0 and before.channel.category == channel.category and before.channel.name != self.createRoomName:

            # Deleting the voice channel
            await before.channel.delete()

async def setup(client):
    await client.add_cog(CreateRoom(client))