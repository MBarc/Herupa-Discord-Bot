'''
Purpose: A button-driven ticketing system, plus anonymous reports.

NORMAL TICKETS: a pinned panel (posted with $ticketpanel) shows one button per
team. Clicking one opens a PRIVATE channel, named
"<team emoji><opener's display name>", visible only to the opener and the
routed team. One open ticket per user per team (per server).

ANONYMOUS REPORTS: a member DMs Herupa `$whisper <message>` (DM-only) and picks
a team (and, if they share more than one configured server with Herupa, which
server it's for).
An anonymous ticket opens routed to that team, but the reporter is NOT given
access — they keep talking to the team through Herupa's DMs, which relays both
ways (staff messages -> reporter DMs; reporter DMs -> channel as "Reporter").
A `//` line in the channel is an internal note, not relayed. One open anonymous
ticket per user (a single shared DM channel). The reporter's identity is stored
only in Mongo for relay — never shown in the channel or the transcript.

Staff use $claim / $add / $close inside any ticket (or the Close button). On
close, a transcript is saved to the team's archive channel (or the ticket-logs
channel on the dedicated logging server if no archive channel is configured)
before the channel is deleted.

MULTI-SERVER: everything is driven by per-guild config in Mongo
(db "tickets", collection "config", one doc per guild_id):

    {
      "guild_id": "645847490020638720",
      "panel_manager_roles": ["head chill"],   # may post $ticketpanel (admins always can)
      "anon_enabled": True,
      "teams": [
        {"key": "tech", "label": "Tech Support", "emoji": "🤖", "style": "primary",
         "roles": ["techie manager", "techie"],  # see/reply/get pinged (case-insensitive)
         "colour": 0x1ABC9C,
         "blurb": "bots, integrations, game servers",   # panel embed line
         "category_id": None,       # channel category ID (preferred: survives renames)
         "category": None,          # channel category NAME fallback — if set and missing,
                                    #   Herupa creates it once (hidden) and leaves it in
                                    #   place; None -> panel's own category, falling back
                                    #   to any category named *ticket*
         "archive_channel": None},  # transcript channel NAME in the guild;
                                    #   None -> HerupaLogger "ticket" (logging server)
        ...
      ]
    }

Edit the config in Mongo, then `$ticketreload` (admin) to apply without a
restart. Guilds with no config doc get a polite "not set up" message.

Requires Herupa's role to have **Manage Channels** AND **Manage Roles**
(needed to set the private per-channel permission overwrites).
'''

import io
import sys
import os
import time

import discord
from discord.ext import commands

current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
sys.path.append(parent_dir)

from tools.HerupaMongo import HerupaMongo
from tools.HerupaLogger import HerupaLogger


BUTTON_STYLES = {
    "primary": discord.ButtonStyle.primary,
    "secondary": discord.ButtonStyle.secondary,
    "success": discord.ButtonStyle.success,
    "danger": discord.ButtonStyle.danger,
}


def _find_role(guild, name):
    """Role lookup by name, case-insensitive (config names may not match case)."""
    low = name.lower()
    return next((r for r in guild.roles if r.name.lower() == low), None)


class TicketPanelView(discord.ui.View):
    """Persistent panel with one button per configured team.

    custom_ids embed the guild + team key ("herupa_ticket:<guild_id>:<key>") so
    one registered view per guild keeps every server's panel buttons working
    across restarts."""

    def __init__(self, cog, guild_id, teams):
        super().__init__(timeout=None)
        self.cog = cog
        for team in teams:
            button = discord.ui.Button(
                label=team["label"], emoji=team.get("emoji"),
                style=BUTTON_STYLES.get(team.get("style"), discord.ButtonStyle.primary),
                custom_id=f"herupa_ticket:{guild_id}:{team['key']}")
            button.callback = self._make_callback(team["key"])
            self.add_item(button)

    def _make_callback(self, team_key):
        async def callback(interaction):
            await self.cog.create_ticket(interaction, team_key)
        return callback


