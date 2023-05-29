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
import json

class WhoIsInSpace(commands.Cog):

    def __init__(self, client):
        self.client = client

    @commands.command()
    async def whoisinspace(self, ctx):
        issURL = 'http://api.open-notify.org/astros.json'
        issAPI = requests.get(issURL)
        jsonData = json.loads(issAPI.text)

        amount = jsonData['number']
        people = [person['name'] for person in jsonData['people']]

        wikiURL = 'https://en.wikipedia.org/wiki/%s'

        message = f'There are **{amount}** people onboard the I.S.S. right now. Here is their info:\n'

        for person in people: # Dynamically adding content to the message.
            message += f"**{person}**: <{wikiURL % person.replace(' ', '_')}>\n"

        await ctx.channel.send(message)

    @whoisinspace.error
    async def whoisinspace_error(self, ctx, error):

        commandName = ctx.invoked_with
        error = str(error)

        herupaErrorLogChannel = self.client.get_channel(configFile()["herupaErrorLogChannel"])
        await herupaErrorLogChannel.send(f"{commandName.upper()} error: {error}")

async def setup(client):
    await client.add_cog(WhoIsInSpace(client))
