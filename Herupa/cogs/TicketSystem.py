'''
Purpose: A button-driven ticketing system, plus anonymous reports.

NORMAL TICKETS: a pinned panel (posted with $ticketpanel, run inside the
create-a-ticket channel) shows three buttons. Clicking one opens a PRIVATE
channel in the SAME category as the panel (the tickets category), named
"<team emoji><opener's display name>", visible only to the opener and the
routed team. One open ticket per user per team.

ANONYMOUS REPORTS: a member DMs Herupa `$whisper <message>` (DM-only) and picks
a team.
An anonymous ticket opens under the tickets category, routed to that team, but
the reporter is NOT given access — they keep talking to the team through
Herupa's DMs, which relays both ways (staff messages -> reporter DMs; reporter
DMs -> channel as "Reporter"). A `//` line in the channel is an internal note,
not relayed. One open anonymous ticket per user (a single shared DM channel).
The reporter's identity is stored only in Mongo for relay — never shown in the
channel or the transcript.

Staff use $claim / $add / $close inside any ticket (or the Close button). On
close, a transcript is saved to the ticket-logs channel on the dedicated
logging server (see tools/HerupaLogger) before the channel is deleted.

Requires Herupa's role to have **Manage Channels** (it does) AND **Manage
Roles** (needed to set the private per-channel permission overwrites).
Single-server build for Chill Club — role names are hardcoded below.
'''

import io
import sys
import os
import time

import discord
from discord.ext import commands
from discord.utils import get

current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
sys.path.append(parent_dir)

from tools.HerupaMongo import HerupaMongo
from tools.HerupaLogger import HerupaLogger


# --- Routing config: button -> {team roles, label, look} ---------------------
# Emoji match the per-team channels in the tickets category (🤖support🤖,
# 👀moderation👀, 📸media📸) and are used to prefix each ticket channel's name.
CATEGORIES = {
    "tech": {"label": "Tech Support", "emoji": "🤖",
             "roles": ["techie manager", "techie"], "colour": 0x1ABC9C},
    "mod": {"label": "Moderation", "emoji": "👀",
            "roles": ["head chill", "sheriff", "deputy"], "colour": 0xE74C3C},
    "media": {"label": "Media", "emoji": "📸",
              "roles": ["media manager", "media"], "colour": 0x9B59B6},
}
# Any of these roles (plus the opener and admins) may claim/add/close.
ALL_STAFF = {r.lower() for c in CATEGORIES.values() for r in c["roles"]}


class TicketPanelView(discord.ui.View):
    """Persistent panel with one button per team."""

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


