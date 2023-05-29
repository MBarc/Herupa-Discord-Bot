# Importing custom config file and default libraries
import sys
import os
from pathlib import Path
configPath = Path(os.path.abspath(os.path.dirname(__file__))).parent.absolute()
sys.path.insert(0, configPath)
from config import configFile
from discord.ext import commands

# Importing libraries specifically used for this command
import discord
import datetime

class Logging(commands.Cog):

    def __init__(self, client):
        self.client = client

    @commands.Cog.listener()
    async def on_user_update(self, before, after):
        '''Called when a member.
        Things that could be updated:
            avatar
            username
            discriminator
        '''

        # Declaring the channel to send the profile updates to
        profileUpdateChannel = self.client.get_channel(configFile()["logging"]["profile-update"])

        #  If the user's display name has changed
        if (before.display_name != after.display_name):
            await profileUpdateChannel.send(f"Display name change for **{before.name}#{before.discriminator}**: **{before.display_name}** was changed to **{after.display_name}** at **{datetime.datetime.now()}**.")

        # If the user's discriminator has changed
        if (before.discriminator != after.discriminator):
            await profileUpdateChannel.send(f"Discriminator change for **{before.name}#{before.discriminator}**: **{before.discriminator}** was changed to **{after.discriminator}** at **{datetime.datetime.now()}**.")

        # If the user's profile picture has changed
        if (before.avatar != after.avatar):
            await profileUpdateChannel.send(f"Profile picture change for **{before.name}#{before.discriminator}**: {before.avatar_url} was changed to {after.avatar_url} at **{datetime.datetime.now()}**.")


    @commands.Cog.listener()
    async def on_member_update(self, before, after):
        """Called when a member.
        Things that could be updated:
            status
            nickname
            pending
        """

        # Declaring the channels that we're going to send updates into
        profileUpdateChannel = self.client.get_channel(configFile()["logging"]["profile-update"])
        statusChannel = self.client.get_channel(configFile()["logging"]["status"])

        if (before.status != after.status):
            await statusChannel.send(f"Status change for **{before.name}#{before.discriminator}**: **{str(before.status).upper()}** was changed to **{str(after.status).upper()}** at **{datetime.datetime.now()}**.")

        if (before.nick != after.nick):
            await profileUpdateChannel.send(f"Display name change for **{before.name}#{before.discriminator}**: **{before.nick}** was changed to **{after.nick}** at **{datetime.datetime.now()}**.")

    @commands.Cog.listener()
    async def on_typing(self, channel, member, when):
        """Called when a member starts typing."""
        typingChannel = self.client.get_channel(configFile()["logging"]["typing"])
        await typingChannel.send(f"**{member.name}#{member.discriminator}** has started typing in **{channel.name}** at **{datetime.datetime.now()}**.")

    @commands.Cog.listener()
    async def on_voice_state_update(self, member, before, after):
        """Called when a member joins or leaves a voice chat."""
        vcLeaveOrJoinChannel = self.client.get_channel(configFile()["logging"]["vc-leave-or-join"])

        if before.channel is None:
            await vcLeaveOrJoinChannel.send(f"**{member.name}#{member.discriminator}** has joined **{after.channel}** at **{datetime.datetime.now()}**.")

        if before.channel != after.channel and after.channel is not None and before.channel is not None:
            await vcLeaveOrJoinChannel.send(f"**{member.name}#{member.discriminator}** has moved from **{before.channel}** to **{after.channel}** at **{datetime.datetime.now()}**.")

        if before.channel != after.channel and after.channel is None:
            await vcLeaveOrJoinChannel.send(f"**{member.name}#{member.discriminator}** disconnected from **{before.channel}** at **{datetime.datetime.now()}**. They did not move to another channel with this action.")

    @commands.Cog.listener()
    async def on_message_delete(self, message):
        """Called when a member deletes a message."""

        # Declaring the elements of the message that are relevant
        messageAuthor = message.author
        messageContent = message.content
        messageChannel = message.channel

        # We haven't discovered who deleted the message yet
        deleter = None

        # Declaring where we will send the update to
        messageDeleteChannel = self.client.get_channel(configFile()["logging"]["message-delete"])

        # Finding out who the deleter is
        async for entry in message.guild.audit_logs(limit=1, action=discord.AuditLogAction.message_delete):
            deleter = entry.user

        # Sending the update
        await messageDeleteChannel.send(f"**{deleter}** deleted a message by **{messageAuthor}** that was sent in **{messageChannel}** at **{datetime.datetime.now()}**. The content of the message was the following: {messageContent}")

async def setup(client):
    await client.add_cog(Logging(client))
