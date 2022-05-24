'''
This command is to make sure that people aren't using voice-dedicated
text channels as general purpose chats.
'''

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
import asyncio

class ChatModerator(commands.Cog):

    def __init__(self, client):
        self.client = client

    @commands.Cog.listener()
    async def on_message(self, message):

        # Determining whether or not message is direct message
        if isinstance(message.channel, discord.channel.DMChannel):
            return

        channels = {
            "💰money-talk💰": {
                "textChannelID": configFile()["chat-moderator"]["money-talk-text"],
                "voiceChannelID": configFile()["chat-moderator"]["money-talk-voice"]
            },
            "☕coffee-talk☕": {
                "textChannelID": configFile()["chat-moderator"]["coffee-talk-text"],
                "voiceChannelID": configFile()["chat-moderator"]["coffee-talk-voice"]
            }
        }

        if message.channel.name in channels:

            # Checking to see if anyone is in the voice channel
            voiceChannelID = channels.get(message.channel.name)['voiceChannelID']
            voice_channel = self.client.get_channel(voiceChannelID)
            members = voice_channel.members

            # If there are no members in the voice channel, delete the message.
            if not members and not message.author.bot:
                await message.delete()
                botMessage = await message.channel.send(f"In order to to avoid people using {message.channel.name} as a general chat, messages can only be sent while someone (doesn't matter who) is in the respective voice channel. This message will now self-destruct. . .")
                await asyncio.sleep(15)
                await botMessage.delete()

def setup(client):
    client.add_cog(ChatModerator(client))