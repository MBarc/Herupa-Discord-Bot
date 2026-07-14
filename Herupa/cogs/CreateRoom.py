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
        self.createRoomName = "🔧create room🔧"
        self.bypassRoles = ["deputy", "sheriff"]
        self.AFKChannelName = "💀AFK💀"
        self.dbName = "createroom"
        self.mongo_instance = HerupaMongo()

    # ----------------------------- helpers -----------------------------

    def _ensure_privacy_doc(self, memberID):
        """Guarantee the member has a privacy_mode document (defaults to public)."""
        if not self.mongo_instance.doesCollectionExist(database_name=self.dbName, collection_name=memberID):
            self.mongo_instance.createCollection(database_name=self.dbName, collection_name=memberID)
            self.mongo_instance.addCollectionEntry(
                database_name=self.dbName, collection_name=memberID, payload={"privacy_mode": "public"})

    def _get_privacy_doc(self, memberID):
        self._ensure_privacy_doc(memberID)
        return self.mongo_instance.findSpecificDocumentsByKey(
            database_name=self.dbName, collection_name=memberID, key="privacy_mode")[0]

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

    def _favorite_ids(self, memberID):
        return [int(f["id"]) for f in self.mongo_instance.returnCollectionEntries(
            database_name="favorites", collection_name=memberID)]

    def _build_overwrites(self, guild, owner, mode):
        """Build the full permission-overwrite map for a room in one shot (no API
        calls) so it can be applied atomically at channel creation / edit — much
        faster than a sequence of set_permissions calls. Shared by room creation
        and the live $crpm switch so the two can't drift apart."""
        allow = self._room_overwrite()
        overwrites = {}

        # Newbies can never see an auto-created room, in either mode.
        newbie = discord.utils.get(guild.roles, name="newbie")
        if newbie:
            overwrites[newbie] = discord.PermissionOverwrite(view_channel=False)

        if mode == "public":
            overwrites[guild.default_role] = allow
            return overwrites

        # private
        overwrites[guild.default_role] = discord.PermissionOverwrite(view_channel=False)
        overwrites[owner] = allow
        for fav_id in self._favorite_ids(str(owner.id)):
            fav = guild.get_member(fav_id)
            if fav:
                overwrites[fav] = allow
        for role_name in self.bypassRoles:
            role = discord.utils.get(guild.roles, name=role_name)
            if role:
                overwrites[role] = allow
        return overwrites

    def _find_owned_room(self, guild, owner):
        """Return the member's auto-created room (matched by its "MODE - name"
        title) or None. Works whether or not they're currently connected to it."""
        trigger = discord.utils.get(guild.channels, name=self.createRoomName)
        category = trigger.category if trigger else None
        if category is None:
            return None
        suffix = f" - {self._room_label(owner)}"
        for vc in category.voice_channels:
            if vc.name in (self.createRoomName, self.AFKChannelName):
                continue
            if vc.name.endswith(suffix) and (vc.name.startswith("PUBLIC") or vc.name.startswith("PRIVATE")):
                return vc
        return None

    # ----------------------------- command -----------------------------

    @commands.command(name='crpm',
                      description='Switches the privacy mode of your create-room, live if you have one.',
                      brief='Switches your room privacy mode.')
    async def crpm(self, ctx):
        memberID = str(ctx.author.id)
        doc = self._get_privacy_doc(memberID)
        new_mode = "private" if doc["privacy_mode"] == "public" else "public"

        self.mongo_instance.updateDocumentsByKey(
            database_name=self.dbName, collection_name=memberID,
            IDkey="_id", IDvalue=doc["_id"], key="privacy_mode", value=new_mode)

        room = self._find_owned_room(ctx.guild, ctx.author)
        if room is None:
            await ctx.channel.send(
                f"Your privacy mode is now **{new_mode.upper()}**. It'll apply to your next room.")
            return

        try:
            overwrites = self._build_overwrites(ctx.guild, ctx.author, new_mode)
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

        # Member joined the "create room" trigger -> spin up their room.
        if after.channel and after.channel.name == self.createRoomName:
            memberID = str(member.id)
            privacyMode = self._get_privacy_doc(memberID)["privacy_mode"]

            channelName = f"{privacyMode.upper()} - {self._room_label(member)}"
            # Create the room WITH all its permissions in a single call, then move
            # the member immediately — no waiting on a chain of overwrite edits.
            overwrites = self._build_overwrites(member.guild, member, privacyMode)
            memberChannel = await after.channel.category.create_voice_channel(channelName, overwrites=overwrites)
            await member.move_to(memberChannel)

        # An auto-created room emptied out -> delete it to keep things tidy.
        trigger = discord.utils.get(member.guild.channels, name=self.createRoomName)
        if (before.channel and len(before.channel.members) == 0 and trigger
                and before.channel.category == trigger.category
                and before.channel.name != self.createRoomName
                and before.channel.name != self.AFKChannelName):
            await before.channel.delete()


async def setup(client):
    await client.add_cog(CreateRoom(client))
