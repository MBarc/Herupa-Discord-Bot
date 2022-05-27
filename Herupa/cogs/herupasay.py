# https://translate.google.com/translate_tts?ie=UTF-8&client=tw-ob&tl=ja&q={name}
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
from better_profanity import profanity
from discord.utils import get
import requests


class HerupaSay(commands.Cog):

    def __init__(self, client):
        self.client = client

    @commands.command(name='herupasay',
                      aliases=['hs', 'hearmygirlfriendsvoice'])
    async def herupasay(self, ctx):

        ctx.channel.send("This command was updated automatically.")
        
        if ctx.message.author.id == 353315864726077471:
            ctx.channel.send("You are not allowed to use this command.")
            return

        # Getting the member so we know who to connect to
        member = ctx.message.author

        # If the user didn't put anything for Herupa to say
        if len(ctx.message.content.split(" ")) <= 1:
            await ctx.channel.send("Sorry, what was it that you wanted me to say?")
            return

        # If the user put profanity to
        if profanity.contains_profanity(ctx.message.content):
            await ctx.channel.send("I'm not saying that. . .")
            return

        # Getting the content of the message and making it be URL compatible
        content = ctx.message.content.split(" ", 1)[1].replace(" ", "%20")

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

        # Preparing the url that we're going to make a request from
        url = f"https://translate.google.com/translate_tts?ie=UTF-8&client=tw-ob&tl=ja&q={content}"

        # Actually making the request
        r = requests.get(url)

        # Preparing the path that where we'll store the mp3 file
        audio_file = str(Path.cwd() / "audio_repo/phrase.mp3")
        
        discord.opus.load_opus()

        # Creating the mp3 file
        with open(audio_file, "wb+") as file:
            file.write(r.content)

        # Getting the voice channel that Herupa is currently connected to
        voice = get(self.client.voice_clients, guild=ctx.guild)

        # Playing the audio
        voice.play(discord.FFmpegPCMAudio(audio_file))
        voice.source = discord.PCMVolumeTransformer(voice.source)
        voice.source.volume = 0.90

    @herupasay.error
    async def herupa_error(self, ctx, error):

        commandName = ctx.invoked_with
        error = str(error)

        if "TypeError: stat: path should be string, bytes, os.PathLike or integer, not NoneType" in error:
            moneyshark = '<@400475368550694942>'
            await ctx.channel.send(
                f"Hello there! Sorry I don't know how to pronounce that name. Please let {moneyshark} know (he's my english teacher).")

        herupaErrorLogChannel = self.client.get_channel(configFile()["herupaErrorLogChannel"])
        await herupaErrorLogChannel.send(f"{commandName.upper()} error: {error}")


def setup(client):
    client.add_cog(HerupaSay(client))
