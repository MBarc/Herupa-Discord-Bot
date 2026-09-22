'''
Purpose: Auto-create a personal voice room when a member joins the "create room"
VC, and let them switch that room's privacy mode live with $crpm.

Privacy modes:
  - public  : @everyone can join.
  - private : only the owner and their favorites can join.

$crpm toggles the stored mode AND, if the member currently has a room, applies
the new mode to it live (re-permissioning and renaming). Switching to private
blocks new disallowed members from joining, but never disconnects anyone who is
already in the room.

PRIVATE MEANS PRIVATE (the $modjoin override)
---------------------------------------------
Staff used to get a blanket connect on every private room via "bypass_roles",
so "PRIVATE" was advisory and mods wandered in casually. Now bypass roles get
*visibility* only ("private_bypass": "view_only", the default): they can see
the room exists, but the join button is dead. Getting in is a deliberate,
logged act:

    $modjoin {@owner | #room} {reason}

...which grants the caller a temporary connect overwrite, announces itself in
the room's own chat when they walk in, and writes a line to the server's
mod-log and to the central log. The grant is single-use: it lapses if unused
within "modjoin_minutes", and is revoked the moment they leave the room.

Channel overwrites are ignored for anyone with Administrator, so permissions
alone can't hold the line. A listener is the real enforcement: joining a
private room without being the owner, a favorite, or a grant holder gets you
disconnected and DM'd. Set "enforce_private": false to run log-only (announce
and record intrusions without disconnecting) while a server gets used to it.

MULTI-SERVER: driven by per-guild config in Mongo (db "createroom",
collection "config", one doc per guild_id):

    {
      "guild_id": "645847490020638720",
      "trigger_channel": "🔧create room🔧",  # joining this VC spawns a room
      "afk_channel": "💀AFK💀",              # never auto-deleted (None if no AFK VC
                                             #   lives in the rooms category)
      "bypass_roles": ["deputy", "sheriff"], # staff who may run $modjoin
      "hidden_roles": ["newbie"],            # can never see auto-created rooms
      "private_bypass": "view_only",         # view_only (default) | open | none
      "enforce_private": true,               # false = log intrusions, don't kick
      "modjoin_minutes": 15,                 # window to use a $modjoin grant
      "log_channel": "👮law-chat👮",          # audit channel (falls back to the
                                             #   moderation config's log_channel)
    }

  private_bypass: what a bypass role gets on a PRIVATE room.
      "view_only" - sees the room, can't connect without $modjoin  (default)
      "open"      - the old blanket connect, no override needed
      "none"      - can't even see the room ($modjoin still works)

Rooms are created in the trigger channel's own category. A member's privacy
mode and custom room name are per member (global), not per server. Configs are
cached at load; `$roomreload` (admin) re-reads them after a Mongo edit. Guilds
with no config doc are ignored entirely.

Other collections in db "createroom":
  privacy     - {guild_id, member_id, privacy_mode}, one per member per guild
  rooms       - {_id: channel_id, guild_id, owner_id, mode}, live room ownership
                (enforcement needs to know whose room it is; the channel name is
                only a fallback)
  grants      - {_id: "channel:member", ..., expires_at, entered}, live overrides
  modjoin_log - append-only audit trail, read back by $modjoins
'''
import datetime
import time

import discord
from discord.ext import commands, tasks

import sys
import os
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
sys.path.append(parent_dir)
from tools.HerupaMongo import HerupaMongo
from tools.HerupaLogger import HerupaLogger


PINK = 0xFFB7C5
DEFAULT_MODJOIN_MINUTES = 15
SWEEP_INTERVAL = 60  # seconds between checks for lapsed (unused) grants


