'''
Purpose: the Discord half of the Minecraft chat bridge -- one channel per
world, plus a live player-list embed.

DISCORD -> GAME: a message posted in a world's channel is shown over RCON
tellraw as pink [Discord] <Name> text -- but only to the players inside that
world (and its _nether / _the_end dimensions), matching the channel-per-world
layout. Bot and webhook messages are ignored (the game->Discord direction
arrives through each channel's webhook, so that rule is also what prevents
echo loops). $-prefixed lines are skipped.

GAME -> DISCORD does NOT pass through this cog: a log-tailer service on the
Minecraft host (repo: scripts/mc-bridge/) follows logs/latest.log, works out
each event's world over local RCON, and posts to that world's channel
webhook. Herupa only ever sees those as normal webhook messages.

PLAYER LIST: a tasks.loop refreshes ONE embed in the configured player-list
channel every 2 minutes: server up/down, and who is online in which world.
The message is edited in place (recreated if someone deletes it).

MULTI-SERVER: per-guild config lives in the "minecraft" block of the
accounts config that AccountLink owns (db "accounts", collection "config"):

    "worlds": {                      one entry per world with a channel
        "Kingdoms": {"channel_id": "...", "webhook_id": "..."},
        ...
    },
    "playerlist_channel_id": "...",  the player-list embed's channel
    "playerlist_message_id": "...",  written by the loop, not by hand

plus the existing rcon_host / rcon_port / rcon_password keys. A world's
webhook_id is the tailer's webhook for that channel, kept here so channel
moves can re-point it. Worlds NOT in the map fall back to the tailer's
"default" webhook on the game->Discord side only.

CONFIG UX -- $mcbridge (managers only; same controls on the web UI's
Minecraft page): bare = status, "$mcbridge <world> here|#channel" = move a
world's channel (the webhook follows), "$mcbridge playerlist here|#channel"
= move the player-list. Turning the whole bridge off is the minecraft
$feature's job, which everything here respects.

COST WHEN IDLE: on_message checks the in-memory $feature switch first and
the config sits behind a 30-second cache; the player-list loop only touches
guilds with a playerlist channel configured. RCON lookups (player -> world
via Multiverse `mv who`) are cached for 10 seconds.
'''

import json
import re
import sys
import os
import time
from datetime import datetime, timezone

import discord
from discord.ext import commands, tasks

current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
sys.path.append(parent_dir)

from tools.HerupaMongo import HerupaMongo
from tools.MinecraftRcon import rcon

PINK = 0xFFB7C5
RELAY_MAX = 256   # keep in-game chat readable; Discord essays get cut
CONF_TTL = 30     # seconds a guild's minecraft config stays cached
MAP_TTL = 10      # seconds the player->world map stays cached
COLORS = re.compile("§.")


def world_key(world):
    """Survival_nether / Survival_the_end -> Survival."""
    if not world:
        return None
    for suffix in ("_nether", "_the_end"):
        if world.endswith(suffix):
            return world[: -len(suffix)]
    return world


