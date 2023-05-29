'''
This is a redundant code that will delete any empty private voice channels at 6:30am EST.
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
import discord
import datetime
from discord.ext import tasks

class DestroyRoomBackground(commands.Cog):

    def __init__(self, client):
        self.client = client
        self.destroyroombackground.start()

    @tasks.loop(seconds=60.0)
    async def destroyroombackground(self):

        currentTime = datetime.datetime.now()

        #If it's 6:30am
        if currentTime.hour == 6 and currentTime.minute == 30:
            category = discord.utils.get(self.client.guilds[0].categories, id=configFile()["all-categories"]["rooms"]).id

            #Iterate through all voice channels in the server
            for voice_channel in self.client.guilds[0].voice_channels:

                #if the voice channel is in the default category and it's empty
                if voice_channel.category_id == category and len(voice_channel.members) == 0:
                    await voice_channel.delete(reason='Deleted by Destroy Room Background task.')

    @destroyroombackground.before_loop
    async def destroyroombackground_before(self):
        await self.client.wait_until_ready()

    @destroyroombackground.error
    async def destroyroombackground_error(self, ctx, error):

        commandName = ctx.invoked_with
        error = str(error)

        herupaErrorLogChannel = self.client.get_channel(configFile()["herupaErrorLogChannel"])
        await herupaErrorLogChannel.send(f"{commandName.upper()} error: {error}")


async def setup(client):
    await client.add_cog(DestroyRoomBackground(client))
