# Importing custom config file and default libraries
import sys
import os
from pathlib import Path
configPath = Path(os.path.abspath(os.path.dirname(__file__))).parent.absolute()
sys.path.insert(0, configPath)
from config import configFile
from discord.ext import commands

class Lenny(commands.Cog):

    def __init__(self, client):
        self.client = client

    @commands.command()
    async def lenny(self, ctx):
        await ctx.message.channel.send('( ͡° ͜ʖ ͡°)')

    @lenny.error
    async def lenny_error(self, ctx, error):

        commandName = ctx.invoked_with
        error = str(error)

        herupaErrorLogChannel = self.client.get_channel(configFile()["herupaErrorLogChannel"])
        await herupaErrorLogChannel.send(f"{commandName.upper()} error: {error}")

async def setup(client):
    await client.add_cog(Lenny(client))
