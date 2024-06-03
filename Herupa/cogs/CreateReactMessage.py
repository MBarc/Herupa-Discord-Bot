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

    def get_title_and_choices(self, message, ctx):
        """
        Returns the title (as a string) and the choices (as a list) for the given poll/message
        """

        parts = message.split(' ')[1:]
        title = parts[0]
        choices = [part.strip() for part in parts[1:] if part.strip()]

        # Going through every choice to validate that it's a role in the server
        for choice in choices:
            choice = int(choice[3:-1])
            role = discord.utils.get(ctx.guild.roles, id=choice)

            # If one of the choices is not a role
            if not role:
                raise Exception("Not all the choices are a role in the server!")

        return title, choices

    @commands.command(name="createreactmessage",
                      description="Creates a message where users can react to receive the corresponding roll.",
                      brief="Creates a react message.",
                      aliases=["crm"])
    async def CreateReactMessage(self, ctx):

        title, choices = self.get_title_and_choices(ctx.message.content, ctx)

        if not choices:
            await ctx.send('Incorrect format! Your message should be like this -> "Prompt" "Role 1" "Roll 2" "Roll 3"')
            return

        if len(choices) > 26:
            raise commands.BadArgument("Too many choices! Only a maximum of 26 choices are allowed.")

        embed = discord.Embed(title=title, colour=discord.Colour.from_rgb(255, 183, 197))

        # Declaring our database and collection
        database_name = f"{ctx.message.guild.id}_react_messages"

        # Adding the choices to the message and adding them as documents to the collection
        for i, choice in enumerate(choices):
            role = discord.utils.get(ctx.guild.roles, id=int(choice[3:-1]))
            embed.add_field(name=self.emojiLetters[i], value=role.name, inline=False)

        # Sending the react message
        message = await ctx.send(embed=embed)

        # Adding the reactions to the react message
        for emoji in self.emojiLetters[:len(choices)]:
            await message.add_reaction(emoji)

        # Adding the choices as documents to the collection ; this must be done after message object is created for collection_name
        for i, choice in enumerate(choices):
            role = discord.utils.get(ctx.guild.roles, id=int(choice[3:-1]))

            payload = {}
            payload[self.emojiLetters[i]] = role.name
            self.mongo_instance.addCollectionEntry(database_name=database_name, collection_name=str(message.id), payload=payload)

        # Cleaning up messages
        await ctx.message.delete()


    @commands.Cog.listener()
    async def on_raw_reaction_add(self, ctx):

        guildID = ctx.guild_id
        guild = self.client.get_guild(guildID)

        messageID = str(ctx.message_id)

        reaction = ctx.emoji

        database_name = f"{guildID}_react_messages"

        # if messageID is the name of a collection in our database
        if self.mongo_instance.doesCollectionExist(database_name=database_name, collection_name=messageID):

            document = self.mongo_instance.findSpecificDocumentsByKey(database_name=database_name, collection_name=messageID, key=reaction.name)

            role = discord.utils.get(guild.roles, name=document[0].get(reaction.name))

            await ctx.member.add_roles(role)

    @commands.Cog.listener()
    async def on_raw_reaction_remove(self, ctx):
        
        # Declaring the variables we'll need
        guildID = ctx.guild_id
        guild = self.client.get_guild(guildID)
        messageID = str(ctx.message_id)
        reaction = ctx.emoji
        database_name = f"{guildID}_react_messages"

        # if messageID is the name of a collection in our database
        if self.mongo_instance.doesCollectionExist(database_name=database_name, collection_name=messageID):

            # Finding the specific document 
            document = self.mongo_instance.findSpecificDocumentsByKey(database_name=database_name, collection_name=messageID, key=reaction.name)

            # Getting the corresponding role
            role = discord.utils.get(guild.roles, name=document[0].get(reaction.name))

            # Getting the member that we need to remove the role from
            member = guild.get_member(ctx.user_id)

            # Actually removing the roles
            await member.remove_roles(role)


async def setup(client):
    await client.add_cog(CreateReactMessage(client))
