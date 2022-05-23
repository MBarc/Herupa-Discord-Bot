'''
This command ties in with the createroom and destroyroom command.
'''
# Importing custom config file and default libraries
import sys
import os
from pathlib import Path
configPath = Path(os.path.abspath(os.path.dirname(__file__))).parent.absolute()
sys.path.insert(0, configPath)
from config import configFile
from discord.ext import commands

import asyncio
import discord

class Add2Room(commands.Cog):

    def __init__(self, client):
        self.client = client

    @commands.command()
    async def add2room(self, ctx):

        #Grabbing members that need to be added to the voice channel
        mentions = ctx.message.mentions

        if mentions is None:
            raise Exception('ADD2ROOM Command Error: User did not mention any users.')

        #Grabbing the default category where all rooms are located/created
        category = discord.utils.get(ctx.guild.categories, id=configFile()["all-categories"]["rooms"]).id

        voice_connection = lambda x: False if x is None else True

        if voice_connection(ctx.message.author.voice) is False:
            raise Exception('ADD2ROOM Command Error: User is not connected to a voice channel at all.')

        #if author is connected to a voice channel, continue. . .
        if voice_connection(ctx.message.author.voice) is True:

            connected_category = ctx.message.author.voice.channel.category_id

            #if their connected voice channel is within the default category
            if connected_category == category:

                channel = ctx.message.author.voice.channel

                for member in mentions:
                    await channel.set_permissions(member,
                                                  view_channel=True,
                                                  connect=True,
                                                  speak=True)
            else:

                raise Exception('ADD2ROOM Command Error: User is not connected to a voice channel within the Rooms category.')

        await ctx.message.delete()

        if len(mentions) > 1:
            mentions.insert(-1, "and") #adding this for the response
            grammerWord = "have"
        else:
            grammerWord = "has"

        response = await ctx.message.channel.send(f'Success! {" ".join(str(member) for member in mentions)} {grammerWord} been given access to the room. This message will self-destruct in 10 seconds.')
        await asyncio.sleep(10)
        await response.delete()


    @add2room.error
    async def add2room_error(self, ctx, error):

        commandName = ctx.invoked_with
        error = str(error)

        if 'ADD2ROOM Command Error: User did not mention any users.' in error:
            await ctx.channel.send(f"You need to mention another member in order to use this command.")

        if 'ADD2ROOM Command Error: User is not connected to a voice channel at all.' in error:
            await ctx.channel.send(f"You need to be in the voice chat in order to add someone to it.")

        if 'ADD2ROOM Command Error: User is not connected to a voice channel within the Rooms category.' in error:
            await ctx.channel.send(f"You need to be in a voice channel that's within the Rooms category in order to use this command.")

        herupaErrorLogChannel = self.client.get_channel(configFile()["herupaErrorLogChannel"])
        await herupaErrorLogChannel.send(f"{commandName.upper()} error: {error}")

def setup(client):
    client.add_cog(Add2Room(client))