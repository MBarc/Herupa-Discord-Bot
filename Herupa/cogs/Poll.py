# Importing custom config file and default libraries
from discord.ext import commands
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

        parts = message.split('"')[1:]
        title = parts[0]
        choices = [part.strip() for part in parts[1:] if part.strip()]

        return title, choices

    @commands.command(name='poll',
                      description='Creates a poll where people can vote on the best option.',
                      brief='Creates a voting poll.',
                      aliases=["pl"])
    async def poll(self, ctx):
        title, choices = self.get_title_and_choices(ctx.message.content)

        if not choices:
            await ctx.send('Incorrect format! Your message should be like this -> "Title" "Choice 1" "Choice 2" "Choice 3"')
            return

        if len(choices) > 26:
            raise commands.BadArgument("Too many choices! Only a maximum of 26 choices are allowed.")

        embed = discord.Embed(title=title, colour=discord.Colour.from_rgb(255, 183, 197))

        for i, choice in enumerate(choices):
            embed.add_field(name=self.emojiLetters[i], value=choice, inline=False)

        message = await ctx.send(embed=embed)

        for emoji in self.emojiLetters[:len(choices)]:
            await message.add_reaction(emoji)
            
        await ctx.message.delete()

async def setup(client):
    await client.add_cog(Poll(client))
