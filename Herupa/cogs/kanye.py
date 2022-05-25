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
import random

class Kanye(commands.Cog):

    def __init__(self, client):
        self.client = client

    @commands.command()
    async def kanye(self, ctx):

        # Getting the quote
        url = "https://api.kanye.rest/"
        request = requests.get(url)
        quote = request.json()["quote"]

        signatures = ["Kanye West",
                      "Yeezy",
                      "Yeezus",
                      "Konman",
                      "The Louis Vuitton Don",
                      "Ye"]

        await ctx.message.channel.send(f'"{quote}" - {random.choice(signatures)}')

    @kanye.error
    async def kanye_error(self, ctx, error):

        commandName = ctx.invoked_with
        error = str(error)

        herupaErrorLogChannel = self.client.get_channel(configFile()["herupaErrorLogChannel"])
        await herupaErrorLogChannel.send(f"{commandName.upper()} error: {error}")

def setup(client):
    client.add_cog(Kanye(client))
