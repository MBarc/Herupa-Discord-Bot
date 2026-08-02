'''
Purpose: the Discord half of the Minecraft chat bridge.

DISCORD -> GAME: a message posted in the guild's bridge channel is shown to
everyone in game over RCON, as pink [Discord] <Name> text (tellraw). Bot and
webhook messages are ignored -- the game->Discord direction arrives through a
channel webhook, so that rule is also what prevents echo loops. $-prefixed
lines are skipped (people run commands in there; the game doesn't care).

GAME -> DISCORD does NOT pass through this cog: a small log-tailer service on
the Minecraft host (repo: scripts/mc-bridge/) follows logs/latest.log and
posts chat / joins / leaves / deaths / advancements / server up-down straight
to the same channel's webhook, with each chat line under the player's own
name and head. Herupa only ever sees those as normal webhook messages.

MULTI-SERVER: per-guild config lives in the SAME "minecraft" block of the
accounts config that AccountLink owns (db "accounts", collection "config"):
  "bridge_channel_id": "123..."    relay messages from this channel
  "bridge_webhook_id": "456..."    the tailer's webhook (so moves follow)
plus the existing rcon_host / rcon_port / rcon_password keys. No block, or
no bridge_channel_id, means no bridge for that guild.

COST WHEN IDLE: none worth mentioning. There is no background loop, and the
on_message listener (which fires for every guild message) checks the cheap
in-memory $feature switch FIRST, then a 30-second config cache -- a guild
with the feature off, or with no server configured, costs at most one Mongo
read per 30s, not one per message. $mcbridge invalidates the cache so its
own changes apply instantly; web UI changes apply within the 30s.

CHOOSING THE CHANNEL -- $mcbridge (managers only; also on the web UI's
Minecraft page): bare = current status, "here" or a #channel = move the
bridge there, "off" = stop relaying Discord messages in game. Moving the
bridge also MOVES THE WEBHOOK to the new channel, so the game->Discord feed
follows without touching the Minecraft host. "off" can't stop the feed (the
tailer posts to the webhook no matter what this cog thinks), so the reply
says as much.

Everything sits behind the "accounts" + "minecraft" $features, same as the
whitelist sync.
'''

import json
import sys
import os
import time

import discord
from discord.ext import commands

current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
sys.path.append(parent_dir)

from tools.HerupaMongo import HerupaMongo
from tools.MinecraftRcon import rcon

RELAY_MAX = 256  # keep in-game chat readable; Discord essays get cut
CONF_TTL = 30    # seconds a guild's minecraft config stays cached


class MinecraftBridge(commands.Cog):

    def __init__(self, client):
        self.client = client
        self.mongo = HerupaMongo()
        self.db = "accounts"
        self.config_col = "config"
        self._cache = {}  # guild_id -> (expires_monotonic, mc block | None)

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

    def _feature_on(self, guild_id):
        fm = self.client.get_cog("FeatureManager")
        return fm is None or (fm.is_enabled(guild_id, "accounts")
                              and fm.is_enabled(guild_id, "minecraft"))

    # ----------------------------- $mcbridge -----------------------------

    async def _move_webhook(self, mc, channel):
        """Point the tailer's webhook at the new channel. Returns a note for
        the reply when the game->Discord side could NOT follow."""
        wid = mc.get("bridge_webhook_id")
        if not wid:
            return ("\n⚠️ I don't know this server's bridge webhook "
                    "(no bridge_webhook_id in the config), so the in-game "
                    "feed stays where it was.")
        try:
            hook = await self.client.fetch_webhook(int(wid))
            if hook.channel_id != channel.id:
                await hook.edit(channel=channel,
                                reason="Minecraft bridge channel moved")
        except discord.NotFound:
            return ("\n⚠️ The bridge webhook seems to be deleted, so the "
                    "in-game feed can't follow. It needs to be recreated and "
                    "its URL updated on the Minecraft host.")
        except discord.HTTPException as e:
            return f"\n⚠️ I couldn't move the in-game feed's webhook: {e}"
        return ""

    @commands.command(name="mcbridge")
    @commands.guild_only()
    async def mcbridge(self, ctx, *, where: str = None):
        """Bare = status, "here" / #channel = put the bridge there, "off" =
        stop relaying Discord messages in game."""
        fm = self.client.get_cog("FeatureManager")
        if fm is None or not fm.is_manager(ctx.author):
            await ctx.send("Only the owner, admins, or bot managers can move "
                           "the Minecraft chat bridge.")
            return
        mc = self._mc_conf(ctx.guild.id)
        if mc is None:
            await ctx.send("This server has no Minecraft server configured yet "
                           "(the accounts config needs a minecraft block first).")
            return
        col = self.mongo.client[self.db][self.config_col]
        where = (where or "").strip()

        if not where:
            current = mc.get("bridge_channel_id")
            if current:
                await ctx.send(f"⛏️ The Minecraft chat bridge lives in "
                               f"<#{current}>. `$mcbridge here` moves it to "
                               "the current channel, `$mcbridge off` stops the "
                               "Discord side.")
            else:
                await ctx.send("⛏️ The chat bridge is off. Run `$mcbridge here` "
                               "in the channel that should talk to the server "
                               "(or `$mcbridge #channel`).")
            return

        if where.lower() == "off":
            col.update_one({"guild_id": str(ctx.guild.id)},
                           {"$unset": {"minecraft.bridge_channel_id": ""}})
            self._cache.pop(str(ctx.guild.id), None)
            await ctx.send("⛏️ Bridge off: messages here no longer reach the "
                           "game. The in-game feed still posts to its channel; "
                           "turn off the `minecraft` feature (or remove the "
                           "webhook) to silence that too.")
            return

        if where.lower() in ("here", "set"):
            channel = ctx.channel
        else:
            try:
                channel = await commands.TextChannelConverter().convert(ctx, where)
            except commands.BadArgument:
                await ctx.send("I don't know that channel. Use `$mcbridge here`, "
                               "`$mcbridge #channel`, or `$mcbridge off`.")
                return
        col.update_one({"guild_id": str(ctx.guild.id)},
                       {"$set": {"minecraft.bridge_channel_id": str(channel.id)}},
                       upsert=True)
        self._cache.pop(str(ctx.guild.id), None)
        note = await self._move_webhook(mc, channel)
        await ctx.send(f"⛏️ The Minecraft chat bridge now lives in "
                       f"{channel.mention}: messages there show up in game, "
                       f"and game chat lands there.{note}")

    # ----------------------------- relay -----------------------------

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
        if not mc or not mc.get("bridge_channel_id"):
            return
        if str(message.channel.id) != str(mc["bridge_channel_id"]):
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
        password = mc.get("rcon_password") or os.environ.get("MC_RCON_PASSWORD", "")
        try:
            await rcon(mc.get("rcon_host", "minecraft.local"),
                       int(mc.get("rcon_port", 25575)), password,
                       f"tellraw @a {payload}")
        except Exception as e:
            # The server being down shouldn't spam the channel -- one quiet
            # reaction tells the sender their line didn't make it in.
            print(f"[MinecraftBridge] relay failed: {e}")
            try:
                await message.add_reaction("⚠️")
            except discord.HTTPException:
                pass


async def setup(client):
    await client.add_cog(MinecraftBridge(client))
