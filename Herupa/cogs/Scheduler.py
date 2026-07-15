# Fires messages scheduled from the web UI. The UI writes docs to Mongo
# (db "webui", collection "scheduled"); this cog only reads them and sends.
# All wall-clock times are Eastern (the server's clock for everything else),
# stored alongside a computed UTC next_fire the loop compares against.
#
# Doc shape:
#   {name, channel_id: int, content: str, embed: {title, description, color}|None,
#    wall: "YYYY-MM-DDTHH:MM" (Eastern), repeat: none|daily|weekly|monthly|yearly,
#    next_fire: datetime (UTC), enabled: bool, last_fired: datetime|None}

import calendar
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import discord
from discord.ext import commands, tasks

from tools.HerupaMongo import HerupaMongo

EASTERN = ZoneInfo("America/New_York")


def parse_wall(wall):
    """'YYYY-MM-DDTHH:MM' (Eastern) -> aware datetime."""
    return datetime.strptime(wall, "%Y-%m-%dT%H:%M").replace(tzinfo=EASTERN)


def advance_wall(dt, repeat):
    """Next occurrence after `dt` for a repeat rule, in Eastern wall time."""
    if repeat == "daily":
        return dt + timedelta(days=1)
    if repeat == "weekly":
        return dt + timedelta(days=7)
    if repeat == "monthly":
        year, month = (dt.year, dt.month + 1) if dt.month < 12 else (dt.year + 1, 1)
        day = min(dt.day, calendar.monthrange(year, month)[1])
        return dt.replace(year=year, month=month, day=day)
    if repeat == "yearly":
        year = dt.year + 1
        day = min(dt.day, calendar.monthrange(year, dt.month)[1])
        return dt.replace(year=year, day=day)
    return None


def next_fire_utc(wall, repeat, after=None):
    """First occurrence of (wall, repeat) at or after `after` (default: now).

    Returns a naive UTC datetime (what pymongo stores), or None if a one-off
    time is already past.
    """
    after = after or datetime.now(timezone.utc)
    dt = parse_wall(wall)
    while dt.astimezone(timezone.utc) < after:
        dt = advance_wall(dt, repeat)
        if dt is None:
            return None
    return dt.astimezone(timezone.utc).replace(tzinfo=None)


class Scheduler(commands.Cog):

    def __init__(self, client):
        self.client = client
        self.mongo = HerupaMongo()

    def _col(self):
        return self.mongo.client["webui"]["scheduled"]

    async def cog_load(self):
        self.check_due.start()

    async def cog_unload(self):
        self.check_due.cancel()

    @tasks.loop(seconds=30)
    async def check_due(self):
        now = datetime.utcnow()
        try:
            due = list(self._col().find({"enabled": True,
                                         "next_fire": {"$lte": now}}))
        except Exception as e:
            print(f"[Scheduler] mongo read failed: {e!r}")
            return
        for doc in due:
            try:
                await self._fire(doc, now)
            except Exception as e:
                print(f"[Scheduler] failed to fire {doc.get('name')!r}: {e!r}")

    async def _fire(self, doc, now):
        channel = self.client.get_channel(int(doc["channel_id"]))
        embed = None
        if doc.get("embed"):
            e = doc["embed"]
            embed = discord.Embed(
                title=e.get("title") or None,
                description=e.get("description") or None,
                colour=discord.Colour(int(e.get("color", 0xFFB7C5))))
        if channel is not None:
            await channel.send(content=doc.get("content") or None, embed=embed)
            print(f"[Scheduler] sent {doc.get('name')!r} to #{channel.name}")
        else:
            print(f"[Scheduler] channel {doc.get('channel_id')} not found "
                  f"for {doc.get('name')!r}")

        update = {"last_fired": now}
        nxt = None
        if doc.get("repeat", "none") != "none":
            nxt = next_fire_utc(doc["wall"], doc["repeat"], after=now.replace(tzinfo=timezone.utc) + timedelta(minutes=1))
        if nxt is not None:
            update["next_fire"] = nxt
        else:
            update["enabled"] = False  # one-off done (kept for history)
        self._col().update_one({"_id": doc["_id"]}, {"$set": update})


async def setup(client):
    await client.add_cog(Scheduler(client))
