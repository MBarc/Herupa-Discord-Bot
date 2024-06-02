'''
Purpose: Herupa returns the number of members and bots in the server where the message was sent.
'''

from discord.ext import commands

class MemberCount(commands.Cog):
    def __init__(self, client):
        self.client = client

    @commands.command(name='membercount',
                      description='Returns the member and bot count of the server where the message was sent.',
                      brief='Show server member count.',
                      aliases=["mc"])
    async def membercount(self, ctx):
        # Count the number of human members and bot members in the server
        member_count = sum(not member.bot for member in ctx.guild.members)
        bot_count = sum(member.bot for member in ctx.guild.members)

        # Create a message with the member and bot count
        message = f"Number of Members: {member_count}\nNumber of Bots: {bot_count}"

        # Send the message to the channel where the command was invoked
        await ctx.send(message)

# This function is required by discord.py to add this cog to the bot
async def setup(client):
    await client.add_cog(MemberCount(client))
