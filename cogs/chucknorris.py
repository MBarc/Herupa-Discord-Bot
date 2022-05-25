'''
Purpose: This command returns a chucknorris joke from
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
import requests

class ChuckNorris(commands.Cog):

    def __init__(self, client):
        self.client = client

    @commands.command()
    async def chucknorris(self, ctx, *args):

        r = requests.get("https://api.chucknorris.io/jokes/random")

        await ctx.channel.send(r.json()['value'])


    @chucknorris.error
    async def chucknorris_error(self, ctx, error):
        commandName = ctx.invoked_with
        error = str(error)

        herupaErrorLogChannel = self.client.get_channel(configFile()["herupaErrorLogChannel"])
        await herupaErrorLogChannel.send(f"{commandName.upper()} error: {error}")

def setup(client):
    client.add_cog(ChuckNorris(client))