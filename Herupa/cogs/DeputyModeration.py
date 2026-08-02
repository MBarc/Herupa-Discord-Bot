'''
Purpose: Restricted moderation commands for the junior mod tier.

Junior mods (Chill Club: deputies; TerraNova: the Moderation Team) have NO
native Kick/Ban permission on their Discord role, so these commands (which act
with Herupa's own permissions) are their only way to remove a member. That
routing is what makes the limits below enforceable:

  - Kicks and bans share ONE budget: 3 removals per rolling hour, per mod
    (per server).
  - A restricted mod may not kick/ban another staff member.
  - Every action is logged to the server's mod-log channel.

Unrestricted roles (Chill Club: sheriff / head chill) and native admins skip
the budget and the staff-target check entirely.

MULTI-SERVER: driven by per-guild config in Mongo (db "moderation",
collection "config", one doc per guild_id):

    {
      "guild_id": "645847490020638720",
      "restricted_roles": ["deputy"],                  # the limited tier
      "unrestricted_roles": ["sheriff", "head chill"], # skip all limits
      "protected_roles": ["deputy", "sheriff", ...],   # restricted mods can't target these
      "log_channel": "👮law-chat👮",                    # channel NAME in the guild
      "removal_limit": 3,
      "removal_window_seconds": 3600,
      "escalation_name": "a Sheriff",                  # flavor for "limit reached" messages
    }

Config is read from Mongo on every command (moderation commands are rare), so
edits apply immediately — no reload needed. Guilds with no config doc get a
"not set up" message. Role/channel matching is case-insensitive.
'''

from discord.ext import commands
from discord.utils import get
import discord

import sys
import os
import time

# Add the parent directory to the path so we can import our custom library
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
sys.path.append(parent_dir)

from tools.HerupaMongo import HerupaMongo


