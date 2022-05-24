'''
This command ties in with the add2room and destroyroom command.
'''
# Importing custom config file and default libraries
import sys
import os
from pathlib import Path
configPath = Path(os.path.abspath(os.path.dirname(__file__))).parent.absolute()
sys.path.insert(0, configPath)
from config import configFile
from discord.ext import commands

# Importing libraries specifically used for this command
import asyncio
import discord

from discord.ext import commands

class CreateRoom(commands.Cog):

    def __init__(self, client):
        self.client = client

    @commands.command()
    async def createroom(self, ctx):

        # Declaring variables
        author = ctx.message.author
        mentions = ctx.message.mentions
        guild = ctx.guild

        #Adding author by default
        mentions.append(author)
        print('worked as expected')
        # Category where the room will be placed under
        category = discord.utils.get(ctx.guild.categories, id=configFile()["all-categories"]["rooms"])

        # Name of the channel being created
        voiceChannel = await ctx.guild.create_voice_channel(f"{author.name}'s Room", category=category)

        textChannel = await ctx.guild.create_text_channel(f"{author.name} TC", category=category)

        # No one else can see this channel, this will avoid the channels list from looking cluttered
        await voiceChannel.set_permissions(discord.utils.get(guild.roles, name="@everyone"), view_channel=False)

        await textChannel.set_permissions(discord.utils.get(guild.roles, name="@everyone"), view_channel=False)

        # Assigning appropriate permissions for the people mentioned
        for member in mentions:

            # Only the members who were specified to join

            # Setting permissions for the voice channel
            await voiceChannel.set_permissions(member,
                                          view_channel=True,
                                          connect=True,
                                          speak=True,
                                          )

            # Setting permissions for the text channel
            await textChannel.set_permissions(member,
                                               view_channel=True,
                                               read_messages=True,
                                               send_messages=True,
                                               )

        # Converting each object to a string so we can @ mention members in the message
        mentions =[f'<@{mention.id}>' for mention in mentions if isinstance(mention, discord.member.Member)]

        # Grammar handling
        if len(mentions) > 1:
            mentions.insert(-1, "and") #adding this for the response
            grammerWord = "have"
        else:
            grammerWord = "has"

        # Converting mentions to a string and removing the list artifacts
        mentions = str(mentions).replace("[", "").replace("]", "").replace("'", "").replace(',', '')
        mentions = mentions.replace(' ', ',', mentions.count(' ') - 1).replace(',', ', ', -1)

        # Sending out the message with the appropriate grammar
        response = await ctx.message.channel.send(f"{author.name}'s Room created! Look under the Rooms category to find it. {mentions} {grammerWord} been given access to the room. This message will self-destruct in 20 seconds.")

        # Cleaning up the channel
        await ctx.message.delete()
        await asyncio.sleep(20)
        await response.delete()

    @createroom.error
    async def createroom_error(self, ctx, error):

        commandName = ctx.invoked_with
        error = str(error)

        if 'CREATEROOM Command Error' in error:
            await ctx.channel.send(f"ERROR")

        herupaErrorLogChannel = self.client.get_channel(configFile()["herupaErrorLogChannel"])
        await herupaErrorLogChannel.send(f"{commandName.upper()} error: {error}")

def setup(client):
    client.add_cog(CreateRoom(client))