class MinecraftBridge(commands.Cog):

    def __init__(self, client):
        self.client = client
        self.mongo = HerupaMongo()
        self.db = "accounts"
        self.config_col = "config"
        self._cache = {}      # guild_id -> (expires, mc block | None)
        self._maps = {}       # guild_id -> (expires, {player: world})

    async def cog_load(self):
        self.playerlist.start()

    async def cog_unload(self):
        self.playerlist.cancel()

    # ----------------------------- config helpers -----------------------------

    def _mc_conf(self, guild_id):
        gid = str(guild_id)
        for doc in self.mongo.returnCollectionEntries(
                database_name=self.db, collection_name=self.config_col):
            if doc.get("guild_id") == gid:
                mc = doc.get("minecraft")
                return mc if isinstance(mc, dict) else None
        return None

    def _mc_cached(self, guild_id):
        gid = str(guild_id)
        hit = self._cache.get(gid)
        now = time.monotonic()
        if hit and hit[0] > now:
            return hit[1]
        mc = self._mc_conf(gid)
        self._cache[gid] = (now + CONF_TTL, mc)
        return mc

    def _drop_cache(self, guild_id):
        self._cache.pop(str(guild_id), None)

    def _feature_on(self, guild_id):
        fm = self.client.get_cog("FeatureManager")
        return fm is None or (fm.is_enabled(guild_id, "accounts")
                              and fm.is_enabled(guild_id, "minecraft"))

    # ----------------------------- rcon helpers -----------------------------

    async def _rcon(self, mc, command):
        password = mc.get("rcon_password") or os.environ.get("MC_RCON_PASSWORD", "")
        reply = await rcon(mc.get("rcon_host", "minecraft.local"),
                           int(mc.get("rcon_port", 25575)), password, command)
        return COLORS.sub("", reply or "")

    async def _player_map(self, mc, guild_id):
        """{player: raw world} via Multiverse, cached MAP_TTL seconds."""
        gid = str(guild_id)
        hit = self._maps.get(gid)
        now = time.monotonic()
        if hit and hit[0] > now:
            return hit[1]
        mapping = {}
        reply = await self._rcon(mc, "mv list")
        worlds = re.findall(r"^([A-Za-z0-9_-]+) - (?:NORMAL|NETHER|THE_END)$",
                            reply, re.M)
        for w in worlds:
            reply = await self._rcon(mc, f"mv who {w}")
            m = re.search(rf"^{re.escape(w)}: (.+)$", reply, re.M)
            if not m or m.group(1).strip() == "empty":
                continue
            for name in m.group(1).split(","):
                name = name.strip()
                if re.fullmatch(r"[A-Za-z0-9_]{1,16}", name):
                    mapping[name] = w
        self._maps[gid] = (now + MAP_TTL, mapping)
        return mapping

    # ----------------------------- relay (discord -> game) -----------------------------

    @commands.Cog.listener()
    async def on_message(self, message):
        # Guard order matters: this fires for EVERY guild message, so the
        # free checks and the in-memory feature switch come before any
        # config lookup, and the lookup itself is cached.
        if message.guild is None or message.author.bot or message.webhook_id:
            return
        if message.content.startswith("$"):
            return
        if not self._feature_on(message.guild.id):
            return
        mc = self._mc_cached(message.guild.id)
        if not mc or not mc.get("worlds"):
            return
        cid = str(message.channel.id)
        world = next((w for w, wc in mc["worlds"].items()
                      if str(wc.get("channel_id")) == cid), None)
        if world is None:
            return

        text = message.clean_content.strip()
        extras = len(message.attachments) + len(message.stickers)
        if extras:
            text = (text + " " if text else "") + f"[{extras} attachment(s)]"
        if not text:
            return
        if len(text) > RELAY_MAX:
            text = text[:RELAY_MAX - 1] + "…"

        payload = json.dumps([
            {"text": "[Discord] ", "color": "#FFB7C5"},
            {"text": f"<{message.author.display_name}> ", "color": "#B49BE0"},
            {"text": text, "color": "white"},
        ])
        try:
            mapping = await self._player_map(mc, message.guild.id)
            targets = [n for n, w in mapping.items() if world_key(w) == world]
            for name in targets:
                await self._rcon(mc, f"tellraw {name} {payload}")
        except Exception as e:
            # The server being down shouldn't spam the channel -- one quiet
            # reaction tells the sender their line didn't make it in.
            print(f"[MinecraftBridge] relay failed: {e}")
            try:
                await message.add_reaction("⚠️")
            except discord.HTTPException:
                pass

    # ----------------------------- player-list embed -----------------------------

    @tasks.loop(minutes=2)
    async def playerlist(self):
        for doc in self.mongo.returnCollectionEntries(
                database_name=self.db, collection_name=self.config_col):
            mc = doc.get("minecraft")
            gid = doc.get("guild_id")
            if (not isinstance(mc, dict) or not gid
                    or not mc.get("playerlist_channel_id")):
                continue
            guild = self.client.get_guild(int(gid))
            if guild is None or not self._feature_on(guild.id):
                continue
            try:
                await self._update_playerlist(guild, mc)
            except Exception as e:  # one guild must not stop the loop
                print(f"[MinecraftBridge] playerlist {gid}: {e}")

    @playerlist.before_loop
    async def _before_playerlist(self):
        await self.client.wait_until_ready()

    async def _update_playerlist(self, guild, mc):
        channel = guild.get_channel(int(mc["playerlist_channel_id"]))
        if channel is None:
            return
        embed = discord.Embed(title="⛏️ Minecraft server", colour=PINK,
                              timestamp=datetime.now(timezone.utc))
        address = mc.get("address") or mc.get("rcon_host", "")
        try:
            mapping = await self._player_map(mc, guild.id)
            reachable = True
        except Exception:
            mapping, reachable = {}, False
        if reachable:
            embed.description = (f"🟢 Online at `{address}` · "
                                 f"**{len(mapping)}** playing")
            grouped = {}
            for name, w in mapping.items():
                grouped.setdefault(world_key(w), []).append(name)
            for world, wc in (mc.get("worlds") or {}).items():
                names = sorted(grouped.pop(world, []), key=str.lower)
                # The channel mention up top is clickable: one tap from
                # seeing who's in a world to talking with them.
                value = f"<#{wc.get('channel_id')}>\n"
                embed.add_field(name=world,
                                value=value + ("\n".join(names) if names
                                               else "*empty*"))
            for world, names in sorted(grouped.items()):
                embed.add_field(name=world,
                                value="\n".join(sorted(names, key=str.lower)))
        else:
            embed.description = f"🔴 `{address}` is unreachable right now."
        embed.set_footer(text="Updates every couple of minutes · "
                              "get whitelisted with $link")

        msg_id = mc.get("playerlist_message_id")
        if msg_id:
            try:
                msg = await channel.fetch_message(int(msg_id))
                await msg.edit(embed=embed)
                return
            except discord.NotFound:
                pass   # someone deleted it: make a fresh one below
            except discord.HTTPException:
                return
        try:
            msg = await channel.send(embed=embed)
        except discord.HTTPException:
            return
        self.mongo.client[self.db][self.config_col].update_one(
            {"guild_id": str(guild.id)},
            {"$set": {"minecraft.playerlist_message_id": str(msg.id)}})
        self._drop_cache(guild.id)

    # ----------------------------- $mcbridge -----------------------------

    async def _move_webhook(self, wc, channel):
        """Point a world's webhook at its new channel. Returns a warning note
        for the reply when the game->Discord side could NOT follow."""
        wid = wc.get("webhook_id")
        if not wid:
            return ("\n⚠️ That world has no webhook recorded, so the in-game "
                    "feed stays where it was.")
        try:
            hook = await self.client.fetch_webhook(int(wid))
            if hook.channel_id != channel.id:
                await hook.edit(channel=channel,
                                reason="Minecraft bridge channel moved")
        except discord.NotFound:
            return ("\n⚠️ That world's webhook seems to be deleted; the "
                    "in-game feed can't follow until it's recreated and the "
                    "Minecraft host's env updated.")
        except discord.HTTPException as e:
            return f"\n⚠️ I couldn't move the in-game feed's webhook: {e}"
        return ""

    @commands.command(name="mcbridge")
    @commands.guild_only()
    async def mcbridge(self, ctx, world: str = None, *, where: str = None):
        """Bare = status. "$mcbridge <world> here|#channel" moves a world's
        channel; "$mcbridge playerlist here|#channel" moves the player list."""
        fm = self.client.get_cog("FeatureManager")
        if fm is None or not fm.is_manager(ctx.author):
            await ctx.send("Only the owner, admins, or bot managers can move "
                           "the Minecraft bridge channels.")
            return
        mc = self._mc_conf(ctx.guild.id)
        if mc is None:
            await ctx.send("This server has no Minecraft server configured yet "
                           "(the accounts config needs a minecraft block first).")
            return
        worlds = mc.get("worlds") or {}
        col = self.mongo.client[self.db][self.config_col]

        if world is None:
            lines = [f"**{w}** → <#{wc.get('channel_id')}>"
                     for w, wc in worlds.items()]
            pl = mc.get("playerlist_channel_id")
            lines.append(f"**player list** → {f'<#{pl}>' if pl else '*not set*'}")
            await ctx.send(embed=discord.Embed(
                title="⛏️ Minecraft bridge", description="\n".join(lines),
                colour=PINK).set_footer(
                    text="$mcbridge <world> here/#channel moves one · "
                         "also on the web UI's Minecraft page"))
            return

        if not where:
            await ctx.send("Where to? `$mcbridge <world> here` or "
                           "`$mcbridge <world> #channel`.")
            return
        if where.lower() in ("here", "set"):
            channel = ctx.channel
        else:
            try:
                channel = await commands.TextChannelConverter().convert(ctx, where)
            except commands.BadArgument:
                await ctx.send("I don't know that channel. Use `here` or a "
                               "#channel mention.")
                return

        if world.lower() in ("playerlist", "player-list", "players"):
            col.update_one(
                {"guild_id": str(ctx.guild.id)},
                {"$set": {"minecraft.playerlist_channel_id": str(channel.id)},
                 "$unset": {"minecraft.playerlist_message_id": ""}})
            self._drop_cache(ctx.guild.id)
            await ctx.send(f"⛏️ The player list now lives in {channel.mention}; "
                           "the embed appears there within a couple of minutes.")
            return

        match = next((w for w in worlds if w.lower() == world.lower()), None)
        if match is None:
            known = ", ".join(worlds) or "none configured"
            await ctx.send(f"I don't know a world called **{world}**. "
                           f"Worlds here: {known}.")
            return
        col.update_one(
            {"guild_id": str(ctx.guild.id)},
            {"$set": {f"minecraft.worlds.{match}.channel_id": str(channel.id)}})
        self._drop_cache(ctx.guild.id)
        note = await self._move_webhook(worlds[match], channel)
        await ctx.send(f"⛏️ **{match}** now bridges with {channel.mention}: "
                       f"messages there reach its players, and its game chat "
                       f"lands there.{note}")


async def setup(client):
    await client.add_cog(MinecraftBridge(client))
