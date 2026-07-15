
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

        # Only show staff pages to staff, so members see just what they can use.
        # Deputies don't have native Discord mod perms (moderation runs through
        # Herupa), so staff is detected by role, not by permission.
        author_roles = {r.name.lower() for r in getattr(ctx.author, "roles", [])}
        is_mod = bool(author_roles & {"head chill", "sheriff", "deputy"})
        is_ticket_staff = bool(author_roles & {
            "head chill", "sheriff", "deputy",
            "techie manager", "techie", "media manager", "media"})

        categories = [
            ("🎉 Fun & Novelty", {
                "$lenny · $l": "Herupa responds with ( ͡° ͜ʖ ͡°)",
                "$uwu · $u": "Herupa joins your voice channel and gets uwu.",
                "$kanye · $k": "Get a random Kanye West quote.",
                "$chucknorris {category} · $cn": "Get a random Chuck Norris joke.",
                "$pokemon {name} · $pk": "Look up info on a Pokémon.",
                "$poll · $pl": "Create a poll people can vote on.",
                "$herupasay {text} · $hs": "Herupa joins your voice channel and says the text.",
                "$mock": "Points you at the shop's mock item ($buy mock @member).",
                "$avatarpic {@member} · $ap": "Show a member's avatar.",
            }),
            ("🔊 Voice & Rooms", {
                "$crpm": "Toggle privacy mode for your auto-created voice room.",
                "$migrate {channel id} · $m": "Move everyone in your voice channel to another one.",
                "$addfavorite {@member} · $af": "Favorite a member and get pinged when they join a VC (must be mutual).",
                "$removefavorite {@member} · $rf": "Remove a member from your favorites.",
                "$displayfavorites · $df": "See your list of favorites.",
            }),
            ("🎶 Music", {
                "$music {song or link} · $play": "Summon a free Hibiki DJ to your voice channel and play a song (searches YouTube).",
                "$skip": "Skip the current song.",
                "$pause / $resume": "Pause or resume playback.",
                "$queue · $q": "See what's playing and what's up next in your channel.",
                "$np": "Show the current song.",
                "$stop": "Clear the queue and send the DJ home.",
            }),
            ("🛠️ Utility", {
                "$membercount · $mc": "Show the server's member and bot counts.",
                "$qrcode {data} · $qr": "Generate a QR code.",
                "$whoisinspace · $wiis": "See who's currently in space.",
                "$isslive": "Get a link to the ISS live stream.",
                "$invitedby {@member}": "See who invited a member (defaults to you).",
                "$invites {@member} · $invited": "See who a member has invited (defaults to you).",
                "$leaderboard {stat} · $lb": "Top members by voice time, invites, AFK time, or messages (monthly and all-time).",
                "$rank {@member} · $level": "See your level, XP, and progress to the next level (defaults to you).",
                "$daily": "Claim 100 XP once a day. Streaks boost it: 2x at 3 days, 3x at 5, 5x at 10.",
                "$ping · $p": "Check that Herupa is alive (pong!).",
                "$help · $h": "Show this help menu.",
            }),
            ("🛒 Level Shop", {
                "$shop": "Browse rewards you can buy by spending your levels.",
                "$buy color {name}": "Equip a name color (2 levels). Colors: Pink, Red, Orange, Gold, Green, Teal, Blue, Purple.",
                "$removecolor · $uncolor": "Take off your name color for free.",
                "$buy title {name}": "Buy a vanity title: Certified Chiller (3), Chill Veteran (5), Big Spender (5).",
                "$buy roomname {name}": "Give your auto-created voice room a custom name (3 levels).",
                "$buy nickname {@member} {name}": "Change someone's nickname as a prank (3 levels). Not staff or bots.",
                "$buy mock {@member}": "Herupa repeats everything they say in your voice channel for a minute (5 levels). Running away only delays it.",
            }),
            ("🎫 Tickets & Reports", {
                "🎫 Open a ticket": "Click a button in the create-a-ticket channel to open a private ticket with staff (support, moderation, or media).",
                "$whisper {message}": "DM me this to send an anonymous report to staff. Your identity stays hidden, and you chat with the team through my DMs.",
            }),
        ]

        if is_mod:
            categories.append(("🔨 Moderation  (staff)", {
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
            }))

        if is_ticket_staff:
            categories.append(("🎫 Ticket Staff", {
                "$ticketpanel · $tpanel": "Post the ticket panel in the current channel.",
                "$claim": "Claim the current ticket so members know who is handling it.",
                "$ticketadd {@member} · $add": "Add a member to the current ticket.",
                "$close": "Close the current ticket and save a transcript.",
            }))

        backgroundTasks = {
            "Activity Stats": "Tracks voice time, AFK time, and messages sent for the leaderboards (see $lb).",
            "Newbie / ToS": "Assigns the newbie role to arrivals, then chillies once they accept the ToS.",
            "Welcome Rewards": "Earn bonus XP for welcoming new members — reply to their join message in general-chat (tap \"Wave to say hi 👋\").",
            "Logging": "Logs deleted messages and voice join/leave/switch events to the log channels.",
            "Invite Tracking": "Records who invited each new member and keeps each inviter's running total.",
            "Bump Reminder": "Nudges the bump squad to /bump only after a few days with no bump, and gives bumpers bonus XP. Grab the role in self-assign.",
            "Counting": "Runs the counting game in the counting channel.",
            "Voice Auto-Leave": "Leaves a voice channel when no people are left, and after 10 minutes with no activity.",
            "Hibiki DJ Crew": "Red, Green, and Blue Hibiki play music in voice channels. Whoever is free answers $music, and they head home when idle or alone.",
            "Clear Channel": "Clears certain text channels every day at 6:30am EST.",
            "Favorites": "Notifies your mutual favorites when you connect to a voice channel.",
            "Destroy Room": "Deletes an auto-created room when the last person leaves (backup sweep at 6:30am EST).",
        }

        # Page 0 is the landing page; pages 1..N are the categories (staff pages
        # only present for staff).
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
