# $daily: a once-a-day chunk of XP with streak multipliers. Base 100 XP;
# claiming on consecutive days builds a streak that doubles the chunk at
# 3 days, triples it at 5, and quintuples it at 10. Miss a day and the
# streak starts over. Days roll over at midnight Eastern, same clock as the
# server's other daily routines.

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import discord
from discord.ext import commands

from tools.HerupaMongo import HerupaMongo

PINK = discord.Colour.from_rgb(255, 183, 197)
EASTERN = ZoneInfo("America/New_York")
BASE_XP = 100
# streak length -> multiplier, checked highest first
TIERS = [(10, 5), (5, 3), (3, 2)]


def _multiplier(streak):
    for days, mult in TIERS:
        if streak >= days:
            return mult
    return 1


def _next_milestone(streak):
    for days, mult in reversed(TIERS):
        if streak < days:
            return days, mult
    return None


# --- MEE6 level curve (same as the Leveling and Shop cogs) ---
def _xp_to_advance(level):
    return 5 * level * level + 50 * level + 100

def level_for_xp(total_xp):
    level, remaining = 0, int(total_xp)
    while remaining >= _xp_to_advance(level):
        remaining -= _xp_to_advance(level)
        level += 1
    return level


class Daily(commands.Cog):

    def __init__(self, client):
        self.client = client
        self.mongo = HerupaMongo()

    def _col(self):
        return self.mongo.client["leveling"]["daily"]

    def _members(self):
        return self.mongo.client["leveling"]["members"]

    @commands.guild_only()
    @commands.command(name="daily")
    async def daily(self, ctx):
        now = datetime.now(EASTERN)
        today = now.date()
        uid = str(ctx.author.id)

        doc = self._col().find_one({"_id": uid}) or {}
        last = doc.get("last")  # "YYYY-MM-DD" or missing
        if last == today.isoformat():
            tomorrow = datetime.combine(today + timedelta(days=1),
                                        datetime.min.time(), EASTERN)
            wait = tomorrow - now
            hours, minutes = divmod(int(wait.total_seconds()) // 60, 60)
            await ctx.send(f"You already claimed today! Next claim in "
                           f"**{hours}h {minutes:02d}m**. "
                           f"Streak: **{doc.get('streak', 1)}** day(s).")
            return

        yesterday = (today - timedelta(days=1)).isoformat()
        streak = doc.get("streak", 0) + 1 if last == yesterday else 1
        mult = _multiplier(streak)
        gain = BASE_XP * mult

        old = self._members().find_one({"_id": uid}) or {}
        old_level = level_for_xp(int(old.get("xp", 0)))
        self._members().update_one({"_id": uid}, {"$inc": {"xp": gain}},
                                   upsert=True)
        new_level = level_for_xp(int(old.get("xp", 0)) + gain)
        self._col().update_one(
            {"_id": uid},
            {"$set": {"last": today.isoformat(), "streak": streak}},
            upsert=True)

        lines = [f"💰 **+{gain} XP**" +
                 (f" ({BASE_XP} x **{mult}** streak bonus)" if mult > 1 else ""),
                 f"🔥 Streak: **{streak}** day(s)"]
        milestone = _next_milestone(streak)
        if milestone is not None:
            days, next_mult = milestone
            lines.append(f"Keep it going: **{next_mult}x** at {days} days "
                         f"({days - streak} to go).")
        else:
            lines.append("Max multiplier! Keep the streak alive.")
        if new_level > old_level:
            lines.append(f"⬆️ Level up! You're now level **{new_level}**.")

        embed = discord.Embed(colour=PINK, description="\n".join(lines))
        embed.set_author(name=f"{ctx.author.display_name}'s daily",
                         icon_url=ctx.author.display_avatar.url)
        embed.set_footer(text="Resets at midnight Eastern. Miss a day and the streak starts over.")
        await ctx.send(embed=embed)


async def setup(client):
    await client.add_cog(Daily(client))
