# Importing custom config file and default libraries
import sys
import os
import asyncio
from pathlib import Path
configPath = Path(os.path.abspath(os.path.dirname(__file__))).parent.absolute()
sys.path.insert(0, configPath)
from config import configFile
from discord.ext import commands

# Importing libraries specifically used for this command
from discord.utils import get

class Newbie(commands.Cog):

    def __init__(self, client):
        self.client = client

    @commands.command()
    async def newbie(self, ctx):
        if ctx.message.channel.name == "📁rules📂":

            if "I ACCEPT" in ctx.message.content.upper():

                chiliesRole = get(ctx.message.guild.roles, name='chilies')
                await ctx.message.author.add_roles(chiliesRole)

                newbieRole = get(ctx.message.guild.roles, name="newbies")
                await ctx.message.author.remove_roles(newbieRole)

                await ctx.message.delete()

                feedback = await ctx.message.channel.send("Welcome to Chill Club! Come on in, you can now see the rest of Chill Club.")

                await asyncio.sleep(7)

                await feedback.delete()

            else:
                # Deleting their message
                await ctx.message.delete()

                # Providing feedback
                feedback = await ctx.message.channel.send("Incorrect input! Did you mispell something?")

                # Waiting 5 seconds before deleting feedback
                await asyncio.sleep(7)

                # Actually deleting the feedback
                await feedback.delete()

                raise Exception(f'{ctx.message.author.name}#{ctx.message.author.discriminator} did not write "I ACCEPT".')

    @newbie.error
    async def newbie_error(self, ctx, error):

        commandName = ctx.invoked_with
        error = str(error)

        herupaErrorLogChannel = self.client.get_channel(configFile()["herupaErrorLogChannel"])
        await herupaErrorLogChannel.send(f"{commandName.upper()} error: {error}")

def setup(client):
    client.add_cog(Newbie(client))
