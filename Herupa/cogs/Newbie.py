'''
Purpose: This command will allow the member to accept our terms of service and make the rest of the server visible to them.
'''

import asyncio
import discord
from discord.ext import commands

class Newbie(commands.Cog):

    def __init__(self, client):
        self.client = client
        self.newbieRoleName = "newbie"
        self.newbieChannelName = "👶newbie👶"
        self.botRoleName = "servants"

    @commands.Cog.listener()
    async def on_message(self, message):
        
        # If the user sent the message in the newbie channel        
        if (message.channel.name == self.newbieChannelName) and (message.author != self.client.user):

            # If the user did not run the newbie command
            if not message.content.startswith("$newbie "):

                # Deleting the message
                await message.delete()

                # Sending feedback to the user and saving our feedback to a variable so we can delete it later on
                notificationMessage = await message.channel.send(f"This channel is only for using the \"$newbie\" command. Please read the pinned message fully.")

                # Waiting a few seconds before deleting the feedback
                await asyncio.sleep(10)

                # Actually deleting the feedback
                await notificationMessage.delete()

    @commands.Cog.listener()
    async def on_member_join(self, member):

        if member.bot: 

            # Declaring the role that should be given to the bots
            role = discord.utils.get(member.guild.roles, name=self.botRoleName)

        else:

            # Declaring the role that should be given to new members
            role = discord.utils.get(member.guild.roles, name=self.newbieRoleName)

        # Actually applying the role to the member/bot
        await member.add_roles(role)


    @commands.command(name='newbie',
                    description='Gives the member appropriate permissions after they accept the ToS of the server.',
                    brief='Gives the member appropriate permissions after they accept the ToS of the server.')
    async def newbie(self, ctx):
    
        # If the user sent the command in the newbie channel        
        if ctx.message.channel.name == self.newbieChannelName:

            # If they accept the server's terms of service
            if ctx.message.content.lower() == "$newbie accept":

                # Getting the newbie role
                role_to_remove = discord.utils.get(ctx.message.guild.roles, name=self.newbieRoleName)

                # Actually removing the newbie role from the member
                await ctx.message.author.remove_roles(role_to_remove)

                # Sending feedback to the user and saving our feedback to a variable so we can delete it later on
                acceptanceMessage = await ctx.message.channel.send(f"Welcome to **{ctx.message.guild}**, {ctx.message.author.name}! You should now see all available channels.")

                # Waiting a few seconds before deleting the feedback
                await asyncio.sleep(7)

                # Actually deleting the feedback
                await acceptanceMessage.delete()

                # Deleting the trigger message as well
                await ctx.message.delete()

            else:

                # Providing feedback
                feedback = await ctx.message.channel.send("Incorrect input! Did you mispell something?")

                # Waiting 5 seconds before deleting feedback
                await asyncio.sleep(5)

                # Actually deleting the feedback
                await feedback.delete()

                # Deleting the trigger message
                await ctx.message.delete()

                raise Exception(f'{ctx.message.author.name}#{ctx.message.author.discriminator} did not write "I ACCEPT".')



async def setup(client):
    await client.add_cog(Newbie(client))