class LegacyPanelView(discord.ui.View):
    """Keeps the pre-multi-server Chill Club panel message alive: its buttons
    were posted with fixed custom_ids, so those ids must stay registered."""

    def __init__(self, cog):
        super().__init__(timeout=None)
        self.cog = cog

    @discord.ui.button(label="Tech Support", emoji="🤖",
                       style=discord.ButtonStyle.primary, custom_id="herupa_ticket_tech")
    async def tech(self, interaction, button):
        await self.cog.create_ticket(interaction, "tech")

    @discord.ui.button(label="Moderation", emoji="👀",
                       style=discord.ButtonStyle.danger, custom_id="herupa_ticket_mod")
    async def mod(self, interaction, button):
        await self.cog.create_ticket(interaction, "mod")

    @discord.ui.button(label="Media", emoji="📸",
                       style=discord.ButtonStyle.secondary, custom_id="herupa_ticket_media")
    async def media(self, interaction, button):
        await self.cog.create_ticket(interaction, "media")


class CloseView(discord.ui.View):
    """Persistent Close button attached to every ticket's welcome message."""

    def __init__(self, cog):
        super().__init__(timeout=None)
        self.cog = cog

    @discord.ui.button(label="Close", emoji="🔒",
                       style=discord.ButtonStyle.danger, custom_id="herupa_ticket_close")
    async def close(self, interaction, button):
        await self.cog.close_from_interaction(interaction)


class AnonChoiceView(discord.ui.View):
    """Transient picker shown in the reporter's DMs after $whisper: one button
    per choice (used for both the server pick and the team pick)."""

    def __init__(self, choices, on_choose):
        # choices: list of (key, label, emoji, style) — emoji/style may be None.
        super().__init__(timeout=300)
        self.on_choose = on_choose
        self.message = None
        for key, label, emoji, style in choices:
            button = discord.ui.Button(
                label=label, emoji=emoji,
                style=BUTTON_STYLES.get(style, discord.ButtonStyle.secondary))
            button.callback = self._make_callback(key)
            self.add_item(button)

    def _make_callback(self, key):
        async def callback(interaction):
            await interaction.response.defer()
            for child in self.children:
                child.disabled = True
            try:
                await interaction.message.edit(view=self)
            except discord.HTTPException:
                pass
            self.stop()
            await self.on_choose(key)
        return callback

    async def on_timeout(self):
        for child in self.children:
            child.disabled = True
        if self.message is not None:
            try:
                await self.message.edit(
                    content="This selection timed out — DM `$whisper <message>` again to retry.", view=self)
            except discord.HTTPException:
                pass


