'''
Purpose: Per-server feature toggles.

$feature            -> list Herupa's features and whether they're on here
$feature off <name> -> turn a feature off in this server
$feature on <name>  -> turn it back on

Only the server owner, administrators, or holders of a manager role (default:
a role named "Bot Manager") may use it. State lives in Mongo (db "features",
collection "config", one doc per guild_id:
{"guild_id": ..., "disabled": ["leveling"], "manager_roles": ["bot manager"]}),
cached in-process; the command itself keeps cache and Mongo in sync, so no
reload step is needed.

Enforcement is two-layer:
  1. A global command check maps every command's cog to its feature (FEATURES
     below) and blocks commands of disabled features with a short notice.
  2. Listener-driven behavior can't be blocked that way, so those cogs ask
     this cog's is_enabled() directly: XP earning (Leveling / Leaderboard /
     WelcomeReward), the ticket panel buttons (TicketSystem), and room
     auto-creation (CreateRoom).

Other cogs may also use is_manager() as the definition of "bot manager".
'''

import discord
from discord.ext import commands, tasks

import sys
import os
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
sys.path.append(parent_dir)
from tools.HerupaMongo import HerupaMongo


# Feature name -> the cogs whose commands belong to it, and a human blurb.
FEATURES = {
    "leveling":   {"cogs": ["Leveling", "Leaderboard", "Daily", "Shop", "WelcomeReward"],
                   "desc": "XP earning, $rank, $daily, $leaderboard, and the level shop"},
    "tickets":    {"cogs": ["TicketSystem"], "desc": "the ticket panel and $whisper reports"},
    "rooms":      {"cogs": ["CreateRoom"], "desc": "auto-created voice rooms and $crpm"},
    "music":      {"cogs": ["Music"], "desc": "the Hibiki DJ crew"},
    "moderation": {"cogs": ["DeputyModeration", "Timeout"], "desc": "$kick, $ban, and $timeout"},
    "accounts":   {"cogs": ["AccountLink"], "desc": "$link, $verify, and $lookup"},
    # Sub-feature of accounts (no commands of its own): gates Minecraft
    # account linking entirely, plus the RCON whitelist sync for guilds
    # whose accounts config has a minecraft block.
    "minecraft": {"cogs": [], "desc": "Minecraft account linking and server whitelist sync"},
    "birthdays":  {"cogs": ["Birthday"], "desc": "$birthday and the daily wishes"},
    "counting":   {"cogs": ["Counting"], "desc": "the counting game"},
    "favorites":  {"cogs": ["Favorites"], "desc": "favorite pings on voice join"},
    "mock":       {"cogs": ["Mock"], "desc": "the $mock voice parrot"},
    "projects":   {"cogs": ["Projects"], "desc": "forum project boards, $task and $board"},
    # Sub-features of projects: no commands of their own (empty cogs), they
    # gate the daily automation pass in the Projects cog.
    "project-reminders": {"cogs": [], "desc": "DM assignees when their task is due today or tomorrow"},
    "project-nudges":    {"cogs": [], "desc": "daily overdue reminders inside task threads"},
    "project-digest":    {"cogs": [], "desc": "morning project summary to the digest channel ($project digest)"},
}
COG_TO_FEATURE = {cog: name for name, f in FEATURES.items() for cog in f["cogs"]}
DEFAULT_MANAGER_ROLES = ["bot manager"]


