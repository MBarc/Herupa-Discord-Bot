'''
Purpose: This command is for deputies to put a member into purgatory asa displinary action.
'''

from discord.ext import commands
from discord.utils import get
import discord

class Purgatory(commands.Cog):

    def __init__(self, client):
        self.client = client
        self.allowedRoles = ["head chill", "sheriff", "deputy"]
        self.notificationChannel = "💯admin-chat💯"

    @commands.command(name="purgatory",
                      aliases=["purg", "pgt"])
    async def purgatory(self, ctx):

        # Ensure that the author only had 1 mention in their command
        if len(ctx.message.mentions) != 1:
            await ctx.send("You can only mention 1 member at a time for this command!", delete_after=10)
            return

        # Get the mention that the author specified
        member = ctx.message.mentions[0]
        mention = member.mention

        # Get the channel the command was invoked from
        command_channel = ctx.channel

        # Get all the roles of the author
        author_roles = [role.name.lower() for role in ctx.author.roles]

        # If the author running the command has a role in self.allowedRoles. Don't take into account capitalization.
        if any(role in author_roles for role in self.allowedRoles):
            # Give the mention the "purgatory" role
            purgatory_role = get(ctx.guild.roles, name="purgatory")
            if purgatory_role:
                await member.add_roles(purgatory_role)

                # Get the notification channel
                notification_channel = get(ctx.guild.channels, name=self.notificationChannel)

                # If the channel where the command was invoked from is the same as self.notificationChannel
                if command_channel == notification_channel:
                    # Send the message f"{mention} has been granted the @purgatory role." into self.notificationChannel
                    await notification_channel.send(f"{mention} has been granted the @purgatory role.")
                else:
                    # Send the message f"{mention} has been granted the @purgatory role." into the channel where the command was invoked
                    await command_channel.send(f"{mention} has been granted the @purgatory role.", delete_after=10)

                    # Send the message f"{mention} has been granted the @purgatory role." into self.notificationChannel
                    await notification_channel.send(f"{mention} has been granted the @purgatory role.")
            else:
                await command_channel.send("The 'purgatory' role does not exist.", delete_after=10)
        else:
            # Send "You must be a Deputy or higher to use this command!" into the channel where the command was invoked
            await command_channel.send("You must be a Deputy or higher to use this command!", delete_after=10)

async def setup(client):
    await client.add_cog(Purgatory(client))