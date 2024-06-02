'''
Purpose: To test is Herupa is up and running. Herupa will respond with "pong!"
'''

from discord.ext import commands

class Ping(commands.Cog):

    def __init__(self, client):
        self.client = client

    @commands.command(name="ping",
                      aliases=["p"])
    async def ping(self, ctx):

        await ctx.channel.send("pong!")

async def setup(client):
    await client.add_cog(Ping(client))