class CreateRoom(commands.Cog):

    def __init__(self, client):
        self.client = client
        self.dbName = "createroom"
        self.config_col = "config"
        self.mongo_instance = HerupaMongo()
        self.logger = HerupaLogger(client)
        self._configs = {}

    async def cog_load(self):
        self._load_configs()
        self.grant_sweep.start()

    async def cog_unload(self):
        self.grant_sweep.cancel()

    # ----------------------------- config -----------------------------

    def _load_configs(self):
        # Cached (not per-call) because on_voice_state_update fires constantly.
        self._configs = {}
        for doc in self.mongo_instance.returnCollectionEntries(
                database_name=self.dbName, collection_name=self.config_col):
            try:
                self._configs[int(doc["guild_id"])] = doc
            except (KeyError, TypeError, ValueError):
                pass

    def _conf(self, guild_id):
        return self._configs.get(int(guild_id))

    @commands.command(name="roomreload")
    @commands.has_guild_permissions(administrator=True)
    async def roomreload(self, ctx):
        """Re-read the rooms configs from Mongo."""
        self._load_configs()
        await ctx.send(f"🔧 Reloaded rooms config for {len(self._configs)} server(s).")

    # ----------------------------- collections -----------------------------

    def _privacy_col(self):
        # Privacy mode is PER SERVER per member (a private room in one server
        # says nothing about your rooms elsewhere).
        return self.mongo_instance.client[self.dbName]["privacy"]

    def _rooms_col(self):
        return self.mongo_instance.client[self.dbName]["rooms"]

    def _grants_col(self):
        return self.mongo_instance.client[self.dbName]["grants"]

    def _audit_col(self):
        return self.mongo_instance.client[self.dbName]["modjoin_log"]

    def _audit_update(self, audit_id, fields):
        # Grants written before an upgrade may have no audit doc attached.
        if audit_id:
            self._audit_col().update_one({"_id": audit_id}, {"$set": fields})

    def _get_privacy(self, guild_id, member_id):
        doc = self._privacy_col().find_one(
            {"guild_id": str(guild_id), "member_id": str(member_id)})
        return doc["privacy_mode"] if doc else "public"

    def _set_privacy(self, guild_id, member_id, mode):
        self._privacy_col().update_one(
            {"guild_id": str(guild_id), "member_id": str(member_id)},
            {"$set": {"privacy_mode": mode}}, upsert=True)

    # ----------------------------- helpers -----------------------------

    @staticmethod
    def _role(guild, name):
        """Look a role up by name, case-insensitively — configs are written in
        lowercase ("deputy") while the actual role is usually capitalised."""
        if not name:
            return None
        wanted = name.lower()
        return discord.utils.find(lambda r: r.name.lower() == wanted, guild.roles)

    def _room_label(self, member):
        """The name shown after 'MODE - ' on a member's room. Defaults to their
        display name, or a custom name they bought from the shop ($buy roomname)."""
        doc = self.mongo_instance.client["roomnames"]["names"].find_one({"_id": str(member.id)})
        if doc and doc.get("name"):
            return doc["name"]
        return member.display_name

    def _room_overwrite(self):
        return discord.PermissionOverwrite(
            connect=True, speak=True, read_messages=True, send_messages=True,
            view_channel=True, use_voice_activation=True)

    def _favorite_ids(self, guild_id, memberID):
        # Favorites are per guild (see cogs/Favorites.py).
        return [int(d["fav_id"]) for d in self.mongo_instance.client["favorites"]["favorites"].find(
            {"guild_id": str(guild_id), "owner_id": str(memberID)})]

    def _build_overwrites(self, guild, owner, mode, conf, channel=None):
        """Build the full permission-overwrite map for a room in one shot (no API
        calls) so it can be applied atomically at channel creation / edit — much
        faster than a sequence of set_permissions calls. Shared by room creation
        and the live $crpm switch so the two can't drift apart.

        `channel` is passed when the room already exists, so live $modjoin grants
        survive a privacy switch instead of being wiped by the rebuild."""
        allow = self._room_overwrite()
        overwrites = {}

        # Hidden roles (e.g. Chill Club newbies) can never see an auto-created
        # room, in either mode.
        for role_name in conf.get("hidden_roles", []):
            role = self._role(guild, role_name)
            if role:
                overwrites[role] = discord.PermissionOverwrite(view_channel=False)

        if mode == "public":
            overwrites[guild.default_role] = allow
            return overwrites

        # private
        overwrites[guild.default_role] = discord.PermissionOverwrite(view_channel=False)
        overwrites[owner] = allow
        # Herupa has to keep her own key: announcing an override and removing an
        # uninvited join both need her inside a channel @everyone can't see, and
        # she isn't necessarily an administrator in every server.
        if guild.me is not None:
            overwrites[guild.me] = allow
        for fav_id in self._favorite_ids(guild.id, str(owner.id)):
            fav = guild.get_member(fav_id)
            if fav:
                overwrites[fav] = allow

        # Staff see the room but can't walk in; $modjoin is the way through.
        bypass = (conf.get("private_bypass") or "view_only").lower()
        for role_name in conf.get("bypass_roles", []):
            role = self._role(guild, role_name)
            if not role:
                continue
            if bypass == "open":
                overwrites[role] = allow
            elif bypass == "view_only":
                overwrites[role] = discord.PermissionOverwrite(view_channel=True, connect=False)
            # "none" -> no entry at all, so @everyone's view_channel=False stands

        # Re-apply any live override so a $crpm switch doesn't lock out a mod
        # who is legitimately in the room right now.
        if channel is not None:
            for doc in self._grants_col().find({"channel_id": str(channel.id)}):
                holder = guild.get_member(int(doc["member_id"]))
                if holder:
                    overwrites[holder] = allow

        return overwrites

    def _trigger(self, guild, conf):
        return discord.utils.get(guild.channels, name=conf["trigger_channel"])

    def _is_auto_room(self, channel, conf):
        """Is this one of the rooms we spawn (as opposed to the trigger, the AFK
        channel, or a hand-made VC that happens to live in the category)?"""
        if not isinstance(channel, discord.VoiceChannel):
            return False
        trigger = self._trigger(channel.guild, conf)
        if trigger is None or channel.category is None or channel.category != trigger.category:
            return False
        if channel.name in (conf["trigger_channel"], conf.get("afk_channel")):
            return False
        return channel.name.startswith("PUBLIC") or channel.name.startswith("PRIVATE")

    def _is_private_room(self, channel, conf):
        return self._is_auto_room(channel, conf) and channel.name.startswith("PRIVATE")

    def _find_owned_room(self, guild, owner, conf):
        """Return the member's auto-created room (matched by its "MODE - name"
        title) or None. Works whether or not they're currently connected to it."""
        trigger = self._trigger(guild, conf)
        category = trigger.category if trigger else None
        if category is None:
            return None
        suffix = f" - {self._room_label(owner)}"
        for vc in category.voice_channels:
            if vc.name in (conf["trigger_channel"], conf.get("afk_channel")):
                continue
            if vc.name.endswith(suffix) and (vc.name.startswith("PUBLIC") or vc.name.startswith("PRIVATE")):
                return vc
        return None

    # --------------------------- room ownership ---------------------------

    def _register_room(self, channel, owner, mode):
        self._rooms_col().update_one(
            {"_id": str(channel.id)},
            {"$set": {"guild_id": str(channel.guild.id),
                      "owner_id": str(owner.id),
                      "mode": mode}},
            upsert=True)

    def _forget_room(self, channel_id):
        self._rooms_col().delete_one({"_id": str(channel_id)})
        self._grants_col().delete_many({"channel_id": str(channel_id)})

    def _room_owner(self, channel):
        """Who owns this room? The rooms collection is authoritative; the name
        match is a fallback for rooms that predate it."""
        doc = self._rooms_col().find_one({"_id": str(channel.id)})
        if doc:
            owner = channel.guild.get_member(int(doc["owner_id"]))
            if owner:
                return owner
        if " - " not in channel.name:
            return None
        label = channel.name.split(" - ", 1)[1]
        named = self.mongo_instance.client["roomnames"]["names"].find_one({"name": label})
        if named:
            owner = channel.guild.get_member(int(named["_id"]))
            if owner:
                return owner
        return discord.utils.find(lambda m: m.display_name == label, channel.guild.members)

    # ----------------------------- grants -----------------------------

    @staticmethod
    def _grant_id(channel_id, member_id):
        return f"{channel_id}:{member_id}"

    def _active_grant(self, channel_id, member_id):
        doc = self._grants_col().find_one({"_id": self._grant_id(channel_id, member_id)})
        if doc is None:
            return None
        # Before it's used a grant is a short window to walk in; once used it
        # lasts as long as they stay in the room.
        if not doc.get("entered") and doc.get("expires_at", 0) < time.time():
            return None
        return doc

    async def _revoke_grant(self, doc, reason):
        """Drop the override and its stored record. Only overwrites we granted
        are removed, so a favorite's access is never stripped by accident."""
        self._grants_col().delete_one({"_id": doc["_id"]})
        guild = self.client.get_guild(int(doc["guild_id"]))
        if guild is None:
            return
        channel = guild.get_channel(int(doc["channel_id"]))
        member = guild.get_member(int(doc["member_id"]))
        if channel is None or member is None:
            return
        try:
            await channel.set_permissions(member, overwrite=None, reason=reason)
        except (discord.Forbidden, discord.HTTPException, discord.NotFound):
            pass

    @tasks.loop(seconds=SWEEP_INTERVAL)
    async def grant_sweep(self):
        """Expire grants that were never used — a mod who asks for access and
        then thinks better of it shouldn't keep a standing key."""
        now = time.time()
        for doc in list(self._grants_col().find({"entered": False})):
            if doc.get("expires_at", 0) > now:
                continue
            await self._revoke_grant(doc, "$modjoin override expired unused")
            self._audit_update(doc.get("audit_id"), {"lapsed_at": now})

    @grant_sweep.before_loop
    async def before_grant_sweep(self):
        await self.client.wait_until_ready()

    # ----------------------------- access -----------------------------

    def _is_staff(self, member, conf):
        """May this member use $modjoin? A configured bypass role, or whoever
        the server calls a bot manager (owner / admin / manager role)."""
        names = {r.lower() for r in conf.get("bypass_roles", [])}
        if any(r.name.lower() in names for r in member.roles):
            return True
        fm = self.client.get_cog("FeatureManager")
        if fm is not None:
            return fm.is_manager(member)
        return member.guild_permissions.administrator

    def _may_enter(self, member, channel, conf):
        """Fails OPEN for rooms we can't attribute to an owner — better to let a
        stranger in than to boot people out of a channel we don't understand."""
        if member.bot:
            return True
        owner = self._room_owner(channel)
        if owner is None:
            return True
        if member.id == owner.id:
            return True
        if member.id in self._favorite_ids(channel.guild.id, str(owner.id)):
            return True
        if self._active_grant(channel.id, member.id) is not None:
            return True
        # A server that opted out of the override keeps the old blanket bypass.
        # Role overwrites don't show up in overwrites_for(member), so check the
        # roles themselves rather than the resolved permissions — permissions_for
        # would say yes to every Administrator, which is the hole we're closing.
        if (conf.get("private_bypass") or "view_only").lower() == "open":
            names = {r.lower() for r in conf.get("bypass_roles", [])}
            if any(r.name.lower() in names for r in member.roles):
                return True
        # An explicit member-level connect (someone was let in by hand) counts.
        return channel.overwrites_for(member).connect is True

    # ----------------------------- logging -----------------------------

    def _log_channel(self, guild, conf):
        name = conf.get("log_channel")
        if not name:
            mod_conf = self.mongo_instance.client["moderation"]["config"].find_one(
                {"guild_id": str(guild.id)})
            name = (mod_conf or {}).get("log_channel")
        if not name:
            return None
        wanted = name.lower()
        return discord.utils.find(lambda c: c.name.lower() == wanted, guild.text_channels)

    async def _audit_log(self, guild, conf, title, desc, colour):
        """Same line to the server's own mod-log and to the central log server."""
        embed = discord.Embed(title=title, description=desc, colour=colour,
                              timestamp=discord.utils.utcnow())
        embed.set_footer(text=guild.name)
        channel = self._log_channel(guild, conf)
        if channel is not None:
            try:
                await channel.send(embed=embed,
                                   allowed_mentions=discord.AllowedMentions.none())
            except (discord.Forbidden, discord.HTTPException):
                pass
        await self.logger.send("mod", embed=embed)

    # ----------------------------- $crpm -----------------------------

    @commands.command(name='crpm',
                      description='Switches the privacy mode of your create-room, live if you have one.',
                      brief='Switches your room privacy mode.')
    @commands.guild_only()
    async def crpm(self, ctx):
        conf = self._conf(ctx.guild.id)
        if conf is None:
            await ctx.send("Auto-created rooms aren't set up for this server yet.")
            return
        current = self._get_privacy(ctx.guild.id, ctx.author.id)
        new_mode = "private" if current == "public" else "public"
        self._set_privacy(ctx.guild.id, ctx.author.id, new_mode)

        room = self._find_owned_room(ctx.guild, ctx.author, conf)
        if room is None:
            await ctx.channel.send(
                f"Your privacy mode is now **{new_mode.upper()}**. It'll apply to your next room.")
            return

        try:
            overwrites = self._build_overwrites(ctx.guild, ctx.author, new_mode, conf, channel=room)
            new_name = f"{new_mode.upper()} - {self._room_label(ctx.author)}"
            # One API call applies both the rename and every permission change.
            # Going private only blocks NEW joins; anyone already connected stays.
            await room.edit(name=new_name, overwrites=overwrites)
        except discord.Forbidden:
            await ctx.channel.send(
                f"Switched you to **{new_mode.upper()}**, but I couldn't update your live room (missing permissions).")
            return

        self._register_room(room, ctx.author, new_mode)
        await ctx.channel.send(f"Your room is now **{new_mode.upper()}**.")

    # ----------------------------- $modjoin -----------------------------

    async def _resolve_room(self, ctx, target, conf):
        """A room, from either a voice-channel reference or its owner."""
        try:
            return await commands.VoiceChannelConverter().convert(ctx, target)
        except commands.BadArgument:
            pass
        try:
            owner = await commands.MemberConverter().convert(ctx, target)
        except commands.BadArgument:
            return None
        doc = self._rooms_col().find_one({"guild_id": str(ctx.guild.id),
                                          "owner_id": str(owner.id)})
        if doc:
            room = ctx.guild.get_channel(int(doc["_id"]))
            if room is not None:
                return room
        return self._find_owned_room(ctx.guild, owner, conf)

    @commands.command(name="modjoin", aliases=["mj"],
                      description="Staff override to enter a private room. Announced in the room and logged.",
                      brief="Enter a private room, on the record.")
    @commands.guild_only()
    async def modjoin(self, ctx, target: str = None, *, reason: str = None):
        conf = self._conf(ctx.guild.id)
        if conf is None:
            await ctx.send("Auto-created rooms aren't set up for this server yet.")
            return
        if not self._is_staff(ctx.author, conf):
            await ctx.send("That's a staff override.")
            return
        if target is None or reason is None or len(reason.strip()) < 3:
            await ctx.send("Usage: `$modjoin {@owner | #room} {reason}`. The reason is "
                           "posted in the room and saved to the log, so make it a real one.")
            return

        room = await self._resolve_room(ctx, target, conf)
        if room is None:
            await ctx.send("I couldn't find that room. Point me at the voice channel or "
                           "at whoever owns it.")
            return
        if not self._is_private_room(room, conf):
            await ctx.send(f"**{room.name}** isn't a private room, so you can just join it.")
            return
        if self._may_enter(ctx.author, room, conf):
            await ctx.send("You can already get into that room, no override needed.")
            return

        reason = reason.strip()
        minutes = int(conf.get("modjoin_minutes", DEFAULT_MODJOIN_MINUTES))
        now = time.time()
        owner = self._room_owner(room)

        try:
            await room.set_permissions(
                ctx.author, overwrite=self._room_overwrite(),
                reason=f"$modjoin by {ctx.author}: {reason}")
        except discord.Forbidden:
            await ctx.send("I don't have permission to edit that room's access.")
            return

        audit_id = f"{room.id}:{ctx.author.id}:{int(now)}"
        self._audit_col().insert_one({
            "_id": audit_id,
            "guild_id": str(ctx.guild.id),
            "channel_id": str(room.id),
            "room_name": room.name,
            "owner_id": str(owner.id) if owner else None,
            "owner_name": owner.display_name if owner else "unknown",
            "mod_id": str(ctx.author.id),
            "mod_name": str(ctx.author),
            "reason": reason,
            "created_at": now,
        })
        self._grants_col().update_one(
            {"_id": self._grant_id(room.id, ctx.author.id)},
            {"$set": {"guild_id": str(ctx.guild.id),
                      "channel_id": str(room.id),
                      "member_id": str(ctx.author.id),
                      "reason": reason,
                      "audit_id": audit_id,
                      "expires_at": now + minutes * 60,
                      "entered": False}},
            upsert=True)

        await ctx.send(f"🔓 You can enter **{room.name}** for the next **{minutes} min**. "
                       f"Everyone in the room will see that you joined and why, and it's in the log. "
                       f"Access ends when you leave.")
        await self._audit_log(
            ctx.guild, conf, "🔓 Private room override requested",
            f"**Staff:** {ctx.author.mention} (`{ctx.author.id}`)\n"
            f"**Room:** {room.name}\n"
            f"**Owner:** {owner.mention if owner else 'unknown'}\n"
            f"**Reason:** {reason[:1000]}",
            0xF2B24E)

    @commands.command(name="modjoins",
                      description="The recent private-room overrides.",
                      brief="Recent $modjoin overrides.")
    @commands.guild_only()
    async def modjoins(self, ctx):
        conf = self._conf(ctx.guild.id)
        if conf is None:
            await ctx.send("Auto-created rooms aren't set up for this server yet.")
            return
        if not self._is_staff(ctx.author, conf):
            await ctx.send("That's a staff command.")
            return

        entries = list(self._audit_col().find({"guild_id": str(ctx.guild.id)})
                       .sort("created_at", -1).limit(10))
        embed = discord.Embed(title="🔓 Recent private-room overrides", colour=PINK)
        if not entries:
            embed.description = "Nobody has used `$modjoin` here yet."
        for doc in entries:
            when = discord.utils.format_dt(
                datetime.datetime.fromtimestamp(doc["created_at"], datetime.timezone.utc), "R")
            used = "entered" if doc.get("entered_at") else ("lapsed unused" if doc.get("lapsed_at") else "granted")
            embed.add_field(
                name=f"{doc.get('mod_name', 'unknown')} → {doc.get('owner_name', 'unknown')}'s room",
                value=f"{when} · {used}\n*{doc.get('reason', '')[:300]}*",
                inline=False)
        await ctx.send(embed=embed)

    # ----------------------------- enforcement -----------------------------

    async def _announce_entry(self, room, member, reason):
        """Say it in the room itself — the whole point is that the override is
        visible to the people whose privacy it overrode."""
        try:
            await room.send(
                f"🔒 {member.mention} joined this private room using a staff override.\n"
                f"**Reason:** {reason}",
                allowed_mentions=discord.AllowedMentions.none())
        except (discord.Forbidden, discord.HTTPException):
            pass

    async def _handle_intrusion(self, member, room, conf):
        """Somebody walked into a private room who shouldn't have. Administrator
        ignores channel overwrites, so this listener is the only thing that
        actually holds the line against staff."""
        enforce = conf.get("enforce_private", True)
        owner = self._room_owner(room)
        removed = False
        if enforce:
            try:
                await member.move_to(None, reason="Private room, no $modjoin override")
                removed = True
            except (discord.Forbidden, discord.HTTPException):
                pass

        if enforce:
            if self._is_staff(member, conf):
                note = ("That room is private. If you need to go in as staff, run "
                        "`$modjoin @owner <reason>`. It lets you in for a few minutes, "
                        "tells the room you're there, and saves the reason to the log.")
            else:
                note = "That room is set to private, so only the owner and their favorites can join."
            try:
                await member.send(f"🔒 I disconnected you from **{room.name}**. {note}")
            except (discord.Forbidden, discord.HTTPException):
                pass

        if removed:
            title, colour = "🔒 Private room: uninvited join blocked", 0xF0546C
        elif enforce:
            title, colour = "⚠️ Private room: couldn't remove uninvited join", 0xF0546C
        else:
            title, colour = "👀 Private room: uninvited join (log-only mode)", 0xF2B24E
        await self._audit_log(
            member.guild, conf, title,
            f"**Member:** {member.mention} (`{member.id}`)\n"
            f"**Room:** {room.name}\n"
            f"**Owner:** {owner.mention if owner else 'unknown'}\n"
            f"**Staff:** {'yes' if self._is_staff(member, conf) else 'no'}",
            colour)

    # ----------------------------- listener -----------------------------

    @commands.Cog.listener()
    async def on_voice_state_update(self, member, before, after):
        conf = self._conf(member.guild.id)
        if conf is None:
            return
        fm = self.client.get_cog("FeatureManager")
        if fm is not None and not fm.is_enabled(member.guild.id, "rooms"):
            return

        # Member joined the "create room" trigger -> spin up their room.
        if after.channel and after.channel.name == conf["trigger_channel"]:
            privacyMode = self._get_privacy(member.guild.id, member.id)

            channelName = f"{privacyMode.upper()} - {self._room_label(member)}"
            # Create the room WITH all its permissions in a single call, then move
            # the member immediately — no waiting on a chain of overwrite edits.
            overwrites = self._build_overwrites(member.guild, member, privacyMode, conf)
            memberChannel = await after.channel.category.create_voice_channel(channelName, overwrites=overwrites)
            # Record ownership BEFORE the move, or the enforcement below sees an
            # unattributable private room and boots the owner out of it.
            self._register_room(memberChannel, member, privacyMode)
            await member.move_to(memberChannel)

        # Left a room they had an override for -> hand the key back.
        if (before.channel and before.channel != after.channel
                and self._is_auto_room(before.channel, conf)):
            grant = self._grants_col().find_one(
                {"_id": self._grant_id(before.channel.id, member.id)})
            if grant is not None:
                await self._revoke_grant(grant, "$modjoin override ended (left the room)")
                self._audit_update(grant.get("audit_id"), {"left_at": time.time()})

        # Joined a private room: either they're using an override, or they
        # shouldn't be here.
        if after.channel and after.channel != before.channel and self._is_private_room(after.channel, conf):
            grant = self._active_grant(after.channel.id, member.id)
            if grant is not None:
                if not grant.get("entered"):
                    self._grants_col().update_one({"_id": grant["_id"]},
                                                  {"$set": {"entered": True}})
                    self._audit_update(grant.get("audit_id"), {"entered_at": time.time()})
                    await self._announce_entry(after.channel, member, grant.get("reason", ""))
            elif not self._may_enter(member, after.channel, conf):
                await self._handle_intrusion(member, after.channel, conf)

        # An auto-created room emptied out -> delete it to keep things tidy.
        trigger = self._trigger(member.guild, conf)
        if (before.channel and len(before.channel.members) == 0 and trigger
                and before.channel.category == trigger.category
                and before.channel.name != conf["trigger_channel"]
                and before.channel.name != conf.get("afk_channel")):
            self._forget_room(before.channel.id)
            await before.channel.delete()


async def setup(client):
    await client.add_cog(CreateRoom(client))
