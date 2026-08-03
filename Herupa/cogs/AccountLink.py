'''
Purpose: Link game accounts to Discord members (RoVer replacement).

Members run bare `$link` for the guided flow: a dropdown of the games this
server supports (or a single button when there is only one), then a popup form
asking for their username, and the game's own verification process takes it
from there. Replies in that flow are ephemeral, so verification codes stay
between Herupa and the member. The inline fast path still works too:
`$link <account type> <username>` (e.g. `$link roblox builderman`).
`$unlink <type>` removes a link. Staff on the moderation ladder run
`$lookup <member>` to see everything a member has linked.

PER-GAME REGISTRIES (adding a game = adding entries here, nothing else):
  RESOLVERS   type -> method resolving a username against the game's public
              API, returning (canonical username, extras) or None. Catches
              typos and stores a stable id (roblox_id / minecraft_uuid, which
              gives $lookup a working profile link).
  VERIFIERS   type -> its ownership-proof flow: the $verify checker, the
              proof label stored on success, and the instructions embed shown
              when the link goes pending. Types WITHOUT an entry can't be
              proofed and always save self-declared.

OWNERSHIP PROOF (classic-RoVer style, per-guild opt-in via "require_proof"):
where enabled, linking a proofable type hands the member a short code of
random words instead of linking immediately. Roblox: they paste it into
their profile's About section, run `$verify`, and Herupa reads the profile's
public description through the Roblox API to confirm the code is there. Only
the account owner can edit that blurb, so a match proves ownership. `$verify`
checks EVERY pending link the member has, each through its own game's
checker. Where proof is off, links save immediately and are labeled
self-declared in $lookup.

Minecraft is resolved through the Mojang API (username -> UUID), but has no
owner-editable public profile text, so there is no proof mechanism yet:
minecraft links always save self-declared.

MINECRAFT WHITELIST (offline servers): a guild's accounts config may carry a
"minecraft" block:

    {
      "offline": True,            # skip the Mojang lookup: offline-mode
                                  # servers use honor-system names, so only
                                  # the name FORMAT is checked
      "manage_whitelist": True,   # Herupa keeps the server whitelist in step
      "rcon_host": "minecraft.local",
      "rcon_port": 25575,
      "rcon_password": "...",     # falls back to env MC_RCON_PASSWORD
      "address": "...",           # optional, shown to members when whitelisted
      "required_role": None,      # optional role gate for whitelisting
    }

With manage_whitelist on, Herupa runs `whitelist add` over RCON when a
minecraft link saves (after the required_role gate), and `whitelist remove`
(+ kick) on $unlink, on re-linking to a different name, and when the member
leaves the Discord server (the link itself is global and survives; only that
guild's whitelist access is revoked). Links are per guild, so every
whitelist effect is naturally scoped to the one server the link belongs
to — no cross-server anything. Everything minecraft sits behind the
"minecraft" $feature (a sub-feature of "accounts"): switched off, the type
disappears from $link (dropdown and inline) and no whitelist syncing or
leave-revocation happens in that guild, while other account types carry on.

ROLE SYNC (Discord -> LuckPerms, one-way): the minecraft block's
"role_groups" ({discord role id: luckperms group}) makes Herupa keep each
linked member's LuckPerms groups matching their Discord roles, via console
`lp user <target> parent add/remove` over RCON. Managers configure the map
with $mcroles (panel with Add/Remove pickers, or inline $mcroles set/remove)
or the web UI's Minecraft page. Only mapped groups are ever touched, so
hand-granted in-game groups survive. On offline-mode servers the lp target
is the COMPUTED offline UUID (md5 of "OfflinePlayer:<name>"), so groups can
be granted before a player's first join; renames strip the old name's
identity first.

RECONCILE (every 10 min): LuckPerms output isn't readable over RCON, so all
lp commands are fire-and-forget. A tasks.loop re-applies the desired state
for every configured guild: missing whitelist entries are re-added (extras
are only removed when the config sets "strict_whitelist": true, so
hand-added legacy names survive by default) and every linked member's
mapped groups are re-asserted. Drift from downtime, missed events, or
manual edits heals within one pass.

MULTI-SERVER: driven by per-guild config in Mongo (db "accounts",
collection "config", one doc per guild_id):

    {
      "guild_id": "1531866278229442620",
      "types": ["roblox"],              # allowed $link types here; null/absent = any
      "verify_types": ["roblox"],       # linking one of these triggers the grants below
      "verified_role": "Community Member",  # role granted on a verify_types link
      "nickname_sync": True,            # set server nickname to the linked username
      "require_proof": True,            # roblox links need the profile-code $verify step
    }

Links are stored PER GUILD per user (db "accounts", collection "links":
user_id / guild_id / type / username / extras / linked_at) — what you link
in one server never follows you to another, and $unlink only touches the
server it was typed in.

$lookup authorisation reuses the per-guild moderation ladder from the
DeputyModeration/Timeout config (Mongo "moderation"/"config"), so there is one
definition of "moderator" per server. Guilds with no accounts config get a
"not set up" message.

VERIFY BUTTON + CLEAN CHANNELS: the pinned "Get Verified" embed carries a
persistent ✅ Verify button (custom_id herupa_verify_start) whose whole flow
is ephemeral -- pending proof is checked, otherwise the $link picker/modal
pipeline runs. Channels listed in config "clean_channel_ids" (the verify
channel) are kept spotless: every non-pinned message is deleted CLEAN_TTL
seconds after it appears (Herupa's replies included), with a 10-minute
janitor sweep catching anything posted while the bot was down. Needs Manage
Messages there. Both respect the "accounts" $feature.
'''

import sys
import os
import re
import time
import random
import hashlib
import uuid as uuidlib
import asyncio
import urllib.parse
from datetime import datetime, timedelta, timezone

import aiohttp
import discord
from discord.ext import commands, tasks

current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
sys.path.append(parent_dir)

from tools.HerupaMongo import HerupaMongo
from tools.MinecraftRcon import rcon


# Friendly, unambiguous words for verification codes (classic-RoVer style:
# easy to copy into a profile, obviously human-readable, unguessable in
# combination).
VERIFY_WORDS = [
    "apple", "banana", "blossom", "breeze", "candle", "cherry", "cloud",
    "comet", "coral", "daisy", "ember", "feather", "forest", "garden",
    "honey", "island", "lantern", "lemon", "maple", "meadow", "melody",
    "moon", "mountain", "ocean", "orchid", "panda", "pebble", "petal",
    "pine", "plum", "rainbow", "raven", "river", "rocket", "sakura",
    "silver", "sparrow", "star", "stone", "sunset", "thunder", "tiger",
    "tulip", "violet", "willow", "winter",
]


