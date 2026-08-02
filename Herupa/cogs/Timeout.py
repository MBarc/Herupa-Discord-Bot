from discord.ext import commands
import discord
from datetime import timedelta

import sys
import os

current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
sys.path.append(parent_dir)

from tools.HerupaMongo import HerupaMongo


class Timeout(commands.Cog):
    '''$timeout, driven by the same per-guild config as DeputyModeration
    (Mongo db "moderation", collection "config"): restricted_roles may use it
    but are capped at timeout_cap_minutes; unrestricted_roles (and native
    admins) have no cap. Actions log to the guild's log_channel.'''

    def __init__(self, client):
        self.client = client
        self.dbName = "moderation"
        self.config_collection = "config"
        self.mongo_instance = HerupaMongo()

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

    @commands.command(name="timeout", aliases=["to"])
    @commands.guild_only()
    async def timeout(self, ctx, member: discord.Member, duration: int, *, reason: str):
        """
        Timeout a member for a specified duration with a reason.
        """
        conf = self._conf(ctx.guild.id)
        if conf is None:
            await ctx.send("Moderation commands aren't set up for this server yet.")
            return

        is_unrestricted = self._has_role(member=ctx.author, names=conf.get("unrestricted_roles", [])) \
            or ctx.author.guild_permissions.administrator
        is_restricted = self._has_role(member=ctx.author, names=conf.get("restricted_roles", []))

        # Check if the author is on the mod ladder at all
        if not (is_unrestricted or is_restricted):
            await ctx.send("You do not have the required role to use this command.")
            return

        # Restricted mods are capped; unrestricted roles are not.
        cap = conf.get("timeout_cap_minutes", 60)
        escalation = conf.get("escalation_name", "a senior moderator")
        if not is_unrestricted and duration > cap:
            await ctx.send(
                f"You can time a member out for at most {cap} minutes. "
                f"{escalation[0].upper()}{escalation[1:]} must apply a longer timeout."
            )
            return

        try:
            # Ensure a reason is provided
            if not reason:
                await ctx.send("You must provide a reason for the timeout.")
                return

            # Calculate the duration for the timeout
            timeout_duration = timedelta(minutes=duration)

            # Apply the timeout
            await member.timeout(timeout_duration, reason=reason)

            # Send a confirmation message
            await ctx.send(f"{member} has been timed out for {duration} minutes. Reason: {reason}", delete_after=10)

            # Log the timeout action
            name = (conf.get("log_channel") or "").lower()
            log_channel = next(
                (c for c in ctx.guild.text_channels if c.name.lower() == name), None)
            if log_channel:
                await log_channel.send(f"{member} was timed out by {ctx.author} for {duration} minutes. Reason: {reason}")
        except discord.Forbidden:
            await ctx.send("I do not have permission to timeout this member.")
        except discord.HTTPException as e:
            await ctx.send(f"Failed to timeout the member. Error: {e}")

    @timeout.error
    async def timeout_error(self, ctx, error):
        if isinstance(error, commands.MissingRequiredArgument):
            await ctx.send("Usage: $timeout <member> <duration (in minutes)> <reason>")
        elif isinstance(error, commands.BadArgument):
            await ctx.send("Invalid argument type.")


async def setup(client):
    await client.add_cog(Timeout(client))
