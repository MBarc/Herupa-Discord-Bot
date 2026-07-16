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
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import discord
from discord.ext import commands, tasks

from tools.HerupaMongo import HerupaMongo

EASTERN = ZoneInfo("America/New_York")


# --- floating holidays (repeat="holiday:<key>" recomputes the date yearly) ---

def _nth_weekday(year, month, weekday, n):
    """The n-th <weekday> of a month; weekday is Python's Monday=0."""
    first = date(year, month, 1).weekday()
    return date(year, month, 1 + ((weekday - first) % 7) + (n - 1) * 7)


def _last_weekday(year, month, weekday):
    last = date(year, month, calendar.monthrange(year, month)[1])
    return last - timedelta(days=(last.weekday() - weekday) % 7)


def _easter(y):
    """Western Easter (anonymous Gregorian computus)."""
    a, b, c = y % 19, y // 100, y % 100
    d, e, f = b // 4, b % 4, (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = c // 4, c % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month = (h + l - 7 * m + 114) // 31
    day = ((h + l - 7 * m + 114) % 31) + 1
    return date(y, month, day)


HOLIDAY_RULES = {
    "mlk":          ("MLK Day",         lambda y: _nth_weekday(y, 1, 0, 3)),
    "presidents":   ("Presidents' Day", lambda y: _nth_weekday(y, 2, 0, 3)),
    "easter":       ("Easter",          _easter),
    "mothersday":   ("Mother's Day",    lambda y: _nth_weekday(y, 5, 6, 2)),
    "memorial":     ("Memorial Day",    lambda y: _last_weekday(y, 5, 0)),
    "fathersday":   ("Father's Day",    lambda y: _nth_weekday(y, 6, 6, 3)),
    "labor":        ("Labor Day",       lambda y: _nth_weekday(y, 9, 0, 1)),
    "thanksgiving": ("Thanksgiving",    lambda y: _nth_weekday(y, 11, 3, 4)),
}


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
    time is already past. repeat "holiday:<key>" recomputes the holiday's
    date each year (Labor Day moves; the rule doesn't).
    """
    after = after or datetime.now(timezone.utc)
    if repeat.startswith("holiday:"):
        rule = HOLIDAY_RULES.get(repeat.split(":", 1)[1])
        if rule is None:
            return None
        t = parse_wall(wall)
        for year in range(after.astimezone(EASTERN).year, after.astimezone(EASTERN).year + 3):
            d = rule[1](year)
            dt = datetime(d.year, d.month, d.day, t.hour, t.minute, tzinfo=EASTERN)
            if dt.astimezone(timezone.utc) >= after:
                return dt.astimezone(timezone.utc).replace(tzinfo=None)
        return None
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
        embed = None
        if doc.get("embed"):
            e = doc["embed"]
            embed = discord.Embed(
                title=e.get("title") or None,
                description=e.get("description") or None,
                colour=discord.Colour(int(e.get("color", 0xFFB7C5))))
        content = doc.get("content") or None

        if doc.get("user_id"):
            # DM target: open (or reuse) Herupa's DM channel with the user.
            try:
                user = (self.client.get_user(int(doc["user_id"]))
                        or await self.client.fetch_user(int(doc["user_id"])))
                channel = user.dm_channel or await user.create_dm()
                await channel.send(content=content, embed=embed)
                print(f"[Scheduler] DM'd {doc.get('name')!r} to {user}")
            except Exception as e:
                print(f"[Scheduler] DM failed for {doc.get('name')!r}: {e!r}")
        else:
            channel = self.client.get_channel(int(doc["channel_id"]))
            if channel is not None:
                await channel.send(content=content, embed=embed)
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
