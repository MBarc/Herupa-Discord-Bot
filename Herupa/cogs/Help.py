
import discord
from discord.ext import commands

import asyncio


class Help(commands.Cog):

    def __init__(self, client):
        self.client = client

    @commands.command(name="help", aliases=["h"])
    async def help(self, ctx):

        PINK = discord.Colour.from_rgb(255, 183, 197)

        def newEmbed(name, value):
            """Build a help embed from a {command: description} dict."""
            embed = discord.Embed(colour=PINK)
            embed.set_author(name=f"Herupa's Help Page - {name}")
            for command, desc in value.items():
                embed.add_field(name=command, value=desc, inline=False)
            embed.set_footer(text="Prefix: $   •   https://github.com/MBarc/Herupa-Discord-Bot")
            return embed

        def check(reaction, user):
            # Only the command's author can drive the menu, and only on this message.
            return (
                user == ctx.author
                and reaction.message.id == message.id
                and str(reaction.emoji) in ["◀️", "▶️", "🤓", "❓"]
            )

        landing = {
            "◀️ ▶️  Browse categories": "Flip through Herupa's command categories.",
            "🤓  Background tasks": "See what Herupa does automatically behind the scenes.",
            "❓  This page": "Come back here any time.",
            "​": "Every command starts with **$**, and most have a short alias — e.g. `$help` = `$h`.",
        }

        categories = [
            ("🎉 Fun & Novelty", {
                "$lenny · $l": "Herupa responds with ( ͡° ͜ʖ ͡°)",
                "$uwu · $u": "Herupa joins your voice channel and gets uwu.",
                "$kanye · $k": "Get a random Kanye West quote.",
                "$chucknorris {category} · $cn": "Get a random Chuck Norris joke.",
                "$pokemon {name} · $pk": "Look up info on a Pokémon.",
                "$poll · $pl": "Create a poll people can vote on.",
                "$herupasay {text} · $hs": "Herupa joins your voice channel and says the text.",
                "$avatarpic {@member} · $ap": "Show a member's avatar.",
            }),
            ("🔊 Voice & Rooms", {
                "$crpm": "Toggle privacy mode for your auto-created voice room.",
                "$migrate {channel id} · $m": "Move everyone in your voice channel to another one.",
                "$addfavorite {@member} · $af": "Favorite a member and get pinged when they join a VC (must be mutual).",
                "$removefavorite {@member} · $rf": "Remove a member from your favorites.",
                "$displayfavorites · $df": "Lists your favorites, then auto-deletes the message after a few seconds.",
            }),
            ("🛠️ Utility", {
                "$membercount · $mc": "Show the server's member and bot counts.",
                "$qrcode {data} · $qr": "Generate a QR code.",
                "$urlshorter {url} · $url": "Shorten a URL.",
                "$whoisinspace · $wiis": "See who's currently in space.",
                "$isslive": "Get a link to the ISS live stream.",
                "$ping · $p": "Check that Herupa is alive (pong!).",
                "$help · $h": "Show this help menu.",
            }),
            ("🔨 Moderation  (staff only)", {
                "$timeout {@member} {minutes} {reason} · $to":
                    "Mute a member.  **Deputy:** ≤ 60 min  •  **Sheriff+:** any duration.",
                "$kick {@member} {reason}":
                    "Kick a member.  **Deputy:** max 3 kicks+bans per hour, can't target staff  •  **Sheriff+:** unlimited.",
                "$ban {@member} {reason}":
                    "Ban a member.  **Deputy:** shares the same 3-per-hour pool  •  **Sheriff+:** unlimited.",
                "$clear {number} · $c": "Bulk-delete messages (default 5).",
                "$purgatory {@member} · $purg": "Send a member to purgatory.",
                "$rolepanel [single] {title} {@role...} · $rp":
                    "Post a self-assign role button panel. 'single' = picking one role swaps out the others.",
            }),
        ]

        backgroundTasks = {
            "AFK": "Herupa tracks how long members are AFK and moves them to the AFK channel.",
            "Newbie / ToS": "Assigns the newbie role to arrivals, then chillies once they accept the ToS.",
            "Greeter": "Greets each new member with a unique welcome.",
            "Logging": "Logs deleted messages and voice join/leave/switch events to the log channels.",
            "Clear Channel": "Clears certain text channels every day at 6:30am EST.",
            "Favorites": "Notifies your mutual favorites when you connect to a voice channel.",
            "Destroy Room": "Deletes an auto-created room when the last person leaves (backup sweep at 6:30am EST).",
        }

        # Page 0 is the landing page; pages 1..N are the categories.
        pages = [("Home", landing)] + categories
        cur_page = 0

        message = await ctx.send(embed=newEmbed(*pages[0]))
        for emoji in ["❓", "◀️", "▶️", "🤓"]:
            await message.add_reaction(emoji)

        while True:
            try:
                reaction, user = await self.client.wait_for("reaction_add", timeout=90, check=check)
                emoji = str(reaction.emoji)

                if emoji == "🤓":
                    await message.edit(embed=newEmbed("Background Tasks", backgroundTasks))
                else:
                    if emoji == "❓":
                        cur_page = 0
                    elif emoji == "▶️":
                        cur_page = (cur_page + 1) % len(pages)
                    elif emoji == "◀️":
                        cur_page = (cur_page - 1) % len(pages)
                    await message.edit(embed=newEmbed(*pages[cur_page]))

                await message.remove_reaction(reaction, user)

            except asyncio.TimeoutError:
                await message.delete()
                break


async def setup(client):
    await client.add_cog(Help(client))