def offline_uuid(name):
    """The UUID an offline-mode server derives from a player name
    (Java's UUID.nameUUIDFromBytes over "OfflinePlayer:<name>")."""
    digest = bytearray(hashlib.md5(f"OfflinePlayer:{name}".encode("utf-8")).digest())
    digest[6] = (digest[6] & 0x0F) | 0x30   # version 3
    digest[8] = (digest[8] & 0x3F) | 0x80   # RFC 4122 variant
    return str(uuidlib.UUID(bytes=bytes(digest)))


GROUP_RE = re.compile(r"^[A-Za-z0-9_-]{1,36}$")

# How long messages survive in a "clean" channel (the verify channel):
# long enough to read a reply, short enough that the pinned embed is all
# anyone ever really sees.
CLEAN_TTL = 60


class LuckPermsGroupModal(discord.ui.Modal, title="Map to a LuckPerms group"):
    """Second step of $mcroles Add: which in-game group the picked role syncs to."""

    group = discord.ui.TextInput(label="LuckPerms group name", max_length=36,
                                 placeholder="e.g. admin / mod / member")

    def __init__(self, cog, role):
        super().__init__()
        self.cog = cog
        self.role = role

    async def on_submit(self, interaction):
        group = str(self.group).strip().lower()
        if not GROUP_RE.fullmatch(group):
            await interaction.response.send_message(
                "Group names are 1-36 letters, numbers, dashes, or underscores.",
                ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        msg = await self.cog.mcroles_set(interaction.guild, self.role, group)
        await interaction.followup.send(msg, ephemeral=True)


class LinkUsernameModal(discord.ui.Modal):
    """Popup form asking for the username of the game account being linked
    (modals can only open from an interaction, hence the dropdown/button hop)."""

    username = discord.ui.TextInput(label="Username", max_length=50)

    def __init__(self, cog, conf, account_type):
        super().__init__(title=f"Link your {account_type.capitalize()} account"[:45])
        self.cog = cog
        self.conf = conf
        self.account_type = account_type
        self.username.label = f"Your {account_type.capitalize()} username"[:45]
        self.username.placeholder = cog.PLACEHOLDERS.get(account_type,
                                                         "Your in-game username")

    async def on_submit(self, interaction):
        # Ephemeral from here on: the verification code (and any typo fumbling)
        # stays between Herupa and the member.
        await interaction.response.defer(ephemeral=True)
        kind, payload = await self.cog._do_link(
            interaction.guild, interaction.user, self.conf,
            self.account_type, str(self.username))
        if kind == "pending":
            await interaction.followup.send(embed=payload, ephemeral=True)
        else:
            await interaction.followup.send(payload, ephemeral=True)


class VerifyStartView(discord.ui.View):
    """Persistent ✅ Verify button on the pinned embed in a guild's verify
    channel. Everything it opens is ephemeral, so verifying leaves no trace
    in the channel: pending proof gets checked, otherwise the link picker /
    username modal runs -- same pipeline as $link."""

    def __init__(self, cog):
        super().__init__(timeout=None)
        self.cog = cog

    @discord.ui.button(label="Verify", emoji="✅",
                       style=discord.ButtonStyle.success,
                       custom_id="herupa_verify_start")
    async def start(self, interaction, button):
        await self.cog.verify_button(interaction)


class AccountLink(commands.Cog):

    # ------------------------- per-game registries -------------------------
    # Adding a game = adding entries here (plus its methods below).

    # type -> method resolving a username against the game's public API.
    RESOLVERS = {"roblox": "_resolve_roblox", "minecraft": "_resolve_minecraft"}

    # type -> its ownership-proof flow. Types without an entry can't be
    # proofed and always save self-declared.
    VERIFIERS = {
        "roblox": {
            "checker": "_check_roblox_proof",        # $verify: is the proof in place?
            "proof": "roblox-profile-code",          # stored on the link when it passes
            "instructions": "_roblox_proof_embed",   # what to do, shown at $link time
        },
    }

    NOT_FOUND_HINTS = {
        "roblox": "Double-check the spelling (username, not display name).",
        "minecraft": "Double-check the spelling (Java Edition username).",
    }
    PLACEHOLDERS = {
        "roblox": "e.g. builderman (username, not display name)",
        "minecraft": "e.g. Notch",
    }
    TYPE_EMOJI = {"roblox": "🎮", "minecraft": "⛏️"}

    def __init__(self, client):
        self.client = client
        self.db = "accounts"
        self.links_col = "links"
        self.config_col = "config"
        self.mod_db = "moderation"
        self.mod_config_col = "config"
        self.mongo = HerupaMongo()
        self._ccache = {}   # guild_id -> (expires, conf | None), janitor only

    async def cog_load(self):
        self.client.add_view(VerifyStartView(self))
        self.reconcile.start()
        self.janitor.start()

    async def cog_unload(self):
        self.reconcile.cancel()
        self.janitor.cancel()

    # ----------------------------- config helpers -----------------------------

    def _conf(self, guild_id):
        gid = str(guild_id)
        for doc in self.mongo.returnCollectionEntries(
                database_name=self.db, collection_name=self.config_col):
            if doc.get("guild_id") == gid:
                return doc
        return None

    def _conf_cached(self, guild_id):
        """30s-cached config, for the janitor's on_message path only (it
        fires for every guild message; everything else reads live)."""
        gid = str(guild_id)
        hit = self._ccache.get(gid)
        now = time.monotonic()
        if hit and hit[0] > now:
            return hit[1]
        conf = self._conf(gid)
        self._ccache[gid] = (now + 30, conf)
        return conf

    # ------------------------- clean channels (janitor) -------------------------
    # Guilds can list channels (config "clean_channel_ids", e.g. the verify
    # channel) where every message evaporates after CLEAN_TTL seconds so
    # only the pinned embed remains. The Verify button makes the normal flow
    # ephemeral; this catches typed commands, replies, and stray chatter.

    async def _delayed_clean(self, message):
        await asyncio.sleep(CLEAN_TTL)
        try:
            fresh = await message.channel.fetch_message(message.id)
            if not fresh.pinned:
                await fresh.delete()
        except discord.HTTPException:
            pass   # already gone, or we lost permission -- either is fine

    @commands.Cog.listener()
    async def on_message(self, message):
        # Herupa's own replies age out too, so no bot skip here. The free
        # checks and the cached config read come before anything costly.
        if message.guild is None:
            return
        fm = self.client.get_cog("FeatureManager")
        if fm is not None and not fm.is_enabled(message.guild.id, "accounts"):
            return
        conf = self._conf_cached(message.guild.id)
        if not conf or str(message.channel.id) not in (conf.get("clean_channel_ids") or []):
            return
        asyncio.create_task(self._delayed_clean(message))

    @tasks.loop(minutes=10)
    async def janitor(self):
        """Sweep pass for whatever on_message missed (downtime, edits made
        while the bot was offline). Deletes one-by-one with a per-pass cap:
        gentle on rate limits, and steady state is near zero anyway."""
        if not self.client.guilds:
            return   # guild cache not primed yet (on_ready is unreliable here)
        fm = self.client.get_cog("FeatureManager")
        cutoff = datetime.now(timezone.utc) - timedelta(seconds=CLEAN_TTL)
        for doc in self.mongo.returnCollectionEntries(
                database_name=self.db, collection_name=self.config_col):
            gid = doc.get("guild_id")
            ids = doc.get("clean_channel_ids") or []
            guild = self.client.get_guild(int(gid)) if gid else None
            if guild is None or not ids:
                continue
            if fm is not None and not fm.is_enabled(guild.id, "accounts"):
                continue
            for cid in ids:
                channel = guild.get_channel(int(cid))
                if channel is None:
                    continue
                deleted = 0
                try:
                    async for msg in channel.history(limit=100, before=cutoff):
                        if msg.pinned:
                            continue
                        await msg.delete()
                        deleted += 1
                        if deleted >= 30:
                            break
                except discord.HTTPException as e:
                    print(f"[AccountLink] janitor {cid}: {e}")

    def _is_mod(self, member):
        """Moderation-ladder check, shared definition with DeputyModeration:
        restricted or unrestricted roles from the guild's moderation config,
        or native admin."""
        if member.guild_permissions.administrator:
            return True
        gid = str(member.guild.id)
        conf = None
        for doc in self.mongo.returnCollectionEntries(
                database_name=self.mod_db, collection_name=self.mod_config_col):
            if doc.get("guild_id") == gid:
                conf = doc
                break
        if conf is None:
            return False
        names = {r.lower() for r in conf.get("restricted_roles", [])}
        names |= {r.lower() for r in conf.get("unrestricted_roles", [])}
        return any(role.name.lower() in names for role in member.roles)

    def _find_role(self, guild, name):
        low = name.lower()
        return next((r for r in guild.roles if r.name.lower() == low), None)

    # ----------------------------- link storage -----------------------------

    def _links_for(self, user_id, guild_id):
        """This member's links in THIS guild — links are per server, so what
        you link in one server never follows you to another."""
        uid, gid = str(user_id), str(guild_id)
        return [l for l in self.mongo.returnCollectionEntries(
                    database_name=self.db, collection_name=self.links_col)
                if l.get("user_id") == uid and l.get("guild_id") == gid]

    def _remove_link(self, user_id, guild_id, account_type):
        self.mongo.removeCollectionEntry(
            database_name=self.db, collection_name=self.links_col,
            payload={"user_id": str(user_id), "guild_id": str(guild_id),
                     "type": account_type})

    def _save_link(self, user_id, guild_id, account_type, username, extras=None):
        # One link per type per member per guild — re-linking replaces it.
        self._remove_link(user_id, guild_id, account_type)
        payload = {
            "user_id": str(user_id),
            "guild_id": str(guild_id),
            "type": account_type,
            "username": username,
            "linked_at": int(time.time()),
        }
        if extras:
            payload.update(extras)
        self.mongo.addCollectionEntry(
            database_name=self.db, collection_name=self.links_col, payload=payload)

    # ----------------------------- roblox -----------------------------

    async def _roblox_user(self, username):
        """Resolve a Roblox username to {id, name, displayName}; None if it
        doesn't exist; raises on API trouble."""
        async with aiohttp.ClientSession() as session:
            async with session.post(
                    "https://users.roblox.com/v1/usernames/users",
                    json={"usernames": [username], "excludeBannedUsers": False},
                    timeout=aiohttp.ClientTimeout(total=10)) as resp:
                data = await resp.json()
        found = data.get("data") or []
        return found[0] if found else None

    async def _roblox_description(self, roblox_id):
        """The public About/blurb text of a Roblox profile (empty if none)."""
        async with aiohttp.ClientSession() as session:
            async with session.get(
                    f"https://users.roblox.com/v1/users/{roblox_id}",
                    timeout=aiohttp.ClientTimeout(total=10)) as resp:
                data = await resp.json()
        return data.get("description") or ""

    async def _resolve_roblox(self, username):
        roblox = await self._roblox_user(username)
        if roblox is None:
            return None
        return roblox["name"], {"roblox_id": roblox["id"]}

    async def _check_roblox_proof(self, link):
        """$verify checker: (True, None) when the code is in the profile
        blurb, else (False, what to tell the member)."""
        blurb = await self._roblox_description(link["roblox_id"])
        # Case- and spacing-insensitive: the code is lowercase single-spaced words.
        normalised = " ".join(blurb.lower().split())
        if link["code"] in normalised:
            return True, None
        return False, (
            f"I checked **{link['username']}**'s profile but couldn't find your code yet. "
            "Make sure you pasted it into the **About** section and saved, then run `$verify` again. "
            "(Lost the code? Run `$link roblox` again for a fresh one.)")

    def _roblox_proof_embed(self, username, code):
        return discord.Embed(
            title="🔑 One more step: prove it's you",
            description=(
                f"To confirm **{username}** is your account:\n\n"
                f"1. Copy this code:\n```{code}```\n"
                "2. Paste it anywhere in your Roblox profile's **About** section "
                "(roblox.com, your profile, then the pencil icon) and save.\n"
                "3. Come back and type `$verify`.\n\n"
                "Once you're verified you can delete the code from your profile."
            ),
            colour=0xFFB7C5,
        )

    # ----------------------------- minecraft -----------------------------

    async def _minecraft_user(self, username):
        """Resolve a Minecraft (Java) username to {"id": undashed uuid,
        "name": canonical}; None if it doesn't exist; raises on API trouble."""
        url = ("https://api.mojang.com/users/profiles/minecraft/"
               + urllib.parse.quote(username, safe=""))
        async with aiohttp.ClientSession() as session:
            async with session.get(url,
                                   timeout=aiohttp.ClientTimeout(total=10)) as resp:
                if resp.status == 200:
                    return await resp.json()
                # 404 = no such player; 204/400 are how older/invalid-name
                # lookups come back. All mean "not found", not "API down".
                if resp.status in (204, 400, 404):
                    return None
                raise RuntimeError(f"Mojang API returned {resp.status}")

    async def _resolve_minecraft(self, username):
        player = await self._minecraft_user(username)
        if player is None:
            return None
        return player["name"], {"minecraft_uuid": player["id"]}

    # ------------------------ minecraft whitelist ------------------------

    def _mc_conf(self, conf):
        """The guild's minecraft block from the accounts config, or None."""
        mc = conf.get("minecraft") if conf else None
        return mc if isinstance(mc, dict) else None

    async def _mc_rcon(self, mc, command):
        password = mc.get("rcon_password") or os.environ.get("MC_RCON_PASSWORD", "")
        return await rcon(mc.get("rcon_host", "minecraft.local"),
                          int(mc.get("rcon_port", 25575)), password, command)

    async def _mc_whitelist(self, mc, action, name):
        """`whitelist add/remove <name>` over RCON (+ kick on remove).
        Returns True when the server took the command."""
        try:
            reply = await self._mc_rcon(mc, f"whitelist {action} {name}")
            if action == "remove":
                # Harmless "No player was found" when they're not online.
                await self._mc_rcon(
                    mc, f"kick {name} Your whitelist access was removed in Discord.")
            print(f"[AccountLink] rcon whitelist {action} {name}: {reply}")
            return True
        except Exception as e:
            print(f"[AccountLink] rcon whitelist {action} {name} FAILED: {e}")
            return False

    # ---------------------- luckperms role sync ----------------------
    # One-way, Discord -> game. All fire-and-forget: LuckPerms prints its
    # replies asynchronously, so RCON can't read them; the reconcile loop
    # re-asserts state instead of us verifying it here.

    def _lp_target(self, mc, username):
        # Offline servers derive the UUID from the name, so we can compute it
        # and grant groups before the player's first join.
        return offline_uuid(username) if mc.get("offline") else username

    async def _lp_apply(self, mc, member, username):
        """Make the MAPPED groups match the member's Discord roles. Groups
        outside role_groups are never touched."""
        groups = mc.get("role_groups") or {}
        if not groups:
            return
        held = {str(r.id) for r in member.roles}
        target = self._lp_target(mc, username)
        for role_id, group in groups.items():
            verb = "add" if role_id in held else "remove"
            try:
                await self._mc_rcon(mc, f"lp user {target} parent {verb} {group}")
            except Exception as e:
                print(f"[AccountLink] lp parent {verb} {group} for {username} FAILED: {e}")
                return   # server unreachable; the reconcile pass catches up

    async def _lp_strip(self, mc, username):
        """Remove every mapped group from a name (unlink / leave / rename)."""
        groups = mc.get("role_groups") or {}
        target = self._lp_target(mc, username)
        for group in set(groups.values()):
            try:
                await self._mc_rcon(mc, f"lp user {target} parent remove {group}")
            except Exception:
                return

    def _mc_feature_on(self, guild_id):
        """The "minecraft" $feature (sub-feature of accounts) gates EVERYTHING
        minecraft in a guild: offering it as a link type, the whitelist sync,
        and the leave-listener."""
        fm = self.client.get_cog("FeatureManager")
        return fm is None or (fm.is_enabled(guild_id, "accounts")
                              and fm.is_enabled(guild_id, "minecraft"))

    async def _mc_link_notes(self, guild, member, username, old_link):
        """Whitelist + role-sync bookkeeping after a minecraft link saves —
        this guild only. Links are per server, so a link (or its removal) in
        one guild never touches another guild's Minecraft server."""
        mc = self._mc_conf(self._conf(guild.id))
        if not mc or not self._mc_feature_on(guild.id):
            return []
        notes = []
        renamed = (old_link
                   and old_link.get("username", "").lower() != username.lower())
        if renamed:
            # A rename is a new identity (offline UUIDs derive from the
            # name): the old name loses its groups and whitelist spot.
            await self._lp_strip(mc, old_link["username"])
        if mc.get("manage_whitelist"):
            required = mc.get("required_role")
            if required and not any(r.name.lower() == required.lower()
                                    for r in member.roles):
                notes.append(f"⚠️ the Minecraft whitelist here needs the "
                             f"**{required}** role, so I haven't whitelisted you yet")
                return notes
            if renamed:
                await self._mc_whitelist(mc, "remove", old_link["username"])
            if not await self._mc_whitelist(mc, "add", username):
                notes.append("⚠️ I couldn't reach the Minecraft server to "
                             "whitelist you; try `$link` again later")
                return notes
            note = f"**{username}** is now on this server's Minecraft whitelist"
            if mc.get("address"):
                note += f" (join at **{mc['address']}**)"
            notes.append(note)
        await self._lp_apply(mc, member, username)
        return notes

    async def _mc_unlink_note(self, guild, link):
        """Whitelist + group removal when THIS guild's minecraft link goes
        away. Returns a sentence for the confirmation ('' when n/a)."""
        if not link or link.get("type") != "minecraft":
            return ""
        mc = self._mc_conf(self._conf(guild.id))
        if not mc or not self._mc_feature_on(guild.id):
            return ""
        await self._lp_strip(mc, link.get("username", ""))
        if not mc.get("manage_whitelist"):
            return ""
        if await self._mc_whitelist(mc, "remove", link.get("username", "")):
            return " Also took you off this server's Minecraft whitelist."
        return " ⚠️ I couldn't reach the Minecraft server to update the whitelist."

    @commands.Cog.listener()
    async def on_member_remove(self, member):
        """Leaving the guild revokes its Minecraft access: whitelist spot and
        mapped LuckPerms groups. The link doc stays for a possible rejoin."""
        conf = self._conf(member.guild.id)
        mc = self._mc_conf(conf)
        if not mc or not self._mc_feature_on(member.guild.id):
            return
        link = next((l for l in self._links_for(member.id, member.guild.id)
                     if l.get("type") == "minecraft"), None)
        if link is None:
            return
        await self._lp_strip(mc, link.get("username", ""))
        if mc.get("manage_whitelist"):
            await self._mc_whitelist(mc, "remove", link.get("username", ""))

    @commands.Cog.listener()
    async def on_member_update(self, before, after):
        """Discord role changes flow straight to the member's mapped
        LuckPerms groups (when they have a minecraft link here)."""
        if before.roles == after.roles:
            return
        mc = self._mc_conf(self._conf(after.guild.id))
        if not mc or not mc.get("role_groups"):
            return
        if not self._mc_feature_on(after.guild.id):
            return
        changed = {str(r.id) for r in set(before.roles) ^ set(after.roles)}
        if not changed & set(mc["role_groups"]):
            return
        link = next((l for l in self._links_for(after.id, after.guild.id)
                     if l.get("type") == "minecraft"), None)
        if link:
            await self._lp_apply(mc, after, link["username"])

    # ---------------------- reconcile loop ----------------------

    @tasks.loop(minutes=10)
    async def reconcile(self):
        """Re-assert the desired Minecraft state for every configured guild.
        lp output isn't readable over RCON, so instead of verifying we
        re-apply: adds/removes are idempotent, and drift from downtime,
        missed events, or manual edits heals within one pass."""
        if not self.client.guilds:
            return   # guild cache not primed yet (on_ready is unreliable here)
        for doc in self.mongo.returnCollectionEntries(
                database_name=self.db, collection_name=self.config_col):
            mc = self._mc_conf(doc)
            if not mc:
                continue
            gid = doc.get("guild_id")
            guild = self.client.get_guild(int(gid)) if gid else None
            if guild is None or not self._mc_feature_on(guild.id):
                continue
            try:
                await self._reconcile_guild(guild, mc)
            except Exception as e:
                print(f"[AccountLink] reconcile failed for {gid}: {e}")

    def _mc_linked_entries(self, guild):
        """(member, username) for every present member with a minecraft link
        in this guild."""
        entries = []
        for l in self.mongo.returnCollectionEntries(
                database_name=self.db, collection_name=self.links_col):
            if (l.get("guild_id") != str(guild.id) or l.get("type") != "minecraft"
                    or not l.get("verified", True) or not l.get("username")):
                continue
            member = guild.get_member(int(l["user_id"]))
            if member is not None:
                entries.append((member, l["username"]))
        return entries

    async def _reconcile_guild(self, guild, mc):
        entries = self._mc_linked_entries(guild)
        if mc.get("manage_whitelist"):
            required = mc.get("required_role")

            def eligible(m):
                return not required or any(r.name.lower() == required.lower()
                                           for r in m.roles)

            desired = {u for m, u in entries if u and eligible(m)}
            reply = await self._mc_rcon(mc, "whitelist list")
            actual = set()
            if ":" in reply:
                actual = {n.strip() for n in reply.split(":", 1)[1].split(",")
                          if n.strip()}
            actual_fold = {a.lower() for a in actual}
            for name in sorted(desired):
                if name.lower() not in actual_fold:
                    print(f"[AccountLink] reconcile: whitelisting {name} in {guild.name}")
                    await self._mc_rcon(mc, f"whitelist add {name}")
            if mc.get("strict_whitelist"):
                desired_fold = {d.lower() for d in desired}
                for name in sorted(actual):
                    if name.lower() not in desired_fold:
                        print(f"[AccountLink] reconcile: removing {name} in {guild.name}")
                        await self._mc_whitelist(mc, "remove", name)
        if mc.get("role_groups"):
            for member, username in entries:
                if username:
                    await self._lp_apply(mc, member, username)

    # ----------------------------- grants -----------------------------

    async def _apply_grants(self, guild, member, conf, account_type, username):
        """Role + nickname for a confirmed verify-type link (RoVer behavior).
        Returns human-readable notes for the confirmation message."""
        notes = []
        verify_types = [t.lower() for t in conf.get("verify_types", [])]
        if account_type not in verify_types:
            return notes
        role_name = conf.get("verified_role")
        if role_name:
            role = self._find_role(guild, role_name)
            if role and role not in member.roles:
                try:
                    await member.add_roles(role, reason=f"Linked {account_type} account")
                    notes.append(f"you now have the **{role.name}** role")
                except discord.Forbidden:
                    notes.append(f"⚠️ I couldn't grant **{role_name}** (missing permission)")
        if conf.get("nickname_sync"):
            try:
                await member.edit(nick=username,
                                  reason=f"Nickname synced to linked {account_type} account")
                notes.append(f"your nickname is now **{username}**")
            except discord.Forbidden:
                # Happens for the server owner and anyone above Herupa's top
                # role — same limitation RoVer had.
                notes.append("⚠️ I couldn't change your nickname (Discord doesn't let "
                             "me rename the server owner or anyone above my role)")
        return notes

    # ----------------------------- commands -----------------------------

    async def _do_link(self, guild, member, conf, account_type, username):
        """The whole link pipeline (shared by the inline command and the popup
        flow): validate the type, resolve the game account, then either start
        the proof step or save + apply grants.

        Returns ("error", text) | ("pending", embed) | ("linked", text)."""
        account_type = account_type.lower().strip()
        username = username.strip()
        if account_type == "minecraft" and not self._mc_feature_on(guild.id):
            return "error", "Minecraft linking is turned off in this server."
        allowed = conf.get("types")
        if allowed and account_type not in [t.lower() for t in allowed]:
            return "error", f"This server supports linking: **{', '.join(allowed)}**."

        # Resolve the account against the game's API where we know how, so
        # typos are caught and the canonical name + stable id get stored.
        extras = {}
        mc = self._mc_conf(conf)
        offline_minecraft = (account_type == "minecraft"
                             and mc is not None and mc.get("offline"))
        resolver = self.RESOLVERS.get(account_type)
        if offline_minecraft:
            # Offline-mode server: in-game names aren't Mojang accounts, so
            # there is nothing to look up. Check the shape and move on.
            if not re.fullmatch(r"[A-Za-z0-9_]{3,16}", username):
                return "error", ("That doesn't look like a Minecraft name "
                                 "(3-16 letters, numbers, or underscores).")
        elif resolver:
            try:
                resolved = await getattr(self, resolver)(username)
            except Exception:
                return "error", (f"I couldn't reach {account_type.capitalize()} to check "
                                 "that username. Try again in a moment.")
            if resolved is None:
                hint = self.NOT_FOUND_HINTS.get(account_type, "Double-check the spelling.")
                return "error", (f"I couldn't find a {account_type.capitalize()} account "
                                 f"named **{username}**. {hint}")
            username, extras = resolved

        # Where proof is required and the game supports it, the link starts
        # PENDING: the member gets a code and completes with $verify.
        verifier = self.VERIFIERS.get(account_type)
        if verifier and conf.get("require_proof"):
            code = " ".join(random.sample(VERIFY_WORDS, 4))
            extras.update({"verified": False, "code": code})
            self._save_link(member.id, guild.id, account_type, username, extras)
            return "pending", getattr(self, verifier["instructions"])(username, code)

        extras.update({"verified": True, "proof": "self-declared"})
        old_link = None
        if account_type == "minecraft":
            # Needed below: re-linking to a new name frees the old whitelist spot.
            old_link = next((l for l in self._links_for(member.id, guild.id)
                             if l.get("type") == "minecraft"), None)
        self._save_link(member.id, guild.id, account_type, username, extras)
        notes = await self._apply_grants(guild, member, conf, account_type, username)
        if account_type == "minecraft":
            notes += await self._mc_link_notes(guild, member, username, old_link)
        msg = f"✅ Linked **{account_type}** account **{username}** to {member.mention}."
        if notes:
            msg += " Also: " + ", and ".join(notes) + "."
        return "linked", msg

    @commands.command(name="link")
    @commands.guild_only()
    async def link(self, ctx, account_type: str = None, *, username: str = None):
        """Link a game account: bare $link for the guided flow, or
        $link <type> <username> (e.g. $link roblox builderman)."""
        conf = self._conf(ctx.guild.id)
        if conf is None:
            await ctx.send("Account linking isn't set up for this server yet.")
            return

        # Fast path: everything given inline.
        if account_type and username:
            kind, payload = await self._do_link(ctx.guild, ctx.author, conf,
                                                account_type, username)
            if kind == "pending":
                await ctx.send(ctx.author.mention, embed=payload,
                               allowed_mentions=discord.AllowedMentions.none())
            else:
                await ctx.send(payload, allowed_mentions=discord.AllowedMentions.none())
            return

        types = [t.lower() for t in (conf.get("types") or [])]
        mc_off = not self._mc_feature_on(ctx.guild.id)
        if mc_off:
            # Feature off = minecraft doesn't exist here: not in the dropdown,
            # not acceptable inline.
            types = [t for t in types if t != "minecraft"]

        # A type named inline (just missing the username) skips the dropdown.
        single = None
        if account_type:
            single = account_type.lower().strip()
            if single == "minecraft" and mc_off:
                await ctx.send("Minecraft linking is turned off in this server.")
                return
            if types and single not in types:
                await ctx.send(f"This server supports linking: **{', '.join(types)}**.")
                return
        elif not types:
            if mc_off and conf.get("types"):
                # The allow-list only had minecraft, and it's switched off.
                await ctx.send("Minecraft linking is turned off in this server.")
            else:
                # Bare $link, and this server allows any type: no list to offer.
                await ctx.send("Usage: `$link <account type> <username>`, "
                               "e.g. `$link roblox builderman`.")
            return
        else:
            # Types they already linked here don't belong in the picker.
            # ($link <type> <username> still swaps one on purpose.)
            linked = {l.get("type") for l in self._links_for(ctx.author.id, ctx.guild.id)}
            remaining = [t for t in types if t not in linked]
            if not remaining:
                await ctx.send("You've already linked everything this server offers "
                               f"({', '.join('**' + t + '**' for t in types)}). "
                               "`$unlink` removes one, or `$link <type> <username>` "
                               "swaps an account.")
                return
            types = remaining

        # Guided flow, $project-delete style: a dropdown of the games this
        # server supports, then a popup form asks for the username. Discord
        # only lets a modal open from an interaction, hence the hop.
        view = discord.ui.View(timeout=60)

        async def open_modal(interaction, chosen_type):
            if interaction.user.id != ctx.author.id:
                await interaction.response.send_message(
                    "Only the person who asked can use this. Run `$link` yourself!",
                    ephemeral=True)
                return
            await interaction.response.send_modal(
                LinkUsernameModal(self, conf, chosen_type))

        if single:
            button = discord.ui.Button(label=f"Link your {single.capitalize()} account",
                                       emoji="🔗", style=discord.ButtonStyle.primary)

            async def clicked(interaction):
                await open_modal(interaction, single)

            button.callback = clicked
            view.add_item(button)
        else:
            select = discord.ui.Select(
                placeholder="Which account do you want to link?",
                options=[discord.SelectOption(label=t.capitalize(), value=t,
                                              emoji=self.TYPE_EMOJI.get(t, "🎮"))
                         for t in types][:25])

            async def chosen(interaction):
                await open_modal(interaction, select.values[0])

            select.callback = chosen
            view.add_item(select)
        await ctx.send("Let's get you linked:", view=view)

    async def _run_verify(self, guild, member, conf):
        """Check every pending link through its game's proof checker
        (VERIFIERS registry). Returns one result line per link -- shared by
        $verify and the pinned Verify button."""
        pending = [l for l in self._links_for(member.id, guild.id)
                   if not l.get("verified") and l.get("code")]
        lines = []
        for link in sorted(pending, key=lambda l: l.get("type", "")):
            verifier = self.VERIFIERS.get(link.get("type"))
            if verifier is None:
                # A pending link of a type that no longer has a proof flow.
                continue
            game = link["type"].capitalize()
            try:
                ok, fail_text = await getattr(self, verifier["checker"])(link)
            except Exception:
                lines.append(f"⚠️ I couldn't reach {game} just now. "
                             "Try again in a moment.")
                continue
            if not ok:
                lines.append(fail_text)
                continue
            # Passed: keep the game-specific extras (ids etc.), drop the code.
            keep = {k: v for k, v in link.items()
                    if k not in ("_id", "user_id", "guild_id", "type", "username",
                                 "linked_at", "verified", "code", "proof")}
            keep.update({"verified": True, "proof": verifier["proof"]})
            self._save_link(member.id, guild.id, link["type"],
                            link["username"], keep)
            notes = await self._apply_grants(guild, member, conf,
                                             link["type"], link["username"])
            msg = (f"✅ Verified! **{link['username']}** belongs to {member.mention}. "
                   "You can delete the code from your profile now.")
            if notes:
                msg += " Also: " + ", and ".join(notes) + "."
            lines.append(msg)
        return lines

    @commands.command(name="verify")
    @commands.guild_only()
    async def verify(self, ctx):
        """Finish pending links: every one is checked through its own game's
        proof checker (VERIFIERS registry)."""
        conf = self._conf(ctx.guild.id)
        if conf is None:
            await ctx.send("Account linking isn't set up for this server yet.")
            return
        lines = await self._run_verify(ctx.guild, ctx.author, conf)
        if not lines:
            await ctx.send("You have nothing waiting to be verified. "
                           "Start with `$link`.")
            return
        await ctx.send("\n".join(lines), allowed_mentions=discord.AllowedMentions.none())

    async def verify_button(self, interaction):
        """The pinned Verify button. Pending proof gets checked; otherwise
        the link picker (or straight to the username modal when the server
        offers one type). Every reply is ephemeral -- the channel stays
        exactly as pinned."""
        guild = interaction.guild
        conf = self._conf(guild.id)
        if conf is None:
            await interaction.response.send_message(
                "Account linking isn't set up for this server yet.", ephemeral=True)
            return
        member = interaction.user
        if any(not l.get("verified") and l.get("code")
               and l.get("type") in self.VERIFIERS
               for l in self._links_for(member.id, guild.id)):
            await interaction.response.defer(ephemeral=True)
            lines = await self._run_verify(guild, member, conf)
            await interaction.followup.send(
                "\n".join(lines) or "Nothing left to verify.", ephemeral=True)
            return

        types = [t.lower() for t in (conf.get("types") or [])]
        if not self._mc_feature_on(guild.id):
            types = [t for t in types if t != "minecraft"]
        linked = {l.get("type") for l in self._links_for(member.id, guild.id)}
        remaining = [t for t in types if t not in linked]
        if not remaining:
            if linked:
                await interaction.response.send_message(
                    "You're all set: everything this server offers is already "
                    "linked to you. `$unlink` removes one if you need a redo.",
                    ephemeral=True)
            else:
                await interaction.response.send_message(
                    "This server hasn't chosen any linkable account types yet.",
                    ephemeral=True)
            return
        if len(remaining) == 1:
            await interaction.response.send_modal(
                LinkUsernameModal(self, conf, remaining[0]))
            return
        view = discord.ui.View(timeout=60)
        select = discord.ui.Select(
            placeholder="Which account do you want to link?",
            options=[discord.SelectOption(label=t.capitalize(), value=t,
                                          emoji=self.TYPE_EMOJI.get(t, "🎮"))
                     for t in remaining][:25])

        async def chosen(inner):
            await inner.response.send_modal(
                LinkUsernameModal(self, conf, select.values[0]))

        select.callback = chosen
        view.add_item(select)
        await interaction.response.send_message("Let's get you linked:",
                                                view=view, ephemeral=True)

    @commands.command(name="unlink")
    @commands.guild_only()
    async def unlink(self, ctx, account_type: str = None):
        """Remove a linked account: bare $unlink picks from your links, or
        $unlink <type>."""
        links = self._links_for(ctx.author.id, ctx.guild.id)
        if not links:
            await ctx.send("You don't have any linked accounts in this server yet. "
                           "`$link` sets one up.")
            return

        done_msg = ("🔗 Unlinked your **{}** account. "
                    "(Roles and nicknames aren't changed by unlinking.)")

        # Fast path: type given inline.
        if account_type:
            account_type = account_type.lower().strip()
            doomed = next((l for l in links if l.get("type") == account_type), None)
            if doomed is None:
                have = ", ".join(sorted(l.get("type", "?") for l in links))
                await ctx.send(f"You don't have a **{account_type}** account linked "
                               f"in this server. You have: **{have}**.")
                return
            self._remove_link(ctx.author.id, ctx.guild.id, account_type)
            note = await self._mc_unlink_note(ctx.guild, doomed)
            await ctx.send(done_msg.format(account_type) + note)
            return

        # Guided flow, $project-delete style: a dropdown of everything they
        # have linked.
        view = discord.ui.View(timeout=60)

        async def do_unlink(interaction, chosen_type):
            if interaction.user.id != ctx.author.id:
                await interaction.response.send_message(
                    "Only the person who asked can use this. Run `$unlink` yourself!",
                    ephemeral=True)
                return
            view.stop()
            doomed = next((l for l in links if l.get("type") == chosen_type), None)
            self._remove_link(ctx.author.id, ctx.guild.id, chosen_type)
            # RCON can take a moment, so acknowledge before the whitelist work.
            await interaction.response.defer(ephemeral=True)
            note = await self._mc_unlink_note(ctx.guild, doomed)
            await interaction.followup.send(done_msg.format(chosen_type) + note,
                                            ephemeral=True)
            try:
                await interaction.message.delete()
            except discord.HTTPException:
                pass

        select = discord.ui.Select(
            placeholder="Which account do you want to unlink?",
            options=[discord.SelectOption(
                        label=l.get("type", "?").capitalize(),
                        value=l.get("type", "?"),
                        description=str(l.get("username", ""))[:100],
                        emoji=self.TYPE_EMOJI.get(l.get("type"), "🎮"))
                     for l in sorted(links, key=lambda x: x.get("type", ""))][:25])

        async def chosen(interaction):
            await do_unlink(interaction, select.values[0])

        select.callback = chosen
        view.add_item(select)
        await ctx.send("Pick the account to unlink:", view=view)

    @commands.command(name="lookup", aliases=["accounts"])
    @commands.guild_only()
    async def lookup(self, ctx, *, member: discord.Member):
        """Staff: see the accounts a member has linked. $lookup <member>"""
        if not self._is_mod(ctx.author):
            await ctx.send("Only moderators can look up linked accounts.")
            return
        links = self._links_for(member.id, ctx.guild.id)
        embed = discord.Embed(
            title=f"🔗 Linked accounts · {member.display_name}",
            colour=0xFFB7C5,
        )
        embed.set_thumbnail(url=member.display_avatar.url)

        # Discord identity: the name behind any nickname, plus account/join ages.
        identity = [f"Username: **{member.name}**"]
        if member.global_name and member.global_name != member.name:
            identity.append(f"Display name: **{member.global_name}**")
        if member.nick:
            identity.append(f"Server nickname: **{member.nick}**")
        created = int(member.created_at.timestamp())
        identity.append(f"Account created: <t:{created}:D> (<t:{created}:R>)")
        if member.joined_at:
            joined = int(member.joined_at.timestamp())
            identity.append(f"Joined this server: <t:{joined}:D> (<t:{joined}:R>)")
        embed.add_field(name="Discord", value="\n".join(identity), inline=False)

        if not links:
            embed.description = "No accounts linked."
        for l in sorted(links, key=lambda x: x.get("type", "")):
            value = f"**{l.get('username', '?')}**"
            if l.get("roblox_id"):
                value += f" · [profile](https://www.roblox.com/users/{l['roblox_id']}/profile)"
            if l.get("minecraft_uuid"):
                value += f" · [NameMC](https://namemc.com/profile/{l['minecraft_uuid']})"
            if l.get("verified") is False:
                value += " · ⏳ pending verification"
            elif l.get("proof") == "self-declared":
                value += " · self-declared"
            if l.get("linked_at"):
                value += f" · linked <t:{l['linked_at']}:R>"
            if l.get("type") == "roblox":
                # Placeholder until the game reports real session data into the
                # link doc's last_in_game field (unix timestamp).
                if l.get("last_in_game"):
                    value += f"\nLast seen in game: <t:{int(l['last_in_game'])}:R>"
                else:
                    value += "\nLast seen in game: no data yet"
            embed.add_field(name=l.get("type", "?").capitalize(), value=value, inline=False)
        await ctx.send(embed=embed)

    @lookup.error
    async def lookup_error(self, ctx, error):
        if isinstance(error, commands.MissingRequiredArgument):
            await ctx.send("Usage: `$lookup <member>`")
        elif isinstance(error, commands.BadArgument):
            await ctx.send("Could not find that member.")

    # ------------------- $mcroles (role sync config) -------------------

    async def mcroles_set(self, guild, role, group):
        """Save a role -> group mapping and apply it to linked holders now.
        Shared by the panel's modal, the inline command, and the web UI's
        semantics. Returns the confirmation text."""
        self.mongo.client[self.db][self.config_col].update_one(
            {"guild_id": str(guild.id)},
            {"$set": {f"minecraft.role_groups.{role.id}": group}}, upsert=True)
        mc = self._mc_conf(self._conf(guild.id)) or {}
        try:
            # Harmless when the group already exists; its PERMISSIONS are
            # still configured in LuckPerms itself.
            await self._mc_rcon(mc, f"lp creategroup {group}")
        except Exception:
            return (f"⛏️ Saved: {role.mention} syncs to **{group}**, but the "
                    "Minecraft server is unreachable right now; the sync "
                    "catches up automatically.")
        applied = 0
        for member, username in self._mc_linked_entries(guild):
            if any(r.id == role.id for r in member.roles):
                await self._lp_apply(mc, member, username)
                applied += 1
        msg = f"⛏️ {role.mention} now syncs to LuckPerms group **{group}**."
        if applied:
            msg += f" Applied to {applied} linked member{'s' if applied != 1 else ''}."
        return msg

    async def mcroles_remove(self, guild, role_id):
        """Drop a mapping; if its group isn't mapped by any other role, take
        it away from the linked members too. Returns the confirmation text."""
        mc = self._mc_conf(self._conf(guild.id)) or {}
        group = (mc.get("role_groups") or {}).get(str(role_id))
        if group is None:
            return "That role isn't mapped to anything."
        self.mongo.client[self.db][self.config_col].update_one(
            {"guild_id": str(guild.id)},
            {"$unset": {f"minecraft.role_groups.{role_id}": ""}})
        mc = self._mc_conf(self._conf(guild.id)) or {}
        if group not in set((mc.get("role_groups") or {}).values()):
            for _member, username in self._mc_linked_entries(guild):
                try:
                    await self._mc_rcon(
                        mc, f"lp user {self._lp_target(mc, username)} "
                            f"parent remove {group}")
                except Exception:
                    break   # unreachable; nothing more to strip right now
        role = guild.get_role(int(role_id))
        name = role.name if role else "a deleted role"
        return (f"🗑️ **{name}** no longer syncs to **{group}**, and I took "
                "the group off the linked members.")

    @commands.command(name="mcroles")
    @commands.guild_only()
    async def mcroles(self, ctx, action: str = None, role_arg: str = None,
                      *, group: str = None):
        """Map Discord roles to LuckPerms groups: bare $mcroles for the
        panel, or $mcroles set <@role> <group> / remove <@role>."""
        fm = self.client.get_cog("FeatureManager")
        if fm is None or not fm.is_manager(ctx.author):
            await ctx.send("Only the owner, admins, or bot managers can manage "
                           "the Minecraft role sync.")
            return
        mc = self._mc_conf(self._conf(ctx.guild.id))
        if mc is None:
            await ctx.send("This server has no Minecraft server configured yet "
                           "(the accounts config needs a `minecraft` block first).")
            return
        if not self._mc_feature_on(ctx.guild.id):
            await ctx.send("The **minecraft** feature is turned off in this server.")
            return

        # Inline fast paths.
        if action:
            action = action.lower()
            if action not in ("set", "remove") or not role_arg:
                await ctx.send("Usage: `$mcroles` for the panel, or "
                               "`$mcroles set <@role> <group>` / `$mcroles remove <@role>`.")
                return
            try:
                role = await commands.RoleConverter().convert(ctx, role_arg)
            except commands.BadArgument:
                await ctx.send(f"I couldn't find a role called **{role_arg}**.")
                return
            if action == "set":
                group = (group or "").strip().lower()
                if not GROUP_RE.fullmatch(group):
                    await ctx.send("Group names are 1-36 letters, numbers, "
                                   "dashes, or underscores: `$mcroles set <@role> <group>`.")
                    return
                await ctx.send(await self.mcroles_set(ctx.guild, role, group),
                               allowed_mentions=discord.AllowedMentions.none())
            else:
                await ctx.send(await self.mcroles_remove(ctx.guild, str(role.id)),
                               allowed_mentions=discord.AllowedMentions.none())
            return

        # The panel.
        groups = mc.get("role_groups") or {}
        lines = []
        for rid, grp in groups.items():
            role = ctx.guild.get_role(int(rid))
            lines.append(f"{role.mention if role else '(deleted role)'} → **{grp}**")
        embed = discord.Embed(
            title="⛏️ Minecraft role sync",
            description=("\n".join(lines) if lines else
                         "Nothing mapped yet. A mapping keeps a Discord role's "
                         "holders in a LuckPerms group, for members with a "
                         "linked Minecraft account."),
            colour=0xFFB7C5,
        )
        embed.set_footer(text="What each group can DO in game is configured in "
                              "LuckPerms itself, not here.")
        view = discord.ui.View(timeout=120)

        async def invoker_only(interaction):
            if interaction.user.id != ctx.author.id:
                await interaction.response.send_message(
                    "Only the person who asked can use this. Run `$mcroles` yourself!",
                    ephemeral=True)
                return False
            return True

        add_btn = discord.ui.Button(label="Add mapping", emoji="➕",
                                    style=discord.ButtonStyle.primary)
        rem_btn = discord.ui.Button(label="Remove mapping", emoji="➖",
                                    style=discord.ButtonStyle.secondary)

        async def add_cb(interaction):
            if not await invoker_only(interaction):
                return
            picker = discord.ui.View(timeout=60)
            role_sel = discord.ui.RoleSelect(placeholder="Which Discord role should sync?")

            async def picked(inner):
                if inner.user.id != ctx.author.id:
                    await inner.response.send_message(
                        "Only the person who asked can pick.", ephemeral=True)
                    return
                await inner.response.send_modal(
                    LuckPermsGroupModal(self, role_sel.values[0]))

            role_sel.callback = picked
            picker.add_item(role_sel)
            await interaction.response.send_message(
                "Pick the Discord role to sync:", view=picker, ephemeral=True)

        async def rem_cb(interaction):
            if not await invoker_only(interaction):
                return
            current = (self._mc_conf(self._conf(ctx.guild.id)) or {}).get("role_groups") or {}
            if not current:
                await interaction.response.send_message("Nothing is mapped yet.",
                                                        ephemeral=True)
                return
            options = []
            for rid, grp in list(current.items())[:25]:
                role = ctx.guild.get_role(int(rid))
                label = f"{role.name if role else 'deleted role'} → {grp}"
                options.append(discord.SelectOption(label=label[:100], value=rid))
            picker = discord.ui.View(timeout=60)
            sel = discord.ui.Select(placeholder="Remove which mapping?", options=options)

            async def chosen(inner):
                if inner.user.id != ctx.author.id:
                    await inner.response.send_message(
                        "Only the person who asked can pick.", ephemeral=True)
                    return
                await inner.response.defer(ephemeral=True)
                msg = await self.mcroles_remove(ctx.guild, sel.values[0])
                await inner.followup.send(msg, ephemeral=True)

            sel.callback = chosen
            picker.add_item(sel)
            await interaction.response.send_message("Pick the mapping to remove:",
                                                    view=picker, ephemeral=True)

        add_btn.callback = add_cb
        rem_btn.callback = rem_cb
        view.add_item(add_btn)
        view.add_item(rem_btn)
        await ctx.send(embed=embed, view=view)


async def setup(client):
    await client.add_cog(AccountLink(client))
