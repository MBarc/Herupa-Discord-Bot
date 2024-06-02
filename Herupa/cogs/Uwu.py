# https://translate.google.com/translate_tts?ie=UTF-8&client=tw-ob&tl=ja&q={name}
# Importing custom config file and default libraries

# Importing libraries specifically used for this command
import discord
import ctypes
import requests
from better_profanity import profanity
from discord.utils import get
from discord.ext import commands
from pathlib import Path

class UWU(commands.Cog):

    def __init__(self, client):
        self.client = client

    @commands.command(name='uwu',
                      aliases=["u"])
    async def uwu(self, ctx):

        # Getting the member so we know who to connect to
        member = ctx.message.author

        # Checking to see if the member is in a voice chat
        if member.voice is None:
            await ctx.channel.send("You need to be in a voice channel to use this command.")
            return

        # Checking to see if Herupa is already connected to voice channel
        voice = get(self.client.voice_clients, guild=ctx.guild)

        # Moving/connecting to the user's voice channel
        if voice and voice.is_connected():
            await voice.move_to(member.voice.channel)
        else:
            await member.voice.channel.connect()
            await ctx.channel.send("Joined the voice channel!")

        # Preparing the path that where we'll store the mp3 file
        audio_file = str(Path.cwd() / "audio_repo/uwu.mp3")

        # Uncomment this section when deploying to a linux environment
        # Loading up opus so we can play audio over the internet
        #opuslib = ctypes.util.find_library("opus")
        #discord.opus.load_opus(opuslib)

        # Getting the voice channel that Herupa is currently connected to
        voice = get(self.client.voice_clients, guild=ctx.guild)

        # Playing the audio
        voice.play(discord.FFmpegPCMAudio(audio_file))
        voice.source = discord.PCMVolumeTransformer(voice.source)
        voice.source.volume = 0.90


async def setup(client):
    await client.add_cog(UWU(client))
