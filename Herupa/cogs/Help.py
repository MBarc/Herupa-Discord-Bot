
import discord
from discord.ext import commands

import asyncio
import sys
import os

current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
sys.path.append(parent_dir)

from tools.HerupaMongo import HerupaMongo


class Help(commands.Cog):
    '''$help menu. Per-guild visibility comes from Mongo (db "help",
    collection "config", one doc per guild_id):

        {"guild_id": "...",
         "sections": ["fun", "voice", "utility", "tickets"],  # member pages to show
         "hide_commands": ["$mock", "$daily"],   # entries to drop from any page
         "background": ["Invite Tracking"]}      # background-task names to show

    No doc (or missing key) means show everything, so Chill Club needs no
    config. Staff pages always show to staff, minus hide_commands.'''

    def __init__(self, client):
        self.client = client
        self.mongo = HerupaMongo()

    def _help_conf(self, guild_id):
        if guild_id is None:
            return {}
        gid = str(guild_id)
        for doc in self.mongo.returnCollectionEntries(database_name="help",
                                                      collection_name="config"):
            if doc.get("guild_id") == gid:
                return doc
        return {}

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
        # Mod status comes from the per-server moderation config, so ask the cog.
        mod_cog = ctx.bot.get_cog("DeputyModeration")
        if mod_cog is not None and ctx.guild is not None:
            is_mod = mod_cog.is_mod(ctx.author)
        else:
            is_mod = bool(author_roles & {"head chill", "sheriff", "deputy"})
        # Ticket staff is defined by the per-server ticket config, so ask the cog.
        ticket_cog = ctx.bot.get_cog("TicketSystem")
        if ticket_cog is not None and ctx.guild is not None:
            is_ticket_staff = ticket_cog._is_staff(ctx.author)
        else:
            is_ticket_staff = is_mod

        categories = [
            ("fun", "🎉 Fun & Novelty", {
                "$lenny · $l": "Herupa responds with ( ͡° ͜ʖ ͡°)",
                "$uwu · $u": "Herupa joins your voice channel and gets uwu.",
                "$chucknorris {category} · $cn": "Get a random Chuck Norris joke.",
                "$pokemon {name} · $pk": "Look up info on a Pokémon.",
                "$poll · $pl": "Create a poll people can vote on.",
                "$herupasay {text} · $hs": "Herupa joins your voice channel and says the text.",
                "$mock": "Points you at the shop's mock item ($buy mock @member).",
                "$birthday {date} · $bday": "Save your birthday (e.g. $birthday March 5); Herupa wishes you in general chat and it shows on the calendar.",
                "$birthdays · $bdays": "See upcoming birthdays.",
                "$avatarpic {@member} · $ap": "Show a member's avatar.",
            }),
            ("voice", "🔊 Voice & Rooms", {
                "$crpm": "Toggle privacy mode for your auto-created voice room.",
                "$migrate {channel id} · $m": "Move everyone in your voice channel to another one.",
                "$addfavorite {@member} · $af": "Favorite a member and get pinged when they join a VC (must be mutual).",
                "$removefavorite {name/ID/number} · $rf": "Remove a favorite by name, user ID, or their number in $displayfavorites, so you never have to ping them.",
                "$displayfavorites · $df": "See your list of favorites.",
            }),
            ("music", "🎶 Music", {
                "$music {song or link} · $play": "Summon a free Hibiki DJ to your voice channel and play a song (searches YouTube).",
                "$skip": "Skip the current song.",
                "$pause / $resume": "Pause or resume playback.",
                "$queue · $q": "See what's playing and what's up next in your channel.",
                "$np": "Show the current song.",
                "$stop": "Clear the queue and send the DJ home.",
            }),
            ("utility", "🛠️ Utility", {
                "$membercount · $mc": "Show the server's member and bot counts.",
                "$qrcode {data} · $qr": "Generate a QR code.",
                "$whoisinspace · $wiis": "See who's currently in space.",
                "$isslive": "Get a link to the ISS live stream.",
                "$invitedby {@member}": "See who invited a member (defaults to you).",
                "$invites {@member} · $invited": "See who a member has invited (defaults to you).",
                "$leaderboard {stat} · $lb": "Top members by voice time, invites, AFK time, or messages (monthly and all-time).",
                "$rank {@member} · $level": "See your level, XP, and progress to the next level (defaults to you).",
                "$daily": "Claim 100 XP once a day. Streaks boost it: 2x at 3 days, 3x at 5, 5x at 10.",
                "$link": "Link a game account to your Discord. Bare $link walks you through it ($link roblox builderman also works).",
                "$verify": "Finish a pending link by completing its proof step (Roblox: the code in your profile's About section).",
                "$unlink": "Remove a linked game account. Bare $unlink lets you pick from a list.",
                "$ping · $p": "Check that Herupa is alive (pong!).",
                "$help · $h": "Show this help menu.",
            }),
            ("shop", "🛒 Level Shop", {
                "$shop": "Browse rewards you can buy by spending your levels.",
                "$buy color {name}": "Equip a name color (2 levels). Colors: Pink, Red, Orange, Gold, Green, Teal, Blue, Purple.",
                "$removecolor · $uncolor": "Take off your name color for free.",
                "$buy title {name}": "Buy a vanity title: Certified Chiller (3), Chill Veteran (5), Big Spender (5).",
                "$buy roomname {name}": "Give your auto-created voice room a custom name (3 levels).",
                "$buy nickname {@member} {name}": "Change someone's nickname as a prank (3 levels). Not staff or bots.",
                "$buy mock {@member}": "Herupa repeats everything they say in your voice channel for a minute (5 levels). Running away only delays it.",
            }),
            ("projects", "🗂️ Projects", {
                "🗂️ New task": "Make a post in a project forum and I'll track it as a task.",
                "$task {title}": "Create a task from anywhere (use $task {project} | {title} if there are several projects).",
                "$assign {@member}": "In a task's thread: route the task (bare $assign takes it yourself).",
                "$due {when}": "Set the due date: friday, tomorrow, 8/15, in 3 days, or none to clear.",
                "$priority {level}": "low, normal, high, or urgent (urgent gets a 🔥 tag).",
                "$status {stage}": "todo, doing, review, or done.",
                "$done": "Finish the task: tags it ✅ and archives the thread.",
                "$mytasks": "Your open tasks, soonest due first.",
                "$board": "Every project's task counts at a glance.",
            }),
            ("tickets", "🎫 Tickets & Reports", {
                "🎫 Open a ticket": "Click a button on the ticket panel to open a private ticket with the right team.",
                "$whisper {message}": "DM me this to send an anonymous report to staff. Your identity stays hidden, and you chat with the team through my DMs.",
            }),
        ]

        if is_mod:
            categories.append(("modstaff", "🔨 Moderation  (staff)", {
                "$timeout {@member} {minutes} {reason} · $to":
                    "Mute a member.  **Junior mods:** ≤ 60 min  •  **Senior staff:** any duration.",
                "$kick {@member} {reason}":
                    "Kick a member.  **Junior mods:** max 3 kicks+bans per hour, can't target staff  •  **Senior staff:** unlimited.",
                "$ban {@member} {reason}":
                    "Ban a member.  **Junior mods:** shares the same 3-per-hour pool  •  **Senior staff:** unlimited.",
                "$lookup {@member}": "See the game accounts a member has linked.",
                "$clear {number} · $c": "Bulk-delete messages (default 5).",
                "$purgatory {@member} · $purg": "Send a member to purgatory.",
                "$rolepanel [single] {title} {@role...} · $rp":
                    "Post a self-assign role button panel. 'single' = picking one role swaps out the others.",
            }))

        if is_ticket_staff:
            categories.append(("ticketstaff", "🎫 Ticket Staff", {
                "$ticketpanel · $tpanel": "Post the ticket panel in the current channel.",
                "$claim": "Claim the current ticket so members know who is handling it.",
                "$ticketadd {@member} · $add": "Add a member to the current ticket.",
                "$close": "Close the current ticket and save a transcript.",
            }))

        # Admin page: feature toggles + config reloads, for owner/admin/bot managers.
        fm = ctx.bot.get_cog("FeatureManager")
        if fm is not None and ctx.guild is not None and fm.is_manager(ctx.author):
            categories.append(("admin", "⚙️ Server Admin  (staff)", {
                "$feature": "See Herupa's features and whether they're on in this server.",
                "$feature off {name} / on {name}": "Turn one of Herupa's features off or on here.",
                "$project create": "Create a project forum whose posts I track as tasks (opens a form; a name after 'create' skips it).",
                "$project delete": "Pick a project from a list and delete it, forum and task records included (asks for confirmation).",
                "$project digest": "Send the morning project digest to the current channel ($project digest off stops it).",
                "$mcroles": "Map Discord roles to Minecraft (LuckPerms) groups for linked members ($mcroles set/remove works inline).",
                "$mcbridge": "Choose the channel the Minecraft chat bridge lives in ($mcbridge here / #channel / off).",
                "$ticketreload": "Re-read the ticket config after editing it in Mongo.",
                "$roomreload": "Re-read the rooms config after editing it in Mongo.",
            }))

        # Per-guild visibility, two layers:
        #   1. $feature toggles hide anything belonging to a disabled feature.
        #   2. The help config filters member pages / commands / background rows.
        # Staff pages always show to staff; pages that end up empty are dropped.
        SECTION_FEATURE = {"music": "music", "shop": "leveling",
                           "tickets": "tickets", "ticketstaff": "tickets",
                           "modstaff": "moderation", "projects": "projects"}
        COMMAND_FEATURE = {
            "$crpm": "rooms",
            "$rank {@member} · $level": "leveling", "$daily": "leveling",
            "$leaderboard {stat} · $lb": "leveling", "$mock": "leveling",
            "$birthday {date} · $bday": "birthdays", "$birthdays · $bdays": "birthdays",
            "$link": "accounts", "$verify": "accounts",
            "$unlink": "accounts", "$lookup {@member}": "accounts",
            "$addfavorite {@member} · $af": "favorites",
            "$removefavorite {name/ID/number} · $rf": "favorites",
            "$displayfavorites · $df": "favorites",
        }

        def feature_on(name):
            return (name is None or fm is None or ctx.guild is None
                    or fm.is_enabled(ctx.guild.id, name))

        help_conf = self._help_conf(ctx.guild.id if ctx.guild else None)
        sections = help_conf.get("sections")
        hidden = set(help_conf.get("hide_commands", []))
        # Sections a guild reserves for staff eyes (config "staff_sections").
        staff_only = set(help_conf.get("staff_sections", []))
        is_staff_viewer = (is_mod or is_ticket_staff
                           or (fm is not None and ctx.guild is not None
                               and fm.is_manager(ctx.author)))
        STAFF_KEYS = {"modstaff", "ticketstaff", "admin"}
        filtered = []
        for key, title, cmds in categories:
            if not feature_on(SECTION_FEATURE.get(key)):
                continue
            if key in staff_only and not is_staff_viewer:
                continue
            if sections is not None and key not in STAFF_KEYS and key not in sections:
                continue
            cmds = {k: v for k, v in cmds.items()
                    if k not in hidden and feature_on(COMMAND_FEATURE.get(k))}
            if cmds:
                filtered.append((title, cmds))
        categories = filtered

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
        TASK_FEATURE = {"Activity Stats": "leveling", "Welcome Rewards": "leveling",
                        "Hibiki DJ Crew": "music", "Favorites": "favorites",
                        "Destroy Room": "rooms", "Counting": "counting"}
        backgroundTasks = {k: v for k, v in backgroundTasks.items()
                           if feature_on(TASK_FEATURE.get(k))}
        shown_tasks = help_conf.get("background")
        if shown_tasks is not None:
            backgroundTasks = {k: v for k, v in backgroundTasks.items() if k in shown_tasks}

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
