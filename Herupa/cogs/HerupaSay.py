# https://translate.google.com/translate_tts?ie=UTF-8&client=tw-ob&tl=ja&q={name}

# Importing libraries specifically used for this command
import discord
import ctypes
import requests
from better_profanity import profanity
from discord.utils import get
from discord.ext import commands
from pathlib import Path


class HerupaSay(commands.Cog):

    def __init__(self, client):
        self.client = client

    @commands.command(name='herupasay',
                      aliases=['hs', 'hearmygirlfriendsvoice'])
    async def herupasay(self, ctx):

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
        print(audio_file)

        # Uncomment this stuff for a linux environment
        # Loading up opus so we can play audio over the internet
        #opuslib = ctypes.util.find_library("opus")
        #print(opuslib)
        #print("before 1")
        #print(discord.opus.is_loaded())
        #discord.opus.load_opus(opuslib)

        # Creating the mp3 file
        with open(audio_file, "wb+") as file:
            file.write(r.content)

        # Getting the voice channel that Herupa is currently connected to
        voice = get(self.client.voice_clients, guild=ctx.guild)

        # Playing the audio
        voice.play(discord.FFmpegPCMAudio(audio_file))
        voice.source = discord.PCMVolumeTransformer(voice.source)
        voice.source.volume = 0.90

async def setup(client):
    await client.add_cog(HerupaSay(client))
