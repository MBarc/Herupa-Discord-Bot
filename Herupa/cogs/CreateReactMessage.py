'''
Purpose: This command will create a message where users can react to it and receive the assigned roll.
'''

import sys
import os

import discord
from discord.ext import commands

# Get the parent directory of the current script
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)

# Add the parent directory to the Python path so we can import our custom library
sys.path.append(parent_dir)

from tools.HerupaMongo import HerupaMongo

class CreateReactMessage(commands.Cog):

    def __init__(self, client):
        self.client = client
        self.dbName = "react_messages"
        self.mongo_instance = HerupaMongo()

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

        parts = message.split('"')[1:]
        title = parts[0]
        choices = [part.strip() for part in parts[1:] if part.strip()]

        # If not all the choices are of type discord.Role
        if not all(isinstance(choice, discord.Role) for choice in choices):
            raise TypeError("Not all the choices are of type discord.Role!")

        return title, choices

    @commands.command(name="createreactmessage",
                      description="Creates a message where users can react to receive the corresponding roll.",
                      brief="Creates a react message.",
                      aliases=["crm"])
    async def CreateReactMessage(self, ctx):

        title, choices = self.get_title_and_choices(ctx.message.content)

        if not choices:
            await ctx.send('Incorrect format! Your message should be like this -> "Prompt" "Role 1" "Roll 2" "Roll 3"')
            return

        if len(choices) > 26:
            raise commands.BadArgument("Too many choices! Only a maximum of 26 choices are allowed.")

        embed = discord.Embed(title=title, colour=discord.Colour.from_rgb(255, 183, 197))

        # Creating a collection for the react message 
        self.mongo_instance.createCollection(database_name=f"{ctx.message.guild.id}_react_messages", collection_name=ctx.message.id)

        # Adding the choices to the message and adding them as documents to the collection
        for i, choice in enumerate(choices):
            embed.add_field(name=self.emojiLetters[i], value=choice.name, inline=False)
            self.mongo_instance.addCollectionEntry(database_name=f"{ctx.message.guild.id}_react_messages", collection_name=ctx.message.id, payload={self.emojiLetters[i], choice.name})

        # Sending the react message
        message = await ctx.send(embed=embed)

        # Adding the reactions to the react message
        for emoji in self.emojiLetters[:len(choices)]:
            await message.add_reaction(emoji)

        # Cleaning up messages
        await ctx.message.delete()




async def setup(client):
    await client.add_cog(CreateReactMessage(client))