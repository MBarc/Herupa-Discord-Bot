'''
Purpose: Auto-create a personal voice room when a member joins the "create room"
VC, and let them switch that room's privacy mode live with $crpm.

Privacy modes:
  - public  : @everyone can join.
  - private : only the owner, their favorites, and bypass (mod) roles can join.

$crpm toggles the stored mode AND, if the member currently has a room, applies
the new mode to it live (re-permissioning and renaming). Switching to private
blocks new disallowed members from joining, but never disconnects anyone who is
already in the room.

MULTI-SERVER: driven by per-guild config in Mongo (db "createroom",
collection "config", one doc per guild_id):

    {
      "guild_id": "645847490020638720",
      "trigger_channel": "🔧create room🔧",  # joining this VC spawns a room
      "afk_channel": "💀AFK💀",              # never auto-deleted (None if no AFK VC
                                             #   lives in the rooms category)
      "bypass_roles": ["deputy", "sheriff"], # may join private rooms
      "hidden_roles": ["newbie"],            # can never see auto-created rooms
    }

Rooms are created in the trigger channel's own category. A member's privacy
mode and custom room name are per member (global), not per server. Configs are
cached at load; `$roomreload` (admin) re-reads them after a Mongo edit. Guilds
with no config doc are ignored entirely.
'''
import discord
from discord.ext import commands

import sys
import os
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
sys.path.append(parent_dir)
from tools.HerupaMongo import HerupaMongo


class CreateRoom(commands.Cog):

    def __init__(self, client):
        self.client = client
        self.dbName = "createroom"
        self.config_col = "config"
        self.mongo_instance = HerupaMongo()
        self._configs = {}

    async def cog_load(self):
        self._load_configs()

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

    # ----------------------------- helpers -----------------------------

    def _privacy_col(self):
        # Privacy mode is PER SERVER per member (a private room in one server
        # says nothing about your rooms elsewhere).
        return self.mongo_instance.client[self.dbName]["privacy"]

    def _get_privacy(self, guild_id, member_id):
        doc = self._privacy_col().find_one(
            {"guild_id": str(guild_id), "member_id": str(member_id)})
        return doc["privacy_mode"] if doc else "public"

    def _set_privacy(self, guild_id, member_id, mode):
        self._privacy_col().update_one(
            {"guild_id": str(guild_id), "member_id": str(member_id)},
            {"$set": {"privacy_mode": mode}}, upsert=True)

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

    def _build_overwrites(self, guild, owner, mode, conf):
        """Build the full permission-overwrite map for a room in one shot (no API
        calls) so it can be applied atomically at channel creation / edit — much
        faster than a sequence of set_permissions calls. Shared by room creation
        and the live $crpm switch so the two can't drift apart."""
        allow = self._room_overwrite()
        overwrites = {}

        # Hidden roles (e.g. Chill Club newbies) can never see an auto-created
        # room, in either mode.
        for role_name in conf.get("hidden_roles", []):
            role = discord.utils.get(guild.roles, name=role_name)
            if role:
                overwrites[role] = discord.PermissionOverwrite(view_channel=False)

        if mode == "public":
            overwrites[guild.default_role] = allow
            return overwrites

        # private
        overwrites[guild.default_role] = discord.PermissionOverwrite(view_channel=False)
        overwrites[owner] = allow
        for fav_id in self._favorite_ids(guild.id, str(owner.id)):
            fav = guild.get_member(fav_id)
            if fav:
                overwrites[fav] = allow
        for role_name in conf.get("bypass_roles", []):
            role = discord.utils.get(guild.roles, name=role_name)
            if role:
                overwrites[role] = allow
        return overwrites

    def _find_owned_room(self, guild, owner, conf):
        """Return the member's auto-created room (matched by its "MODE - name"
        title) or None. Works whether or not they're currently connected to it."""
        trigger = discord.utils.get(guild.channels, name=conf["trigger_channel"])
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

    # ----------------------------- command -----------------------------

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
            overwrites = self._build_overwrites(ctx.guild, ctx.author, new_mode, conf)
            new_name = f"{new_mode.upper()} - {self._room_label(ctx.author)}"
            # One API call applies both the rename and every permission change.
            # Going private only blocks NEW joins; anyone already connected stays.
            await room.edit(name=new_name, overwrites=overwrites)
        except discord.Forbidden:
            await ctx.channel.send(
                f"Switched you to **{new_mode.upper()}**, but I couldn't update your live room (missing permissions).")
            return

        await ctx.channel.send(f"Your room is now **{new_mode.upper()}**.")

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
            await member.move_to(memberChannel)

        # An auto-created room emptied out -> delete it to keep things tidy.
        trigger = discord.utils.get(member.guild.channels, name=conf["trigger_channel"])
        if (before.channel and len(before.channel.members) == 0 and trigger
                and before.channel.category == trigger.category
                and before.channel.name != conf["trigger_channel"]
                and before.channel.name != conf.get("afk_channel")):
            await before.channel.delete()


async def setup(client):
    await client.add_cog(CreateRoom(client))
