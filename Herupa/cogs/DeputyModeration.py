'''
Purpose: Restricted moderation commands for Deputies.

Deputies have NO native Kick/Ban permission on their Discord role, so these
commands (which act with Herupa's own permissions) are their only way to
remove a member. That routing is what makes the limits below enforceable:

  - Kicks and bans share ONE budget: 3 removals per rolling hour, per deputy.
  - A deputy may not kick/ban another staff member.
  - Every action is logged to the law-chat channel.

Sheriff and Head Chill are unrestricted: they skip the budget and the
staff-target check entirely (and keep their native Kick/Ban besides).
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

        # --- Chill Club role model (single-server) ---
        self.deputy_role = "deputy"
        self.unrestricted_roles = ["sheriff", "head chill"]   # skip all limits
        # A deputy may not action anyone holding one of these roles.
        self.staff_roles = ["deputy", "sheriff", "head chill", "servants"]

        self.log_channel_name = "👮law-chat👮"

        # --- Rate limit: shared kick+ban budget per deputy ---
        self.removal_limit = 3
        self.removal_window_seconds = 60 * 60   # rolling one hour

        # --- Mongo persistence (survives bot restarts) ---
        self.dbName = "moderation"
        self.removals_collection = "deputy_removals"
        self.mongo_instance = HerupaMongo()

    # ----------------------------- helpers -----------------------------

    def _has_role(self, member, names):
        return any(role.name.lower() in names for role in member.roles)

    def _is_unrestricted(self, member):
        return self._has_role(member, self.unrestricted_roles)

    def _is_deputy(self, member):
        return self.deputy_role in [role.name.lower() for role in member.roles]

    def _is_staff(self, member):
        return self._has_role(member, self.staff_roles)

    def _recent_removal_count(self, deputy_id):
        '''Prune expired records, then count this deputy's removals in-window.'''
        cutoff = int(time.time()) - self.removal_window_seconds

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
        return sum(1 for e in entries if e.get("deputy_id") == deputy_id)

    def _record_removal(self, deputy_id, target_id, action, reason):
        self.mongo_instance.addCollectionEntry(
            database_name=self.dbName,
            collection_name=self.removals_collection,
            payload={
                "deputy_id": deputy_id,
                "target_id": target_id,
                "action": action,
                "reason": reason,
                "timestamp": int(time.time()),
            },
        )

    async def _log(self, guild, text):
        log_channel = get(guild.text_channels, name=self.log_channel_name)
        if log_channel:
            await log_channel.send(text)

    async def _remove(self, ctx, member, reason, action):
        '''Shared flow for kick and ban. `action` is "kick" or "ban".'''

        author = ctx.author

        # 1) Authorisation: only the mod ladder may use these at all.
        if not (self._is_unrestricted(author) or self._is_deputy(author)):
            await ctx.send("You do not have the required role to use this command.")
            return

        restricted = self._is_deputy(author) and not self._is_unrestricted(author)

        # 2) Deputies cannot act on fellow staff.
        if restricted and self._is_staff(member):
            await ctx.send(f"Deputies cannot {action} another staff member.")
            return

        # No one should be able to remove themselves via the command.
        if member.id == author.id:
            await ctx.send("You cannot use this command on yourself.")
            return

        # 3) Deputies share a 3-per-hour kick+ban budget.
        if restricted:
            used = self._recent_removal_count(str(author.id))
            if used >= self.removal_limit:
                await ctx.send(
                    f"You have hit your limit of {self.removal_limit} removals per hour. "
                    "A Sheriff must take it from here."
                )
                await self._log(
                    ctx.guild,
                    f"⚠️ {author} was blocked from {action}ing {member}: hourly removal "
                    f"limit ({self.removal_limit}) reached.",
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

        # 5) Record (deputies only) and log (everyone).
        if restricted:
            self._record_removal(str(author.id), str(member.id), action, reason)
            remaining = self.removal_limit - self._recent_removal_count(str(author.id))
            tail = f" ({remaining} removals left this hour)"
        else:
            tail = ""

        await ctx.send(
            f"{member} has been {action}ned. Reason: {reason}{tail}",
            delete_after=10,
        )
        await self._log(
            ctx.guild,
            f"{member} was {action}ned by {author}. Reason: {reason}",
        )

    # ----------------------------- commands -----------------------------

    @commands.command(name="kick", description="Kick a member (rate-limited for deputies).")
    async def kick(self, ctx, member: discord.Member, *, reason: str):
        await self._remove(ctx, member, reason, "kick")

    @commands.command(name="ban", description="Ban a member (rate-limited for deputies).")
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
