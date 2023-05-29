# Importing custom config file and default libraries
import sys
import os
from pathlib import Path
from turtle import color
configPath = Path(os.path.abspath(os.path.dirname(__file__))).parent.absolute()
sys.path.insert(0, configPath)
from config import configFile
from discord.ext import commands

# Importing libraries only used in this command
import shlex
import discord

class Poll(commands.Cog):

    def __init__(self, client):
        self.client = client

        self.emojiLetters = [
                "\N{REGIONAL INDICATOR SYMBOL LETTER A}",
                "\N{REGIONAL INDICATOR SYMBOL LETTER B}",
                "\N{REGIONAL INDICATOR SYMBOL LETTER C}",
                "\N{REGIONAL INDICATOR SYMBOL LETTER D}",
                "\N{REGIONAL INDICATOR SYMBOL LETTER E}", 
                "\N{REGIONAL INDICATOR SYMBOL LETTER F}",
                "\N{REGIONAL INDICATOR SYMBOL LETTER G}",
                "\N{REGIONAL INDICATOR SYMBOL LETTER H}",
                "\N{REGIONAL INDICATOR SYMBOL LETTER I}",
                "\N{REGIONAL INDICATOR SYMBOL LETTER J}",
                "\N{REGIONAL INDICATOR SYMBOL LETTER K}",
                "\N{REGIONAL INDICATOR SYMBOL LETTER L}",
                "\N{REGIONAL INDICATOR SYMBOL LETTER M}",
                "\N{REGIONAL INDICATOR SYMBOL LETTER N}",
                "\N{REGIONAL INDICATOR SYMBOL LETTER O}",
                "\N{REGIONAL INDICATOR SYMBOL LETTER P}",
                "\N{REGIONAL INDICATOR SYMBOL LETTER Q}",
                "\N{REGIONAL INDICATOR SYMBOL LETTER R}",
                "\N{REGIONAL INDICATOR SYMBOL LETTER S}",
                "\N{REGIONAL INDICATOR SYMBOL LETTER T}",
                "\N{REGIONAL INDICATOR SYMBOL LETTER U}",
                "\N{REGIONAL INDICATOR SYMBOL LETTER V}",
                "\N{REGIONAL INDICATOR SYMBOL LETTER W}",
                "\N{REGIONAL INDICATOR SYMBOL LETTER X}",
                "\N{REGIONAL INDICATOR SYMBOL LETTER Y}",
                "\N{REGIONAL INDICATOR SYMBOL LETTER Z}"
            ]

    def get_title_and_choices(self, message):
        """
        Returns the title (as a string) and the choices (as a list) for the given poll/message
        """

        message = shlex.split(message, posix=False)
        message.remove(message[0])
        message = [s.replace('"', '') for s in message]

        title = message[0]
        message.remove(message[0])
        choices = message

        return title, choices

    @commands.command()
    async def poll(self, ctx):
        
        title, choices = self.get_title_and_choices(ctx.message.content)

        if len(choices) > 26:
            raise Exception("Too many choices! Only a maximum of 26 choices are allowed.")

        embed = discord.Embed(title=title, colour=discord.Colour.from_rgb(255, 183, 197))

        for i in range(len(choices)):
            embed.add_field(name=self.emojiLetters[i], value=choices[i], inline=False)

        message = await ctx.message.channel.send(embed=embed)

        for i in range(len(choices)):
            await message.add_reaction(self.emojiLetters[i])
            
        await ctx.message.delete()


    @poll.error
    async def poll_error(self, ctx, error):

        await ctx.message.send('Incorrect format! Your message should be like this -> "Title" "Choice 1" "Choice 2" "Choice 3"')

        commandName = ctx.invoked_with
        error = str(error)

        herupaErrorLogChannel = self.client.get_channel(configFile()["herupaErrorLogChannel"])
        await herupaErrorLogChannel.send(f"{commandName.upper()} error: {error}")

async def setup(client):
    await client.add_cog(Poll(client))
