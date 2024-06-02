# Importing libraries specifically used for this command
import discord
from discord.ext import commands

class AvatarPic(commands.Cog):

    def __init__(self, client):
        self.client = client

    @commands.command(name='avatarpic',
                      aliases=['ap'])
    async def avatarpic(self, ctx, avamember : discord.Member=None):
        userAvatarUrl = avamember.display_avatar
        await ctx.send(userAvatarUrl)

async def setup(client):
    await client.add_cog(AvatarPic(client))