# Importing custom config file and default libraries
import sys
import os
from pathlib import Path
configPath = Path(os.path.abspath(os.path.dirname(__file__))).parent.absolute()
sys.path.insert(0, configPath)
from config import configFile
from discord.ext import commands

# Importing libraries specifically used for this command
import random

class RPS(commands.Cog):

    def __init__(self, client):
        self.client = client

    @commands.command(name = 'rps',
                    description = 'Play rock, paper, scissors against Herupa!',
                    brief = 'Play rock, paper, scissors.')
    async def rps(self, ctx, arg):
        user_input = arg.lower()
        answer_choices = ['rock', 'paper', 'scissors']
        bot_choice = random.choice(answer_choices)

        if user_input == 'rock' and bot_choice == 'scissors':
            await ctx.channel.send('You won! I picked scissors.')
        elif user_input == 'paper' and bot_choice == 'rock':
            await ctx.channel.send('You won! I picked rock.')
        elif user_input == 'scissors' and bot_choice == 'paper':
            await ctx.channel.send('You won! I picked paper.')
        elif user_input != 'rock' and user_input != 'paper' and user_input != 'scissors':
            await ctx.channel.send('Please pick between rock, paper, or scissors.')
        elif user_input == bot_choice:
            await ctx.channel.send(f"It's a draw! We both picked {bot_choice}.")
        else:
            await ctx.channel.send(f'You lost! I picked {bot_choice}.')

    @rps.error
    async def rps_error(self, ctx, error):

        commandName = ctx.invoked_with
        error = str(error)

        herupaErrorLogChannel = self.client.get_channel(configFile()["herupaErrorLogChannel"])
        await herupaErrorLogChannel.send(f"{commandName.upper()} error: {error}")

def setup(client):
    client.add_cog(RPS(client))
