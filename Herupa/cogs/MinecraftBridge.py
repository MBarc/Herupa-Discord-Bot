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
plus the existing rcon_host / rcon_port / rcon_password keys. No block, or
no bridge_channel_id, means no bridge for that guild. Config is read per
message (bridge traffic is low-volume, matching AccountLink).

Everything sits behind the "accounts" + "minecraft" $features, same as the
whitelist sync.
'''

import json
import sys
import os

import discord
from discord.ext import commands

current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
sys.path.append(parent_dir)

from tools.HerupaMongo import HerupaMongo
from tools.MinecraftRcon import rcon

RELAY_MAX = 256  # keep in-game chat readable; Discord essays get cut


class MinecraftBridge(commands.Cog):

    def __init__(self, client):
        self.client = client
        self.mongo = HerupaMongo()
        self.db = "accounts"
        self.config_col = "config"

    # ----------------------------- config helpers -----------------------------

    def _mc_conf(self, guild_id):
        gid = str(guild_id)
        for doc in self.mongo.returnCollectionEntries(
                database_name=self.db, collection_name=self.config_col):
            if doc.get("guild_id") == gid:
                mc = doc.get("minecraft")
                return mc if isinstance(mc, dict) else None
        return None

    def _feature_on(self, guild_id):
        fm = self.client.get_cog("FeatureManager")
        return fm is None or (fm.is_enabled(guild_id, "accounts")
                              and fm.is_enabled(guild_id, "minecraft"))

    # ----------------------------- relay -----------------------------

    @commands.Cog.listener()
    async def on_message(self, message):
        if message.guild is None or message.author.bot or message.webhook_id:
            return
        if message.content.startswith("$"):
            return
        mc = self._mc_conf(message.guild.id)
        if mc is None or not mc.get("bridge_channel_id"):
            return
        if str(message.channel.id) != str(mc["bridge_channel_id"]):
            return
        if not self._feature_on(message.guild.id):
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
