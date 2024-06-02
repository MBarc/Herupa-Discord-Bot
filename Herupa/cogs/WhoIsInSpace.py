# Importing libraries specifically used for this command
import requests
import json
from discord.ext import commands

class WhoIsInSpace(commands.Cog):

    def __init__(self, client):
        self.client = client

    @commands.command(name="whoisinspace",
                      aliases=["wiis"])
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

async def setup(client):
    await client.add_cog(WhoIsInSpace(client))