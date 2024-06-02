# Importing custom config file and default libraries
from discord.ext import commands


class ISSLive(commands.Cog):

    def __init__(self, client):
        self.client = client

    @commands.command()
    async def isslive(self, ctx):
        issLivestreamURL = 'https://www.youtube.com/watch?v=P9C25Un7xaM'
        await ctx.message.channel.send(f"Here's the link to watch the I.S.S. live: <{issLivestreamURL}>")

async def setup(client):
    await client.add_cog(ISSLive(client))