class FeatureManager(commands.Cog):

    def __init__(self, client):
        self.client = client
        self.db = "features"
        self.col = "config"
        self.mongo = HerupaMongo()
        self._disabled = {}   # guild_id (int) -> set of feature names
        self._managers = {}   # guild_id (int) -> configured manager role names

    async def cog_load(self):
        self._load()
        self.client.add_check(self._feature_check)
        self.refresh.start()

    async def cog_unload(self):
        self.client.remove_check(self._feature_check)
        self.refresh.cancel()

    @tasks.loop(seconds=30)
    async def refresh(self):
        # The web UI toggles features by writing Mongo directly, so the
        # in-process cache re-reads it every half minute.
        self._load()

    def _load(self):
        self._disabled, self._managers = {}, {}
        for doc in self.mongo.returnCollectionEntries(database_name=self.db,
                                                      collection_name=self.col):
            try:
                gid = int(doc["guild_id"])
            except (KeyError, TypeError, ValueError):
                continue
            self._disabled[gid] = {f.lower() for f in doc.get("disabled", [])}
            self._managers[gid] = [r.lower() for r in doc.get("manager_roles", [])]

    # ----------------------------- public API -----------------------------

    def is_enabled(self, guild_id, feature):
        return feature not in self._disabled.get(int(guild_id), set())

    def is_manager(self, member):
        """Owner, admin, or a configured manager role (default 'Bot Manager')."""
        if member.id == member.guild.owner_id or member.guild_permissions.administrator:
            return True
        allowed = set(self._managers.get(member.guild.id) or DEFAULT_MANAGER_ROLES)
        return any(r.name.lower() in allowed for r in member.roles)

    # ----------------------------- enforcement -----------------------------

    async def _feature_check(self, ctx):
        if ctx.guild is None or ctx.cog is None:
            return True
        feature = COG_TO_FEATURE.get(ctx.cog.qualified_name)
        if feature and not self.is_enabled(ctx.guild.id, feature):
            try:
                await ctx.send(f"The **{feature}** feature is turned off in this server.")
            except discord.HTTPException:
                pass
            return False
        return True

    # ----------------------------- commands -----------------------------

    @commands.group(name="feature", aliases=["features"], invoke_without_command=True)
    @commands.guild_only()
    async def feature(self, ctx):
        """List the features and their on/off state in this server."""
        if not self.is_manager(ctx.author):
            await ctx.send("Only the owner, admins, or bot managers can manage features.")
            return
        disabled = self._disabled.get(ctx.guild.id, set())
        embed = discord.Embed(
            title="⚙️ Herupa's Features",
            description="Toggle with `$feature off <name>` and `$feature on <name>`.",
            colour=0xFFB7C5,
        )
        for name, f in FEATURES.items():
            status = "⛔ off" if name in disabled else "✅ on"
            embed.add_field(name=f"{name}  ·  {status}", value=f["desc"], inline=False)
        await ctx.send(embed=embed)

    @feature.command(name="list")
    async def feature_list(self, ctx):
        await self.feature(ctx)

    async def _toggle(self, ctx, name, turn_on):
        if not self.is_manager(ctx.author):
            await ctx.send("Only the owner, admins, or bot managers can manage features.")
            return
        name = (name or "").lower().strip()
        if name not in FEATURES:
            await ctx.send(f"I don't have a feature called **{name}**. "
                           "Run `$feature` to see the list.")
            return
        gid = str(ctx.guild.id)
        col = self.mongo.client[self.db][self.col]
        if turn_on:
            col.update_one({"guild_id": gid}, {"$pull": {"disabled": name}}, upsert=True)
            self._disabled.get(ctx.guild.id, set()).discard(name)
            await ctx.send(f"✅ **{name}** is back on for this server.")
        else:
            col.update_one({"guild_id": gid}, {"$addToSet": {"disabled": name}}, upsert=True)
            self._disabled.setdefault(ctx.guild.id, set()).add(name)
            await ctx.send(f"⛔ **{name}** is now off for this server "
                           f"({FEATURES[name]['desc']}).")

    @feature.command(name="off", aliases=["disable"])
    async def feature_off(self, ctx, name: str = None):
        await self._toggle(ctx, name, turn_on=False)

    @feature.command(name="on", aliases=["enable"])
    async def feature_on(self, ctx, name: str = None):
        await self._toggle(ctx, name, turn_on=True)


async def setup(client):
    await client.add_cog(FeatureManager(client))
