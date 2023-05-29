# Importing custom config file and default libraries
import sys
import os
from pathlib import Path
configPath = Path(os.path.abspath(os.path.dirname(__file__))).parent.absolute()
sys.path.insert(0, configPath)
from config import configFile
from discord.ext import commands

# Importing libraries specifically used for this command
import discord

class Migrate(commands.Cog):

    def __init__(self, client):
        self.client = client

    @commands.command(name = 'migrate',
                    description = 'Mass migrate people to another voice channel.',
                    brief = 'Move all members of your voice channel to another channel.')
    async def migrate(self, ctx, *args):
        user_input = list(args)

        tracker = None # placeholder variable
        for word in user_input:

            if word == user_input[len(user_input) - 1]:  # if equal to the last word
                True  # do nothing
            else:
                word = word + " " #include a space afterwards since it's not the last word in the list

            if tracker == None:
                tracker = word
            else:
                tracker += word


        user_input = tracker
        for guild in self.client.guilds:
            for channel in guild.channels:

                if (channel.name == user_input) and (channel.type == discord.ChannelType.voice):

                    currentChannel = ctx.message.author.voice.channel.members

                    for member in currentChannel:
                        await member.move_to(channel)

    @migrate.error
    async def migrate_error(self, ctx, error):

        commandName = ctx.invoked_with
        error = str(error)

        herupaErrorLogChannel = self.client.get_channel(configFile()["herupaErrorLogChannel"])
        await herupaErrorLogChannel.send(f"{commandName.upper()} error: {error}")

async def setup(client):
    await client.add_cog(Migrate(client))
