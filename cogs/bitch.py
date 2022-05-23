# Importing custom config file and default libraries
import sys
import os
from pathlib import Path
configPath = Path(os.path.abspath(os.path.dirname(__file__))).parent.absolute()
sys.path.insert(0, configPath)
from config import configFile

# Importing libraries specifically used for this command
from discord.ext import commands

class Bitch(commands.Cog):

    def __init__(self, client):
        self.client = client

    @commands.command()
    async def bitch(self, ctx):
        #twinkie = '<@353315864726077471>'
        #await ctx.message.channel.send(f"Hey {twinkie}, they're calling you.")
        await ctx.message.channel.send(f"This command is no longer operational.")

    @bitch.error
    async def bitch_error(self, ctx, error):

        commandName = ctx.invoked_with
        error = str(error)

        herupaErrorLogChannel = self.client.get_channel(configFile()["herupaErrorLogChannel"])
        await herupaErrorLogChannel.send(f"{commandName.upper()} error: {error}")
        
# testing super late at night

def setup(client):
    client.add_cog(Bitch(client))