class TicketSystem(commands.Cog):

    def __init__(self, client):
        self.client = client
        self.db = "tickets"
        self.col = "tickets"
        self.config_col = "config"
        self.mongo = HerupaMongo()
        self.log = HerupaLogger(client)  # transcript fallback: the dedicated logging server
        self._configs = {}  # guild_id (int) -> config doc
        # Anonymous-relay caches (channel_id <-> reporter user_id) so on_message
        # stays O(1). Kept in sync on create/close; rebuilt in cog_load.
        self._anon_ch2user = {}
        self._anon_user2ch = {}

    async def cog_load(self):
        self._load_configs()
        self._register_views()
        # Rebuild the anonymous-relay caches from any still-open anon tickets.
        self._anon_ch2user.clear()
        self._anon_user2ch.clear()
        for t in self._all_tickets():
            if t.get("anonymous") and t.get("status") == "open":
                try:
                    self._anon_link(int(t["channel_id"]), int(t["opener_id"]))
                except (KeyError, TypeError, ValueError):
                    pass
        # While a user has an open anonymous report, their DMs are reserved for it,
        # so block any other DM command for them (the text is relayed to the ticket).
        self.client.add_check(self._dm_locked_by_anon)

    async def cog_unload(self):
        self.client.remove_check(self._dm_locked_by_anon)

    async def _dm_locked_by_anon(self, ctx):
        if ctx.guild is None and ctx.author.id in self._anon_user2ch:
            return False
        return True

    # ------------------------- config -------------------------

    def _load_configs(self):
        self._configs = {}
        for doc in self.mongo.returnCollectionEntries(database_name=self.db,
                                                      collection_name=self.config_col):
            try:
                self._configs[int(doc["guild_id"])] = doc
            except (KeyError, TypeError, ValueError):
                pass

    def _register_views(self):
        # Re-adding a persistent view with the same custom_ids replaces the old
        # registration, so this is safe to call again from $ticketreload.
        for guild_id, conf in self._configs.items():
            if conf.get("teams"):
                self.client.add_view(TicketPanelView(self, guild_id, conf["teams"]))
        self.client.add_view(LegacyPanelView(self))
        self.client.add_view(CloseView(self))

    def _conf(self, guild_id):
        return self._configs.get(int(guild_id))

    def _team(self, guild_id, team_key):
        conf = self._conf(guild_id)
        if conf is None:
            return None
        return next((t for t in conf.get("teams", []) if t.get("key") == team_key), None)

    # ------------------------- data helpers -------------------------

    def _all_tickets(self):
        return self.mongo.returnCollectionEntries(database_name=self.db, collection_name=self.col)

    def _guild_tickets(self, guild_id):
        gid = str(guild_id)
        return [t for t in self._all_tickets() if t.get("guild_id") == gid]

    def _open_ticket_for(self, channel_id):
        for t in self._all_tickets():
            if t.get("channel_id") == str(channel_id) and t.get("status") == "open":
                return t
        return None

    def _staff_role_names(self, guild_id):
        conf = self._conf(guild_id)
        if conf is None:
            return set()
        names = {r.lower() for t in conf.get("teams", []) for r in t.get("roles", [])}
        names |= {r.lower() for r in conf.get("panel_manager_roles", [])}
        return names

    def _is_staff(self, member):
        names = {r.name.lower() for r in member.roles}
        return bool(names & self._staff_role_names(member.guild.id)) \
            or member.guild_permissions.administrator

    def _can_manage(self, member, ticket):
        return str(member.id) == ticket["opener_id"] or self._is_staff(member)

    async def _resolve_category(self, guild, team, panel_channel=None):
        """The team's configured category: by ID first (rename-proof), then by
        name; if the name is configured but missing it's created once (hidden)
        and left in place — never picked ad hoc. Teams with no configured
        category use the panel's own category, else any category whose name
        contains 'ticket'."""
        wanted_id = (team or {}).get("category_id")
        if wanted_id:
            cat = guild.get_channel(int(wanted_id))
            if isinstance(cat, discord.CategoryChannel):
                return cat
        wanted = (team or {}).get("category")
        if wanted:
            low = wanted.lower()
            cat = next((c for c in guild.categories if c.name.lower() == low), None)
            if cat is not None:
                return cat
            try:
                return await guild.create_category(
                    name=wanted,
                    overwrites={
                        guild.default_role: discord.PermissionOverwrite(view_channel=False),
                        guild.me: discord.PermissionOverwrite(
                            view_channel=True, send_messages=True, manage_channels=True),
                    },
                    reason="Ticket category from Herupa's ticket config",
                )
            except discord.Forbidden:
                return None
        if panel_channel is not None and getattr(panel_channel, "category", None) is not None:
            return panel_channel.category
        return next((c for c in guild.categories if "ticket" in c.name.lower()), None)

    # ------------------------- anonymous relay -------------------------

    def _anon_link(self, channel_id, user_id):
        self._anon_ch2user[int(channel_id)] = int(user_id)
        self._anon_user2ch[int(user_id)] = int(channel_id)

    def _anon_unlink(self, channel_id):
        uid = self._anon_ch2user.pop(int(channel_id), None)
        if uid is not None:
            self._anon_user2ch.pop(uid, None)

    def _prefixes(self):
        p = self.client.command_prefix
        if isinstance(p, str):
            return (p,)
        if isinstance(p, (list, tuple)):
            return tuple(x for x in p if isinstance(x, str)) or ("$",)
        return ("$",)

    async def _fetch_user(self, user_id):
        if not user_id:
            return None
        user = self.client.get_user(int(user_id))
        if user is not None:
            return user
        try:
            return await self.client.fetch_user(int(user_id))
        except discord.HTTPException:
            return None

    def _anon_candidate_guilds(self, user_id):
        """Configured, anon-enabled guilds the reporter is a member of."""
        out = []
        for guild_id, conf in self._configs.items():
            if not conf.get("anon_enabled", True) or not conf.get("teams"):
                continue
            guild = self.client.get_guild(guild_id)
            if guild is not None and guild.get_member(int(user_id)) is not None:
                out.append(guild)
        return out

    @commands.Cog.listener()
    async def on_message(self, message):
        if message.author.bot:
            return
        if isinstance(message.channel, discord.DMChannel):
            await self._handle_reporter_dm(message)
        elif message.channel.id in self._anon_ch2user:
            await self._handle_staff_reply(message)

    async def _handle_reporter_dm(self, message):
        # Starting a report is the $whisper command; this listener handles the
        # continuation: while a report is open, every DM goes to the ticket.
        open_ch = self._anon_user2ch.get(message.author.id)
        if not open_ch:
            return
        content = (message.content or "").strip()
        low = content.lower()
        for trigger in ("$whisper", "/whisper"):  # tolerate a re-typed command
            if low.startswith(trigger):
                content = content[len(trigger):].strip()
                break
        if content:
            await self._relay_to_channel(open_ch, content)
            await self._react_ok(message)

    async def _react_ok(self, message):
        try:
            await message.add_reaction("✅")
        except discord.HTTPException:
            pass

    async def _relay_to_channel(self, channel_id, text):
        channel = self.client.get_channel(int(channel_id))
        if channel is None:
            return
        embed = discord.Embed(description=f"🤫 **Reporter:** {text}", colour=0x95A5A6)
        await channel.send(embed=embed, allowed_mentions=discord.AllowedMentions.none())

    async def _handle_staff_reply(self, message):
        # Staff talking in an anon ticket -> relayed to the reporter's DMs.
        # A line starting with // is an internal note and is NOT relayed.
        content = (message.content or "").strip()
        if not content or content.startswith("//") or content.startswith(self._prefixes()):
            return
        user = await self._fetch_user(self._anon_ch2user.get(message.channel.id))
        if user is None:
            return
        try:
            await user.send(f"🛡️ **{message.author.display_name}:** {content}")
        except discord.Forbidden:
            try:
                await message.channel.send(
                    "⚠️ I couldn't deliver that to the reporter (their DMs are closed).")
            except discord.HTTPException:
                pass
        except discord.HTTPException:
            pass

    async def create_anon_ticket(self, user, content, guild, team_key):
        # One open anonymous ticket per user (a single shared DM channel).
        existing = self._anon_user2ch.get(user.id)
        if existing:
            await self._relay_to_channel(existing, content)
            try:
                await user.send("You already had an open report, so I added that to it.")
            except discord.HTTPException:
                pass
            return
        team = self._team(guild.id, team_key)
        if team is None:
            return
        category = await self._resolve_category(guild, team)
        if category is None:
            try:
                await user.send("Sorry, I couldn't find a server to file your report in right now.")
            except discord.HTTPException:
                pass
            return

        number = len(self._guild_tickets(guild.id)) + 1
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
            guild.me: discord.PermissionOverwrite(
                view_channel=True, send_messages=True, manage_channels=True, read_message_history=True),
        }
        team_roles = []
        for rname in team.get("roles", []):
            role = _find_role(guild, rname)
            if role:
                overwrites[role] = discord.PermissionOverwrite(
                    view_channel=True, send_messages=True, read_message_history=True)
                team_roles.append(role)

        try:
            channel = await guild.create_text_channel(
                name=f"🤫anon-{number:04d}",
                category=category,
                overwrites=overwrites,
                topic=f"Anonymous {team['label']} report #{number:04d} — messages here relay to the reporter via Herupa DMs.",
            )
        except discord.Forbidden:
            try:
                await user.send("I couldn't open your report (I'm missing permissions). Please contact a mod directly.")
            except discord.HTTPException:
                pass
            return

        self.mongo.addCollectionEntry(database_name=self.db, collection_name=self.col, payload={
            "number": number, "guild_id": str(guild.id), "channel_id": str(channel.id),
            "opener_id": str(user.id), "category": team_key, "anonymous": True,
            "claimed_by": None, "opened_at": int(time.time()), "status": "open",
        })
        self._anon_link(channel.id, user.id)

        ping = " ".join(r.mention for r in team_roles)
        embed = discord.Embed(
            title=f"🤫 Anonymous {team['label']} Report #{number:04d}",
            description=(f"An anonymous member submitted a report — **their identity is hidden.**\n\n"
                         f">>> {content}\n\n"
                         "Type here to reply — I relay messages to and from the reporter's DMs. "
                         "Start a line with `//` to keep it internal (not sent to them).\n"
                         "*Staff:* `$claim` · `$close [reason]` or the button below."),
            colour=team.get("colour", 0x95A5A6),
        )
        await channel.send(content=ping, embed=embed, view=CloseView(self),
                           allowed_mentions=discord.AllowedMentions(roles=True))
        try:
            await user.send(
                f"✅ Your anonymous **{team['label']}** report has been sent. "
                "Keep messaging me here and I'll pass it along — your name stays hidden.")
        except discord.HTTPException:
            pass

    # ------------------------- create -------------------------

    async def create_ticket(self, interaction, team_key):
        # ACK immediately so we never miss Discord's 3s response window, then work.
        try:
            await interaction.response.defer(ephemeral=True)
        except discord.HTTPException:
            pass
        # Buttons bypass the command pipeline, so honor $feature toggles here.
        fm = self.client.get_cog("FeatureManager")
        if fm is not None and not fm.is_enabled(interaction.guild_id, "tickets"):
            try:
                await interaction.followup.send(
                    "Tickets are turned off in this server right now.", ephemeral=True)
            except discord.HTTPException:
                pass
            return
        try:
            await self._create_ticket_inner(interaction, team_key)
        except Exception as ex:
            import traceback
            traceback.print_exc()
            try:
                await interaction.followup.send(
                    f"⚠️ Ticket creation failed: `{type(ex).__name__}: {ex}`", ephemeral=True)
            except discord.HTTPException:
                pass

    async def _create_ticket_inner(self, interaction, team_key):
        guild = interaction.guild
        opener = interaction.user
        team = self._team(guild.id, team_key)
        if team is None:
            await interaction.followup.send(
                "Tickets aren't set up for this server yet.", ephemeral=True)
            return

        # One open ticket per user per team (per server) — point them at the existing one.
        for t in self._guild_tickets(guild.id):
            if (t.get("opener_id") == str(opener.id) and t.get("category") == team_key
                    and t.get("status") == "open"):
                ch = guild.get_channel(int(t["channel_id"]))
                if ch:
                    await interaction.followup.send(
                        f"You already have an open {team['label']} ticket: {ch.mention}", ephemeral=True)
                    return

        category = await self._resolve_category(guild, team, panel_channel=interaction.channel)
        if category is None:
            await interaction.followup.send(
                "I couldn't find the tickets category. Ask an admin to run the panel "
                "inside the tickets category.", ephemeral=True)
            return

        number = len(self._guild_tickets(guild.id)) + 1

        overwrites = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
            guild.me: discord.PermissionOverwrite(
                view_channel=True, send_messages=True, manage_channels=True, read_message_history=True),
            opener: discord.PermissionOverwrite(
                view_channel=True, send_messages=True, read_message_history=True),
        }
        team_roles = []
        for rname in team.get("roles", []):
            role = _find_role(guild, rname)
            if role:
                overwrites[role] = discord.PermissionOverwrite(
                    view_channel=True, send_messages=True, read_message_history=True)
                team_roles.append(role)

        try:
            channel = await guild.create_text_channel(
                name=f"{team.get('emoji', '🎫')}{opener.display_name}",
                category=category,
                overwrites=overwrites,
                topic=f"{team['label']} ticket #{number:04d} opened by {opener} ({opener.id})",
            )
        except discord.Forbidden:
            await interaction.followup.send(
                "I couldn't open the ticket — I need the **Manage Roles** permission to create "
                "private channels. Please ask an admin to grant it.", ephemeral=True)
            return

        self.mongo.addCollectionEntry(database_name=self.db, collection_name=self.col, payload={
            "number": number, "guild_id": str(guild.id), "channel_id": str(channel.id),
            "opener_id": str(opener.id), "category": team_key, "claimed_by": None,
            "opened_at": int(time.time()), "status": "open",
        })

        ping = " ".join([opener.mention] + [r.mention for r in team_roles])
        embed = discord.Embed(
            title=f"{team.get('emoji', '🎫')} {team['label']} — Ticket #{number:04d}",
            description=(f"Thanks {opener.mention}, the **{team['label']}** team has been notified.\n"
                         "Describe your issue and someone will be with you shortly.\n\n"
                         "*Staff:* `$claim` to take it · `$add @user` to pull someone in · "
                         "`$close [reason]` or the button below to close."),
            colour=team.get("colour", 0x5865F2),
        )
        await channel.send(content=ping, embed=embed, view=CloseView(self),
                           allowed_mentions=discord.AllowedMentions(users=True, roles=True))
        await interaction.followup.send(f"Your ticket is open: {channel.mention}", ephemeral=True)

    # ------------------------- close -------------------------

    async def _save_transcript(self, channel, ticket, closer, reason):
        lines = []
        async for msg in channel.history(limit=1000, oldest_first=True):
            stamp = msg.created_at.strftime("%Y-%m-%d %H:%M")
            body = msg.content or ""
            for e in msg.embeds:
                body += f" [embed: {e.title}]"
            for a in msg.attachments:
                body += f" [attachment: {a.url}]"
            lines.append(f"[{stamp}] {msg.author}: {body}")
        text = "\n".join(lines) or "(no messages)"

        opener_str = "(anonymous)" if ticket.get("anonymous") else f"<@{ticket['opener_id']}>"
        header = (f"Server **{channel.guild.name}** · opened by {opener_str} · "
                  f"category **{ticket['category']}** · closed by {closer} · reason: {reason or 'n/a'}")
        embed = discord.Embed(title=f"🎫 Ticket #{ticket['number']:04d} closed",
                              description=header, colour=0x888888)
        buf = io.BytesIO(text.encode("utf-8"))
        transcript_file = discord.File(buf, filename=f"ticket-{ticket['number']:04d}.txt")

        # Transcript -> the team's archive channel in this guild if configured,
        # else ticket-logs on the dedicated logging server (no-op if unavailable).
        team = self._team(channel.guild.id, ticket.get("category"))
        archive_name = (team or {}).get("archive_channel")
        archive = None
        if archive_name:
            low = archive_name.lower()
            archive = next((c for c in channel.guild.text_channels if c.name.lower() == low), None)
        if archive is not None:
            try:
                await archive.send(embed=embed, file=transcript_file,
                                   allowed_mentions=discord.AllowedMentions.none())
            except discord.HTTPException:
                pass
        else:
            await self.log.send("ticket", embed=embed, file=transcript_file)
        return text

    # A transcript this size or smaller fits comfortably in one embed
    # (description cap is 4096); anything bigger goes as a .txt file.
    TRANSCRIPT_EMBED_LIMIT = 3500

    async def _dm_transcript(self, user, guild_name, ticket, text, intro):
        """DM the closed ticket's transcript to its opener: short conversations
        inline as an embed, long ones as the same .txt file the logs get."""
        try:
            if len(text) <= self.TRANSCRIPT_EMBED_LIMIT:
                embed = discord.Embed(
                    title=f"🎫 Ticket #{ticket['number']:04d} transcript",
                    description=text, colour=0xFFB7C5)
                await user.send(intro, embed=embed)
            else:
                buf = io.BytesIO(text.encode("utf-8"))
                await user.send(intro, file=discord.File(
                    buf, filename=f"ticket-{ticket['number']:04d}.txt"))
        except discord.HTTPException:
            pass  # their DMs are closed; the logs still have the transcript

    async def _do_close(self, channel, closer, reason):
        ticket = self._open_ticket_for(channel.id)
        if not ticket:
            return
        transcript = await self._save_transcript(channel, ticket, closer, reason)
        self.mongo.updateDocumentsByKey(database_name=self.db, collection_name=self.col,
                                        IDkey="channel_id", IDvalue=str(channel.id),
                                        key="status", value="closed")
        guild_name = channel.guild.name
        if ticket.get("anonymous"):
            user = await self._fetch_user(self._anon_ch2user.get(channel.id))
            self._anon_unlink(channel.id)
            intro = (f"🔒 Your anonymous report over at **{guild_name}** was closed "
                     f"out by the team. Thanks for reaching out. Here is the transcript:")
        else:
            user = await self._fetch_user(ticket.get("opener_id"))
            intro = (f"🔒 Your ticket over at **{guild_name}** was closed out. "
                     f"Here is the transcript:")
        if user is not None:
            await self._dm_transcript(user, guild_name, ticket, transcript, intro)
        await channel.delete(reason=f"Ticket closed by {closer}: {reason or 'n/a'}")

    async def close_from_interaction(self, interaction):
        # ACK immediately so we never miss Discord's 3s window, then work.
        try:
            await interaction.response.defer(ephemeral=True)
        except discord.HTTPException:
            pass
        try:
            ticket = self._open_ticket_for(interaction.channel.id)
            if not ticket:
                await interaction.followup.send("This isn't an open ticket channel.", ephemeral=True)
                return
            if not self._can_manage(interaction.user, ticket):
                await interaction.followup.send(
                    "Only the ticket opener or staff can close this.", ephemeral=True)
                return
            await interaction.followup.send("Closing this ticket…", ephemeral=True)
            await self._do_close(interaction.channel, interaction.user, "Closed via button")
        except Exception as ex:
            import traceback
            traceback.print_exc()
            try:
                await interaction.followup.send(
                    f"⚠️ Close failed: `{type(ex).__name__}: {ex}`", ephemeral=True)
            except discord.HTTPException:
                pass

    # ------------------------- commands -------------------------

    def _may_post_panel(self, member):
        if member.guild_permissions.administrator:
            return True
        conf = self._conf(member.guild.id)
        if conf is None:
            return False
        allowed = {r.lower() for r in conf.get("panel_manager_roles", [])}
        return any(r.name.lower() in allowed for r in member.roles)

    @commands.command(name="ticketpanel", aliases=["tpanel"])
    @commands.guild_only()
    async def ticketpanel(self, ctx):
        """Post the ticket panel in this channel (admin / panel managers only)."""
        conf = self._conf(ctx.guild.id)
        if conf is None or not conf.get("teams"):
            await ctx.send("Tickets aren't set up for this server yet.")
            return
        if not self._may_post_panel(ctx.author):
            await ctx.send("Only an admin can post the ticket panel.")
            return
        lines = ["Need a hand? Pick the team that fits and we'll open a private channel just for you.\n"]
        for team in conf["teams"]:
            lines.append(f"{team.get('emoji', '🎫')} **{team['label']}** — {team.get('blurb', '')}")
        lines.append("\nYour ticket will be visible only to you and the team you choose.")
        if conf.get("anon_enabled", True):
            lines.append(
                "\n🤫 **Want to stay anonymous?** Instead of opening a ticket, **DM me** "
                "`$whisper <your message>`. I'll ask which team it should go to and open an "
                "anonymous ticket — your name stays hidden and you chat with the team right here in DMs.")
        embed = discord.Embed(title="🎫 Open a Ticket", description="\n".join(lines), colour=0x5865F2)
        panel = await ctx.send(embed=embed, view=TicketPanelView(self, ctx.guild.id, conf["teams"]))
        try:
            await panel.pin()
        except discord.HTTPException:
            pass
        try:
            await ctx.message.delete()
        except discord.HTTPException:
            pass

    @commands.command(name="ticketreload")
    @commands.has_guild_permissions(administrator=True)
    async def ticketreload(self, ctx):
        """Re-read the ticket configs from Mongo and re-register the panel views."""
        self._load_configs()
        self._register_views()
        await ctx.send(f"🎫 Reloaded ticket config for {len(self._configs)} server(s).")

    @commands.command(name="whisper")
    async def whisper(self, ctx, *, message: str = None):
        """Send an anonymous report to a team. DM-only."""
        if ctx.guild is not None:
            # A $whisper in a public channel isn't anonymous — remove it and redirect to DMs.
            try:
                await ctx.message.delete()
            except discord.HTTPException:
                pass
            try:
                await ctx.author.send("To report anonymously, DM me `$whisper <your message>` right here.")
            except discord.HTTPException:
                pass
            return
        if not message or not message.strip():
            await ctx.send("Usage: `$whisper <your message>` — include what you'd like the team to know.")
            return
        # (If they already have an open report, the global DM lock blocks this and
        #  the message is relayed instead — see _dm_locked_by_anon / _handle_reporter_dm.)
        guilds = self._anon_candidate_guilds(ctx.author.id)
        if not guilds:
            await ctx.send("Sorry, I couldn't find a server to file your report in right now.")
            return
        content = message.strip()
        if len(guilds) == 1:
            await self._ask_anon_team(ctx, guilds[0], content)
        else:
            # The reporter is in more than one configured server — ask which one first.
            async def chose_guild(guild_id):
                guild = self.client.get_guild(int(guild_id))
                if guild is not None:
                    await self._ask_anon_team(ctx, guild, content)
            view = AnonChoiceView(
                [(str(g.id), g.name, None, "secondary") for g in guilds], chose_guild)
            view.message = await ctx.send(
                "🤫 Which server is your anonymous report about?", view=view)

    async def _ask_anon_team(self, ctx, guild, content):
        conf = self._conf(guild.id)

        async def chose_team(team_key):
            await self.create_anon_ticket(ctx.author, content, guild, team_key)

        view = AnonChoiceView(
            [(t["key"], t["label"], t.get("emoji"), t.get("style")) for t in conf.get("teams", [])],
            chose_team)
        view.message = await ctx.send(
            "🤫 Which team should receive your anonymous report?", view=view)

    @commands.command(name="close")
    async def close(self, ctx, *, reason: str = None):
        ticket = self._open_ticket_for(ctx.channel.id)
        if not ticket:
            await ctx.send("This isn't an open ticket channel.")
            return
        if not self._can_manage(ctx.author, ticket):
            await ctx.send("Only the ticket opener or staff can close this.")
            return
        await ctx.send("Closing this ticket…")
        await self._do_close(ctx.channel, ctx.author, reason or "No reason given")

    @commands.command(name="claim")
    async def claim(self, ctx):
        ticket = self._open_ticket_for(ctx.channel.id)
        if not ticket:
            await ctx.send("This isn't an open ticket channel.")
            return
        if not self._is_staff(ctx.author):
            await ctx.send("Only staff can claim tickets.")
            return
        self.mongo.updateDocumentsByKey(database_name=self.db, collection_name=self.col,
                                        IDkey="channel_id", IDvalue=str(ctx.channel.id),
                                        key="claimed_by", value=str(ctx.author.id))
        await ctx.send(f"🙋 {ctx.author.mention} has claimed this ticket.")
        if ticket.get("anonymous"):
            user = await self._fetch_user(self._anon_ch2user.get(ctx.channel.id))
            if user is not None:
                try:
                    await user.send("🙋 A moderator is now looking into your report.")
                except discord.HTTPException:
                    pass

    @commands.command(name="ticketadd", aliases=["add"])
    async def ticketadd(self, ctx, member: discord.Member):
        ticket = self._open_ticket_for(ctx.channel.id)
        if not ticket:
            await ctx.send("This isn't an open ticket channel.")
            return
        if not self._is_staff(ctx.author):
            await ctx.send("Only staff can add people to a ticket.")
            return
        try:
            await ctx.channel.set_permissions(
                member, view_channel=True, send_messages=True, read_message_history=True)
        except discord.Forbidden:
            await ctx.send("I need the **Manage Roles** permission to add people to tickets.")
            return
        await ctx.send(f"Added {member.mention} to the ticket.")

    @ticketadd.error
    async def ticketadd_error(self, ctx, error):
        if isinstance(error, commands.MissingRequiredArgument):
            await ctx.send("Usage: $add <@member>")
        elif isinstance(error, commands.BadArgument):
            await ctx.send("Could not find that member.")


async def setup(client):
    await client.add_cog(TicketSystem(client))
