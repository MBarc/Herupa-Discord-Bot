'''
Purpose: This command returns a chucknorris joke from
'''

# Importing libraries specifically used for this command
import aiohttp
from discord.ext import commands

class ChuckNorris(commands.Cog):

    def __init__(self, client):
        self.client = client

    @commands.command(name='chucknorris',
                      aliases=['cn'])
    async def chucknorris(self, ctx, *args):

        async with aiohttp.ClientSession() as session:
            async with session.get("https://api.chucknorris.io/jokes/random") as r:
                data = await r.json()

        await ctx.channel.send(data['value'])

async def setup(client):
    await client.add_cog(ChuckNorris(client))
