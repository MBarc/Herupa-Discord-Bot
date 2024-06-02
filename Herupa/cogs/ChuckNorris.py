'''
Purpose: This command returns a chucknorris joke from
'''

# Importing libraries specifically used for this command
import requests
from discord.ext import commands

class ChuckNorris(commands.Cog):

    def __init__(self, client):
        self.client = client

    @commands.command(name='chucknorris',
                      aliases=['cn'])
    async def chucknorris(self, ctx, *args):

        r = requests.get("https://api.chucknorris.io/jokes/random")

        await ctx.channel.send(r.json()['value'])

async def setup(client):
    await client.add_cog(ChuckNorris(client))