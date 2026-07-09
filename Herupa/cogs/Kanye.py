# Importing custom config file and default libraries
from discord.ext import commands

# Importing libraries specifically used for this command
import aiohttp
import random

class Kanye(commands.Cog):

    def __init__(self, client):
        self.client = client

    @commands.command(name="kanye",
                      aliases=["k"])
    async def kanye(self, ctx):

        # Getting the quote
        url = "https://api.kanye.rest/"
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as request:
                quote = (await request.json())["quote"]

        signatures = ["Kanye West",
                      "Yeezy",
                      "Yeezus",
                      "Konman",
                      "The Louis Vuitton Don",
                      "Ye"]

        await ctx.message.channel.send(f'"{quote}" - {random.choice(signatures)}')

async def setup(client):
    await client.add_cog(Kanye(client))
