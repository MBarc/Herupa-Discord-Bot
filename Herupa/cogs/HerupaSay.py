# Herupa joins the author's voice channel and speaks their text using Google
# Translate's TTS voice (Japanese voice on purpose — the "hearmygirlfriendsvoice" gag).
# Reference: https://translate.google.com/translate_tts?ie=UTF-8&client=tw-ob&tl=ja&q={text}

from pathlib import Path
from urllib.parse import quote

import aiohttp
import discord
from better_profanity import profanity
from discord.ext import commands

# Google Translate TTS rejects a query longer than ~200 characters.
MAX_CHARS = 200
TTS_URL = "https://translate.google.com/translate_tts?ie=UTF-8&client=tw-ob&tl=ja&q={}"


class HerupaSay(commands.Cog):

    def __init__(self, client):
        self.client = client

    @commands.command(name='herupasay',
                      aliases=['hs', 'hearmygirlfriendsvoice'])
    async def herupasay(self, ctx):

        # Everything after the command word is what Herupa should say.
        parts = ctx.message.content.split(" ", 1)
        text = parts[1].strip() if len(parts) > 1 else ""

        if not text:
            await ctx.channel.send("Sorry, what was it that you wanted me to say?")
            return

        if len(text) > MAX_CHARS:
            await ctx.channel.send(f"That's a bit long — keep it under {MAX_CHARS} characters.")
            return

        if profanity.contains_profanity(text):
            await ctx.channel.send("I'm not saying that. . .")
            return

        # The author has to be in a voice channel for Herupa to join them.
        if ctx.author.voice is None:
            await ctx.channel.send("You need to be in a voice channel to use this command.")
            return

        # Don't interrupt audio that's already playing in this guild.
        voice = ctx.guild.voice_client
        if voice and voice.is_playing():
            await ctx.channel.send("Hang on — I'm still saying the last one.")
            return

        # Fetch the TTS audio, properly URL-encoding the phrase so characters
        # like & # + and emoji can't break or inject into the request.
        url = TTS_URL.format(quote(text, safe=""))
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url) as r:
                    if r.status != 200:
                        await ctx.channel.send("I couldn't reach my voice right now — try again in a moment.")
                        return
                    audio_content = await r.read()
        except aiohttp.ClientError:
            await ctx.channel.send("I couldn't reach my voice right now — try again in a moment.")
            return

        # Write to a per-message file so concurrent calls never clash over one path.
        audio_dir = Path.cwd() / "audio_repo"
        audio_dir.mkdir(parents=True, exist_ok=True)
        audio_file = audio_dir / f"{ctx.message.id}.mp3"
        audio_file.write_bytes(audio_content)

        def cleanup(_error):
            # Runs on a worker thread once playback finishes (or errors).
            try:
                audio_file.unlink(missing_ok=True)
            except OSError:
                pass

        # Connect to — or move into — the author's voice channel.
        try:
            if voice and voice.is_connected():
                if voice.channel != ctx.author.voice.channel:
                    await voice.move_to(ctx.author.voice.channel)
            else:
                voice = await ctx.author.voice.channel.connect()
                await ctx.channel.send("Joined the voice channel!")
        except discord.ClientException:
            cleanup(None)
            await ctx.channel.send("I'm having trouble joining your voice channel.")
            return

        # Play at 90% volume; wrap the source before playing so volume is set atomically.
        source = discord.PCMVolumeTransformer(discord.FFmpegPCMAudio(str(audio_file)), volume=0.90)
        try:
            voice.play(source, after=cleanup)
        except discord.ClientException:
            # Lost the race to another invocation that started playing first.
            cleanup(None)
            await ctx.channel.send("Hang on — I'm still saying the last one.")


async def setup(client):
    await client.add_cog(HerupaSay(client))