class DeputyModeration(commands.Cog):

    def __init__(self, client):
        self.client = client

        self.dbName = "moderation"
        self.config_collection = "config"
        self.removals_collection = "deputy_removals"
        self.mongo_instance = HerupaMongo()

    # ----------------------------- helpers -----------------------------

    def _conf(self, guild_id):
        gid = str(guild_id)
        for doc in self.mongo_instance.returnCollectionEntries(
                database_name=self.dbName, collection_name=self.config_collection):
            if doc.get("guild_id") == gid:
                return doc
        return None

    def _has_role(self, member, names):
        low = {n.lower() for n in names}
        return any(role.name.lower() in low for role in member.roles)

    def _is_unrestricted(self, member, conf):
        return self._has_role(member, conf.get("unrestricted_roles", [])) \
            or member.guild_permissions.administrator

    def _is_restricted_mod(self, member, conf):
        return self._has_role(member, conf.get("restricted_roles", []))

    def _is_protected(self, member, conf):
        return self._has_role(member, conf.get("protected_roles", []))

    def is_mod(self, member):
        """Public: is this member on the guild's moderation ladder at all?
        Used by other cogs (Help, AccountLink) as the one definition of 'mod'."""
        if member.guild_permissions.administrator:
            return True
        conf = self._conf(member.guild.id)
        if conf is None:
            return False
        return self._is_unrestricted(member, conf) or self._is_restricted_mod(member, conf)

    def _recent_removal_count(self, guild_id, mod_id, window_seconds):
        '''Prune expired records, then count this mod's removals in-window.'''
        cutoff = int(time.time()) - window_seconds

        # Drop everything older than the window so the collection stays small
        # and every remaining record is, by definition, inside the window.
        self.mongo_instance.removeCollectionEntry(
            database_name=self.dbName,
            collection_name=self.removals_collection,
            payload={"timestamp": {"$lt": cutoff}},
        )

        entries = self.mongo_instance.returnCollectionEntries(
            database_name=self.dbName,
            collection_name=self.removals_collection,
        )
        # Pre-multi-server records have no guild_id; those were all Chill Club's,
        # and they expire within the hour anyway, so a missing value just counts
        # toward whichever guild asks — harmless for one transition window.
        return sum(1 for e in entries
                   if e.get("deputy_id") == mod_id
                   and e.get("guild_id", str(guild_id)) == str(guild_id))

    def _record_removal(self, guild_id, mod_id, target_id, action, reason):
        self.mongo_instance.addCollectionEntry(
            database_name=self.dbName,
            collection_name=self.removals_collection,
            payload={
                "guild_id": str(guild_id),
                "deputy_id": mod_id,
                "target_id": target_id,
                "action": action,
                "reason": reason,
                "timestamp": int(time.time()),
            },
        )

    async def _log(self, guild, conf, text):
        name = (conf.get("log_channel") or "").lower()
        log_channel = next(
            (c for c in guild.text_channels if c.name.lower() == name), None)
        if log_channel:
            await log_channel.send(text)

    async def _remove(self, ctx, member, reason, action):
        '''Shared flow for kick and ban. `action` is "kick" or "ban".'''

        author = ctx.author
        conf = self._conf(ctx.guild.id)
        if conf is None:
            await ctx.send("Moderation commands aren't set up for this server yet.")
            return

        # 1) Authorisation: only the mod ladder may use these at all.
        if not (self._is_unrestricted(author, conf) or self._is_restricted_mod(author, conf)):
            await ctx.send("You do not have the required role to use this command.")
            return

        restricted = self._is_restricted_mod(author, conf) \
            and not self._is_unrestricted(author, conf)

        # 2) Restricted mods cannot act on fellow staff.
        if restricted and self._is_protected(member, conf):
            await ctx.send(f"You cannot {action} another staff member.")
            return

        # No one should be able to remove themselves via the command.
        if member.id == author.id:
            await ctx.send("You cannot use this command on yourself.")
            return

        # 3) Restricted mods share a kick+ban budget per rolling window.
        limit = conf.get("removal_limit", 3)
        window = conf.get("removal_window_seconds", 3600)
        escalation = conf.get("escalation_name", "a senior moderator")
        if restricted:
            used = self._recent_removal_count(ctx.guild.id, str(author.id), window)
            if used >= limit:
                await ctx.send(
                    f"You have hit your limit of {limit} removals per hour. "
                    f"{escalation[0].upper()}{escalation[1:]} must take it from here."
                )
                await self._log(
                    ctx.guild, conf,
                    f"⚠️ {author} was blocked from {action}ing {member}: hourly removal "
                    f"limit ({limit}) reached.",
                )
                return

        # 4) Perform the action with Herupa's permissions.
        try:
            if action == "ban":
                await member.ban(reason=reason, delete_message_seconds=0)
            else:
                await member.kick(reason=reason)
        except discord.Forbidden:
            await ctx.send(f"I do not have permission to {action} this member.")
            return
        except discord.HTTPException as e:
            await ctx.send(f"Failed to {action} the member. Error: {e}")
            return

        # 5) Record (restricted mods only) and log (everyone).
        if restricted:
            self._record_removal(ctx.guild.id, str(author.id), str(member.id), action, reason)
            remaining = limit - self._recent_removal_count(ctx.guild.id, str(author.id), window)
            tail = f" ({remaining} removals left this hour)"
        else:
            tail = ""

        await ctx.send(
            f"{member} has been {action}ned. Reason: {reason}{tail}",
            delete_after=10,
        )
        await self._log(
            ctx.guild, conf,
            f"{member} was {action}ned by {author}. Reason: {reason}",
        )

    # ----------------------------- commands -----------------------------

    @commands.command(name="kick", description="Kick a member (rate-limited for junior mods).")
    @commands.guild_only()
    async def kick(self, ctx, member: discord.Member, *, reason: str):
        await self._remove(ctx, member, reason, "kick")

    @commands.command(name="ban", description="Ban a member (rate-limited for junior mods).")
    @commands.guild_only()
    async def ban(self, ctx, member: discord.Member, *, reason: str):
        await self._remove(ctx, member, reason, "ban")

    @kick.error
    async def kick_error(self, ctx, error):
        await self._usage_error(ctx, error, "kick")

    @ban.error
    async def ban_error(self, ctx, error):
        await self._usage_error(ctx, error, "ban")

    async def _usage_error(self, ctx, error, action):
        if isinstance(error, commands.MissingRequiredArgument):
            await ctx.send(f"Usage: ${action} <member> <reason>")
        elif isinstance(error, commands.BadArgument):
            await ctx.send("Could not find that member.")


async def setup(client):
    await client.add_cog(DeputyModeration(client))
