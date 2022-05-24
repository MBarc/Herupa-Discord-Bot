# Importing custom config file and default libraries
import sys
import os
from pathlib import Path
configPath = Path(os.path.abspath(os.path.dirname(__file__))).parent.absolute()
sys.path.insert(0, configPath)
from config import configFile
from discord.ext import commands

# Importing libraries specifically used for this command
import datetime
import asyncio
from discord.ext import tasks


class ClearChannel(commands.Cog):

    def __init__(self, client):
        self.client = client
        self.clearchannel.start()

    @tasks.loop(seconds=60.0)
    async def clearchannel(self):

        currentHour = datetime.datetime.now().hour
        currentMinute = datetime.datetime.now().minute

        channelsToBeCleared = configFile()["clear-channel"]

        if currentHour == 6 and currentMinute == 30:
            for channel in channelsToBeCleared:

                channel = self.client.get_channel(configFile()["clear-channel"][channel])

                # Keep deleting as many messages as possible for the next 30 loops
                try:
                    for loop in range(0, 30):
                        await channel.purge(limit=None)
                        await asyncio.sleep(30)
                except:

                    # Error if there are no messages to delete
                    pass

    @clearchannel.before_loop
    async def clearchannel_before(self):
        await self.client.wait_until_ready()

    @clearchannel.error
    async def clearchannel_error(self, ctx, error):

        commandName = ctx.invoked_with
        error = str(error)

        herupaErrorLogChannel = self.client.get_channel(configFile()["herupaErrorLogChannel"])
        await herupaErrorLogChannel.send(f"{commandName.upper()} error: {error}")

def setup(client):
    client.add_cog(ClearChannel(client))
