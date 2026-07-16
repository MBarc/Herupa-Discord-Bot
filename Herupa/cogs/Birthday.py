# Birthdays: members save theirs with $birthday, Herupa wishes them a happy
# birthday in general chat each morning, and they show up on the web control
# room's schedule calendar. Only month/day is used for the celebration; a year,
# if given, is optional and just lets Herupa mention an age.

import calendar as _cal
import re
from datetime import datetime
from zoneinfo import ZoneInfo

import discord
from discord.ext import commands, tasks

from tools.HerupaMongo import HerupaMongo

EASTERN = ZoneInfo("America/New_York")
GENERAL_CHANNEL = "🤠general-chat🤠"
PINK = discord.Colour.from_rgb(255, 183, 197)
MONTH_NAMES = ["", "January", "February", "March", "April", "May", "June",
               "July", "August", "September", "October", "November", "December"]
_MONTH_LOOKUP = {}
for _i, _n in enumerate(MONTH_NAMES[1:], 1):
    _MONTH_LOOKUP[_n.lower()] = _i
    _MONTH_LOOKUP[_n[:3].lower()] = _i
# days per month using a leap year so Feb 29 is allowed
_MAX_DAY = [0, 31, 29, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]


def parse_birthday(text):
    """Parse 'March 5', '3/5', 'Mar 5 1998', '3-5-1998' -> (month, day, year|None).

    Returns None if it can't be read or the date is impossible.
    """
    text = text.strip().lower()
    month = day = year = None
    m = re.match(r"^(\d{1,2})[/\-.](\d{1,2})(?:[/\-.](\d{2,4}))?$", text)
    if m:
        month, day = int(m.group(1)), int(m.group(2))
        year = int(m.group(3)) if m.group(3) else None
    else:
        for tok in re.split(r"[\s,]+", text):
            if tok in _MONTH_LOOKUP:
                month = _MONTH_LOOKUP[tok]
            elif tok.isdigit():
                v = int(tok)
                if len(tok) == 4 or v > 31:
                    year = v
                elif day is None:
                    day = v
                else:
                    year = v
    if month is None or day is None or not (1 <= month <= 12):
        return None
    if not (1 <= day <= _MAX_DAY[month]):
        return None
    if year is not None and not (1900 <= year <= datetime.now(EASTERN).year):
        year = None
    return month, day, year


def pretty(month, day, year=None):
    base = f"{MONTH_NAMES[month]} {day}"
    return f"{base}, {year}" if year else base


class Birthday(commands.Cog):

    def __init__(self, client):
        self.client = client
        self.mongo = HerupaMongo()

    def _col(self):
        return self.mongo.client["birthdays"]["dates"]

    def _meta(self):
        return self.mongo.client["birthdays"]["meta"]

    async def cog_load(self):
        self.announce.start()

    async def cog_unload(self):
        self.announce.cancel()

    # ------------------------- commands -------------------------

    @commands.guild_only()
    @commands.command(name="birthday", aliases=["bday"])
    async def birthday(self, ctx, *, arg: str = None):
        # $birthday @someone -> show theirs
        if ctx.message.mentions:
            target = ctx.message.mentions[0]
            doc = self._col().find_one({"_id": str(target.id)})
            if not doc:
                await ctx.send(f"{target.display_name} hasn't saved a birthday yet.")
            else:
                await ctx.send(f"🎂 {target.display_name}'s birthday is "
                               f"**{pretty(doc['month'], doc['day'])}**.")
            return

        # $birthday -> show your own or prompt
        if not arg:
            doc = self._col().find_one({"_id": str(ctx.author.id)})
            if doc:
                await ctx.send(f"🎂 Your birthday is saved as "
                               f"**{pretty(doc['month'], doc['day'], doc.get('year'))}**. "
                               "Change it with `$birthday <date>` or remove it with `$forgetbirthday`.")
            else:
                await ctx.send("Tell me your birthday and I'll remember it: "
                               "`$birthday March 5` (a year is optional).")
            return

        parsed = parse_birthday(arg)
        if parsed is None:
            await ctx.send("I couldn't read that date. Try `$birthday March 5` or `$birthday 3/5`.")
            return
        month, day, year = parsed
        self._col().update_one(
            {"_id": str(ctx.author.id)},
            {"$set": {"month": month, "day": day, "year": year,
                      "name": ctx.author.display_name}},
            upsert=True)
        await ctx.send(f"🎂 Got it, {ctx.author.mention}! I'll celebrate you on "
                       f"**{pretty(month, day)}**.")

    @commands.guild_only()
    @commands.command(name="forgetbirthday")
    async def forgetbirthday(self, ctx):
        res = self._col().delete_one({"_id": str(ctx.author.id)})
        if res.deleted_count:
            await ctx.send("Done, I've forgotten your birthday.")
        else:
            await ctx.send("You didn't have a birthday saved.")

    @commands.guild_only()
    @commands.command(name="birthdays", aliases=["bdays"])
    async def birthdays(self, ctx):
        today = datetime.now(EASTERN)
        rows = []
        for doc in self._col().find():
            member = ctx.guild.get_member(int(doc["_id"]))
            if member is None:
                continue
            # days until the next occurrence
            m, d = doc["month"], doc["day"]
            year = today.year
            if (m, d) < (today.month, today.day):
                year += 1
            try:
                nxt = datetime(year, m, d)
            except ValueError:            # Feb 29 in a non-leap year -> Mar 1
                nxt = datetime(year, 3, 1)
            rows.append((max(0, (nxt.date() - today.date()).days), member.display_name, m, d))
        if not rows:
            await ctx.send("No birthdays saved yet. Add yours with `$birthday <date>`!")
            return
        rows.sort()
        lines = []
        for days, name, m, d in rows[:10]:
            when = "today! 🎉" if days == 0 else ("tomorrow" if days == 1 else f"in {days} days")
            lines.append(f"**{pretty(m, d)}** — {name} ({when})")
        embed = discord.Embed(title="🎂 Upcoming birthdays", colour=PINK,
                              description="\n".join(lines))
        await ctx.send(embed=embed)

    # ------------------------- daily announcement -------------------------

    @tasks.loop(minutes=30)
    async def announce(self):
        now = datetime.now(EASTERN)
        today = now.date().isoformat()
        state = self._meta().find_one({"_id": "state"}) or {}
        if state.get("last") == today:
            return
        channel = discord.utils.get(self.client.get_all_channels(), name=GENERAL_CHANNEL)
        if channel is None:
            return
        celebrants = []
        for doc in self._col().find({"month": now.month, "day": now.day}):
            member = channel.guild.get_member(int(doc["_id"]))
            if member is not None:
                celebrants.append(member)
        if celebrants:
            mentions = ", ".join(m.mention for m in celebrants)
            plural = "birthdays" if len(celebrants) > 1 else "birthday"
            embed = discord.Embed(
                colour=PINK,
                description=f"🎂🎉 Happy {plural}, {mentions}! Hope your day is amazing 💖")
            try:
                await channel.send(content=mentions, embed=embed,
                                   allowed_mentions=discord.AllowedMentions(users=True))
            except discord.HTTPException:
                pass
        self._meta().update_one({"_id": "state"}, {"$set": {"last": today}}, upsert=True)

    @announce.before_loop
    async def _before(self):
        await self.client.wait_until_ready()


async def setup(client):
    await client.add_cog(Birthday(client))
