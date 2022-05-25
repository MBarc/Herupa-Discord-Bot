
import discord
from discord.ext import commands

import asyncio
from math import ceil
from itertools import islice


class Help(commands.Cog):

    def __init__(self, client):
        self.client = client

    @commands.command()
    async def help(self, ctx):

        def newEmbed(name, value):
            """Creating a new Discord.embed object
            """
            embed = discord.Embed(colour=discord.Colour.from_rgb(255, 183, 197))

            embed.set_author(name=f"Herupa's Help Page - {name}")

            for command in value:
                embed.add_field(name=command, value=value.get(command), inline=False)

            embed.add_field(name="\u200b", value="\u200b")
            embed.set_footer(text="https://github.com/MBarc/Herupa-Discord-Bot")

            return embed

        def check(reaction, user):
            # This makes sure nobody except the command sender can interact with the "menu"
            return user == ctx.author and str(reaction.emoji) in ["◀️", "▶️", "🤓", "❓"]

        def chunks(data, commandsPerPage):
            it = iter(data)
            for i in range(0, ceil(len(data)/commandsPerPage)):
                yield {k: data[k] for k in islice(it, commandsPerPage)}

        commands = {
            'avatarpic {@member}': 'Herupa will respond with the avatar pic of the member mentioned.',
            'clear {number}': 'Delete messages in bulk. If no number is specified, 5 messages are cleared.',
            'flip {heads or tails}': 'Have Herupa flip a coin. Specifying heads or tails is optional.',
            'herupa {name}': 'Herupa will join the voice channel and say the name specified.',
            'leave': 'Tell Herupa to leave the voice channel.',
            'lenny': 'Herupa responds with ( ͡° ͜ʖ ͡°)',
            'lennymoney': 'Herupa responds with [̲̅$̲̅(̲̅ ͡° ͜ʖ ͡°̲̅)̲̅$̲̅]',
            'migrate {channel name}': 'Move everyone in your current voice channel to another voice channel.',
            'rps': 'Play rock, paper, scissors against Herupa.',
            'github': "Responds with a link to Herupa's Github page",
            'isslocation': 'Get the coordinates and map of where the International Space Station currently is.',
            'whoisinspace': 'Get the amount and names of astronauts currently in space.',
            'issprediction {country, region, city}': 'Get the amount and names of astronauts currently in space.',
            'addfavorite': 'Add member to your favorites. They must add you back in order to receive notifications of when each other joins a voice channel.',
            'removefavorite': 'Remove member from your favorites. They will no longer receive notifications of when you join a voice channel.',
            'myfavorites': "See your list of favorites. This command works in either a public text channel or Herupa's DMs",
            'createroom {@members}': 'Create a private voice chat with the members specified. Specifying members is optional.',
            'add2room {@members}': 'Add members to private voice chat after the room has been created.',
            'kanye': 'Get a random Kanye West quote.',
        }

        backgroundTasks = {
            'AFK': 'Herupa automatically keeps track of how long members are AFK and moves them to the appropriate AFK voice channels.',
            'Newbie': 'Responsible for assigning the newbie role to new members and assigning the chillies role once members accept to our ToS.',
            'Clear Channel': 'Clears out certain text channels everyday at 6:30am EST.',
            'On Member Join': 'Greets new members with a unique greeting.',
            'Favorites': "Sends a notification to all of your favorites (assuming you're their favorite too) letting them know that you connected to a voice chat.",
            'Destroy Room': "Destroys a private voice chat if the last person leaves the channel. Redundant policy will delete the channel at 6:30am EST.",
        }

        helpPage = {
            "❓": "Displays the help page for the help command.",
            "◀️": "Goes back 1 page.",
            "▶️": "Goes forward 1 page.",
            "🤓": "Displays all of Herupa's background tasks.",
        }

        commandsPerPage = 10
        contents = [item for item in chunks(commands, commandsPerPage)]
        pages = ceil(len(contents))
        cur_page = 0

        message = await ctx.send(embed=newEmbed(name="Help Page", value=helpPage))
        # getting the message object for editing and reacting

        await message.add_reaction("❓")
        await message.add_reaction("◀️")
        await message.add_reaction("▶️")
        await message.add_reaction("🤓")


        while True:
            try:
                # waiting for a reaction to be added - times out after 60 seconds
                reaction, user = await self.client.wait_for("reaction_add", timeout=60, check=check)

                if str(reaction.emoji) == "❓":
                    cur_page = 0
                    await message.edit(embed=newEmbed(name="Help Page", value=helpPage))
                    await message.remove_reaction(reaction, user)

                elif str(reaction.emoji) == "▶️" and cur_page != pages:
                    cur_page += 1
                    await message.edit(embed=newEmbed(name=f"Page {cur_page}/{pages}", value=contents[cur_page - 1]))
                    await message.remove_reaction(reaction, user)

                elif str(reaction.emoji) == "▶️" and cur_page == pages:
                    cur_page = 1
                    await message.edit(embed=newEmbed(name=f"Page {cur_page}/{pages}", value=contents[cur_page - 1]))
                    await message.remove_reaction(reaction, user)

                elif str(reaction.emoji) == "◀️" and (cur_page == 1 or cur_page == 0):
                    cur_page = len(contents)
                    await message.edit(embed=newEmbed(name=f"Page {cur_page}/{pages}", value=contents[cur_page - 1]))
                    await message.remove_reaction(reaction, user)

                elif str(reaction.emoji) == "◀️" and cur_page > 1:
                    cur_page -= 1
                    await message.edit(embed=newEmbed(name=f"Page {cur_page}/{pages}", value=contents[cur_page - 1]))
                    await message.remove_reaction(reaction, user)

                elif str(reaction.emoji) == "🤓":
                    cur_page = 0
                    await message.edit(embed=newEmbed(name="Background Tasks", value=backgroundTasks))
                    await message.remove_reaction(reaction, user)
                else:
                    await message.remove_reaction(reaction, user)

            except asyncio.TimeoutError:

                await message.delete()

                # ending the loop if user doesn't react after x seconds
                break


def setup(client):
    client.add_cog(Help(client))