class AnonTeamView(discord.ui.View):
    """Transient team picker shown in the reporter's DMs after $whisper."""

    def __init__(self, cog, user, content):
        super().__init__(timeout=300)
        self.cog = cog
        self.user = user
        self.content = content
        self.message = None

    async def _choose(self, interaction, key):
        await interaction.response.defer()
        for child in self.children:
            child.disabled = True
        try:
            await interaction.message.edit(content="🤫 Report sent — thank you.", view=self)
        except discord.HTTPException:
            pass
        self.stop()
        await self.cog.create_anon_ticket(self.user, self.content, key)

    @discord.ui.button(label="Tech Support", emoji="🤖", style=discord.ButtonStyle.primary)
    async def tech(self, interaction, button):
        await self._choose(interaction, "tech")

    @discord.ui.button(label="Moderation", emoji="👀", style=discord.ButtonStyle.danger)
    async def mod(self, interaction, button):
        await self._choose(interaction, "mod")

    @discord.ui.button(label="Media", emoji="📸", style=discord.ButtonStyle.secondary)
    async def media(self, interaction, button):
        await self._choose(interaction, "media")

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
        self.mongo = HerupaMongo()
        self.log = HerupaLogger(client)  # transcripts go to the dedicated logging server
        # Anonymous-relay caches (channel_id <-> reporter user_id) so on_message
        # stays O(1). Kept in sync on create/close; rebuilt in cog_load.
        self._anon_ch2user = {}
        self._anon_user2ch = {}

    async def cog_load(self):
        # Re-register the persistent views so buttons keep working after a restart.
        self.client.add_view(TicketPanelView(self))
        self.client.add_view(CloseView(self))
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

    # ------------------------- data helpers -------------------------

    def _all_tickets(self):
        return self.mongo.returnCollectionEntries(database_name=self.db, collection_name=self.col)

    def _open_ticket_for(self, channel_id):
        for t in self._all_tickets():
            if t.get("channel_id") == str(channel_id) and t.get("status") == "open":
                return t
        return None

    def _is_staff(self, member):
        names = {r.name.lower() for r in member.roles}
        return bool(names & ALL_STAFF) or member.guild_permissions.administrator

    def _can_manage(self, member, ticket):
        return str(member.id) == ticket["opener_id"] or self._is_staff(member)

    def _ticket_category(self, interaction):
        """Open tickets in the same category the panel lives in (the tickets
        category). Fall back to any category whose name contains 'ticket'."""
        ch = interaction.channel
        if ch is not None and getattr(ch, "category", None) is not None:
            return ch.category
        for cat in interaction.guild.categories:
            if "ticket" in cat.name.lower():
                return cat
        return None

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

    def _guild_category_for_reporter(self, user_id):
        """Pick a guild the reporter shares with the bot that has a tickets
        category, preferring one they're actually a member of."""
        fallback = None
        for guild in self.client.guilds:
            category = next((c for c in guild.categories if "ticket" in c.name.lower()), None)
            if category is None:
                continue
            if guild.get_member(int(user_id)) is not None:
                return guild, category
            if fallback is None:
                fallback = (guild, category)
        return fallback if fallback else (None, None)

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

    async def create_anon_ticket(self, user, content, category_key):
        # One open anonymous ticket per user (a single shared DM channel).
        existing = self._anon_user2ch.get(user.id)
        if existing:
            await self._relay_to_channel(existing, content)
            try:
                await user.send("You already had an open report, so I added that to it.")
            except discord.HTTPException:
                pass
            return
        conf = CATEGORIES.get(category_key)
        if conf is None:
            return
        guild, category = self._guild_category_for_reporter(user.id)
        if guild is None or category is None:
            try:
                await user.send("Sorry, I couldn't find a server to file your report in right now.")
            except discord.HTTPException:
                pass
            return

        number = len(self._all_tickets()) + 1
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
            guild.me: discord.PermissionOverwrite(
                view_channel=True, send_messages=True, manage_channels=True, read_message_history=True),
        }
        team_roles = []
        for rname in conf["roles"]:
            role = get(guild.roles, name=rname)
            if role:
                overwrites[role] = discord.PermissionOverwrite(
                    view_channel=True, send_messages=True, read_message_history=True)
                team_roles.append(role)

        try:
            channel = await guild.create_text_channel(
                name=f"🤫anon-{number:04d}",
                category=category,
                overwrites=overwrites,
                topic=f"Anonymous {conf['label']} report #{number:04d} — messages here relay to the reporter via Herupa DMs.",
            )
        except discord.Forbidden:
            try:
                await user.send("I couldn't open your report (I'm missing permissions). Please contact a mod directly.")
            except discord.HTTPException:
                pass
            return

        self.mongo.addCollectionEntry(database_name=self.db, collection_name=self.col, payload={
            "number": number, "channel_id": str(channel.id), "opener_id": str(user.id),
            "category": category_key, "anonymous": True, "claimed_by": None,
            "opened_at": int(time.time()), "status": "open",
        })
        self._anon_link(channel.id, user.id)

        ping = " ".join(r.mention for r in team_roles)
        embed = discord.Embed(
            title=f"🤫 Anonymous {conf['label']} Report #{number:04d}",
            description=(f"An anonymous member submitted a report — **their identity is hidden.**\n\n"
                         f">>> {content}\n\n"
                         "Type here to reply — I relay messages to and from the reporter's DMs. "
                         "Start a line with `//` to keep it internal (not sent to them).\n"
                         "*Staff:* `$claim` · `$close [reason]` or the button below."),
            colour=conf["colour"],
        )
        await channel.send(content=ping, embed=embed, view=CloseView(self),
                           allowed_mentions=discord.AllowedMentions(roles=True))
        try:
            await user.send(
                f"✅ Your anonymous **{conf['label']}** report has been sent. "
                "Keep messaging me here and I'll pass it along — your name stays hidden.")
        except discord.HTTPException:
            pass

    # ------------------------- create -------------------------

    async def create_ticket(self, interaction, category_key):
        conf = CATEGORIES[category_key]
        # ACK immediately so we never miss Discord's 3s response window, then work.
        try:
            await interaction.response.defer(ephemeral=True)
        except discord.HTTPException:
            pass
        try:
            await self._create_ticket_inner(interaction, category_key, conf)
        except Exception as ex:
            import traceback
            traceback.print_exc()
            try:
                await interaction.followup.send(
                    f"⚠️ Ticket creation failed: `{type(ex).__name__}: {ex}`", ephemeral=True)
            except discord.HTTPException:
                pass

    async def _create_ticket_inner(self, interaction, category_key, conf):
        guild = interaction.guild
        opener = interaction.user

        # One open ticket per user per category — point them at the existing one.
        for t in self._all_tickets():
            if (t.get("opener_id") == str(opener.id) and t.get("category") == category_key
                    and t.get("status") == "open"):
                ch = guild.get_channel(int(t["channel_id"]))
                if ch:
                    await interaction.followup.send(
                        f"You already have an open {conf['label']} ticket: {ch.mention}", ephemeral=True)
                    return

        category = self._ticket_category(interaction)
        if category is None:
            await interaction.followup.send(
                "I couldn't find the tickets category. Ask an admin to run the panel "
                "inside the tickets category.", ephemeral=True)
            return

        number = len(self._all_tickets()) + 1

        overwrites = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
            guild.me: discord.PermissionOverwrite(
                view_channel=True, send_messages=True, manage_channels=True, read_message_history=True),
            opener: discord.PermissionOverwrite(
                view_channel=True, send_messages=True, read_message_history=True),
        }
        team_roles = []
        for rname in conf["roles"]:
            role = get(guild.roles, name=rname)
            if role:
                overwrites[role] = discord.PermissionOverwrite(
                    view_channel=True, send_messages=True, read_message_history=True)
                team_roles.append(role)

        try:
            channel = await guild.create_text_channel(
                name=f"{conf['emoji']}{opener.display_name}",
                category=category,
                overwrites=overwrites,
                topic=f"{conf['label']} ticket #{number:04d} opened by {opener} ({opener.id})",
            )
        except discord.Forbidden:
            await interaction.followup.send(
                "I couldn't open the ticket — I need the **Manage Roles** permission to create "
                "private channels. Please ask an admin to grant it.", ephemeral=True)
            return

        self.mongo.addCollectionEntry(database_name=self.db, collection_name=self.col, payload={
            "number": number, "channel_id": str(channel.id), "opener_id": str(opener.id),
            "category": category_key, "claimed_by": None, "opened_at": int(time.time()),
            "status": "open",
        })

        ping = " ".join([opener.mention] + [r.mention for r in team_roles])
        embed = discord.Embed(
            title=f"{conf['emoji']} {conf['label']} — Ticket #{number:04d}",
            description=(f"Thanks {opener.mention}, the **{conf['label']}** team has been notified.\n"
                         "Describe your issue and someone will be with you shortly.\n\n"
                         "*Staff:* `$claim` to take it · `$add @user` to pull someone in · "
                         "`$close [reason]` or the button below to close."),
            colour=conf["colour"],
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
        # Transcript -> ticket-logs on the dedicated logging server (no-op if unavailable).
        await self.log.send("ticket", embed=embed,
                            file=discord.File(buf, filename=f"ticket-{ticket['number']:04d}.txt"))
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

    @commands.command(name="ticketpanel", aliases=["tpanel"])
    async def ticketpanel(self, ctx):
        """Post the ticket panel in this channel (admin / head chill only)."""
        if not (ctx.author.guild_permissions.administrator
                or any(r.name.lower() == "head chill" for r in ctx.author.roles)):
            await ctx.send("Only an admin can post the ticket panel.")
            return
        embed = discord.Embed(
            title="🎫 Open a Ticket",
            description=("Need a hand? Pick the team that fits and we'll open a private channel just for you.\n\n"
                         "🤖 **Tech Support** — bots, integrations, game servers\n"
                         "👀 **Moderation** — reports, rule issues, appeals\n"
                         "📸 **Media** — content, streams, media requests\n\n"
                         "Your ticket will be visible only to you and the team you choose.\n\n"
                         "🤫 **Want to stay anonymous?** Instead of opening a ticket, **DM me** "
                         "`$whisper <your message>`. I'll ask which team it should go to and open an "
                         "anonymous ticket — your name stays hidden and you chat with the team right here in DMs."),
            colour=0x5865F2,
        )
        panel = await ctx.send(embed=embed, view=TicketPanelView(self))
        try:
            await panel.pin()
        except discord.HTTPException:
            pass
        try:
            await ctx.message.delete()
        except discord.HTTPException:
            pass

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
        view = AnonTeamView(self, ctx.author, message.strip())
        view.message = await ctx.send("🤫 Which team should receive your anonymous report?", view=view)

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
