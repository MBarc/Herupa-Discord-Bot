from discord.ext import commands

class Lenny(commands.Cog):

    def __init__(self, client):
        self.client = client

    @commands.command(name="lenny",
                      aliases=["l"])
    async def lenny(self, ctx):
        await ctx.message.channel.send('( ͡° ͜ʖ ͡°)!!!!!!')

async def setup(client):
    await client.add_cog(Lenny(client))
