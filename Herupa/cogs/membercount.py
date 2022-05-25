'''
Purpose: To test is Herupa is up and running. Herupa will respond with "pong!"
'''
# Importing custom config file and default libraries
import sys
import os
from pathlib import Path
configPath = Path(os.path.abspath(os.path.dirname(__file__))).parent.absolute()
sys.path.insert(0, configPath)
from config import configFile
from discord.ext import commands

class MemberCount(commands.Cog):

    def __init__(self, client):
        self.client = client

    @commands.command()
    async def membercount(self, ctx):

        members = [member for member in self.client.get_all_members() if not member.bot]
        bots = [member for member in self.client.get_all_members() if member.bot]

        message = f"""
        Number of Members: {len(members)} \nNumber of Bots: {len(bots)}
        """

        await ctx.channel.send(message)


    @membercount.error
    async def membercount_error(self, ctx, error):
        commandName = ctx.invoked_with
        error = str(error)

        herupaErrorLogChannel = self.client.get_channel(configFile()["herupaErrorLogChannel"])
        await herupaErrorLogChannel.send(f"{commandName.upper()} error: {error}")

def setup(client):
    client.add_cog(MemberCount(client))