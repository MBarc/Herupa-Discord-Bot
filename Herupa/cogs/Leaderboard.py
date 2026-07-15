'''
Purpose: Server leaderboards. Herupa tracks four stats for every member, each
kept two ways (this calendar month and all-time):
  - messages sent
  - voice time (time in non-AFK voice channels)
  - AFK time (time in the guild's configured AFK channel)
  - invites (read from the InviteTracker data)

$leaderboard / $lb opens a reaction-driven menu (like $help):
  - $lb            flip through the four boards with ◀ ▶; 📅 toggles month/all-time.
  - $lb <stat>     just that board; ◀ ▶ toggles between its monthly and all-time pages.

Stats other than all-time invites start from zero and fill in over time, since
Herupa can't retroactively know past activity.
'''

import asyncio
import datetime
import os
import sys
import time

import discord
from discord.ext import commands, tasks

current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
sys.path.append(parent_dir)

from tools.HerupaMongo import HerupaMongo

STATS_DB = "stats"
STATS_COL = "members"
INVITES_DB = "invites"
INVITES_COL = "counts"
PINK = discord.Colour.from_rgb(255, 183, 197)
TOP_N = 10

# board key -> display config. Order here is the order $lb flips through.
METRICS = {
    "voice":    {"label": "Voice Time",    "emoji": "🔊", "kind": "duration"},
    "invites":  {"label": "Invites",       "emoji": "📨", "kind": "invites"},
    "afk":      {"label": "AFK Time",       "emoji": "💀", "kind": "duration"},
    "messages": {"label": "Messages Sent", "emoji": "💬", "kind": "count"},
}
ORDER = list(METRICS.keys())
ALIASES = {
    "voice": "voice", "vc": "voice",
    "invites": "invites", "invite": "invites", "inv": "invites",
    "afk": "afk",
    "messages": "messages", "message": "messages", "msg": "messages", "msgs": "messages",
}

# Monthly champions: whoever finished #1 last month in each category gets a big
# XP boost, announced at the start of the new month. Single tunable amount.
CHAMPION_XP = 1500
CHAMPION_CATEGORIES = ORDER          # all four boards reward their monthly #1
CHAMPIONS_DB, CHAMPIONS_COL = "champions", "state"


def month_key(when=None):
    when = when or datetime.datetime.now(datetime.timezone.utc)
    return when.strftime("%Y-%m")


def prev_month_key(cur):
    """The 'YYYY-MM' before a given 'YYYY-MM'."""
    y, m = map(int, cur.split("-"))
    return f"{y - 1:04d}-12" if m == 1 else f"{y:04d}-{m - 1:02d}"


def fmt_duration(seconds):
    seconds = int(seconds)
    if seconds < 60:
        return f"{seconds}s"
    minutes, _ = divmod(seconds, 60)
    if minutes < 60:
        return f"{minutes}m"
    hours, minutes = divmod(minutes, 60)
    if hours < 24:
        return f"{hours}h {minutes}m"
    days, hours = divmod(hours, 24)
    return f"{days}d {hours}h"


def fmt_value(kind, value):
    if kind == "duration":
        return fmt_duration(value)
    if kind == "invites":
        return f"{int(value)} invite" + ("" if int(value) == 1 else "s")
    return f"{int(value):,} messages"


class Leaderboard(commands.Cog):

    def __init__(self, client):
        self.client = client
        self.mongo = HerupaMongo()
        # (guild_id, user_id) -> (channel_id, start_unix) for open voice sessions
        self._voice_since = {}

    async def cog_load(self):
        # Capture anyone already in voice so a restart doesn't lose their session.
        asyncio.create_task(self._prime_voice())
        self.champion_check.start()

    async def cog_unload(self):
        self.champion_check.cancel()

    async def _prime_voice(self):
        for _ in range(60):
            if self.client.guilds:
                break
            await asyncio.sleep(2)
        now = time.time()
        for g in self.client.guilds:
            for vc in g.voice_channels:
                for m in vc.members:
                    if not m.bot:
                        self._voice_since[(g.id, m.id)] = (vc.id, now)

    # --------------------------- storage ---------------------------

    def _stats(self):
        return self.mongo.client[STATS_DB][STATS_COL]

    def _bump(self, user_id, metric, amount):
        if amount <= 0:
            return
        mk = month_key()
        self._stats().update_one(
            {"_id": str(user_id)},
            {"$inc": {f"{metric}.total": amount, f"{metric}.{mk}": amount}},
            upsert=True)

    # --------------------------- trackers ---------------------------

    @commands.Cog.listener()
    async def on_message(self, message):
        if message.author.bot or message.guild is None:
            return
        self._bump(message.author.id, "messages", 1)

    @commands.Cog.listener()
    async def on_voice_state_update(self, member, before, after):
        if member.bot:
            return
        now = time.time()
        key = (member.guild.id, member.id)

        # Close the previous session and bank the elapsed time.
        prev = self._voice_since.pop(key, None)
        if prev:
            chan_id, start = prev
            elapsed = int(now - start)
            afk = member.guild.afk_channel
            metric = "afk" if (afk and chan_id == afk.id) else "voice"
            self._bump(member.id, metric, elapsed)

        # Open a new session if they're still connected somewhere.
        if after.channel is not None:
            self._voice_since[key] = (after.channel.id, now)

    # --------------------------- querying ---------------------------

    def _rows(self, metric, window):
        """List of (user_id, value) for a metric, sorted high to low.
        window is 'total' or a 'YYYY-MM' key."""
        rows = []
        if metric == "invites":
            for d in self.mongo.client[INVITES_DB][INVITES_COL].find():
                v = d.get("count", 0) if window == "total" else (d.get("months") or {}).get(window, 0)
                if v and v > 0:
                    rows.append((d["_id"], v))
        else:
            for d in self._stats().find():
                v = (d.get(metric) or {}).get(window, 0)
                if v and v > 0:
                    rows.append((d["_id"], v))
        rows.sort(key=lambda x: -x[1])
        return rows

    def _board_embed(self, guild, viewer, metric, window):
        info = METRICS[metric]
        scope = "This Month" if window != "total" else "All-Time"
        rows = self._rows(metric, window)
        medals = ["🥇", "🥈", "🥉"]

        lines, viewer_rank = [], None
        for i, (uid, val) in enumerate(rows):
            if str(uid) == str(viewer.id):
                viewer_rank = (i + 1, val)
        for i, (uid, val) in enumerate(rows[:TOP_N]):
            member = guild.get_member(int(uid))
            name = member.display_name if member else "Unknown member"
            rank = medals[i] if i < 3 else f"`#{i + 1}`"
            lines.append(f"{rank} **{name}**  ·  {fmt_value(info['kind'], val)}")

        desc = "\n".join(lines) if lines else "No data yet. Check back once people have been active!"
        embed = discord.Embed(title=f"{info['emoji']}  {info['label']}  ·  {scope}",
                              description=desc, colour=PINK)
        if viewer_rank and viewer_rank[0] > TOP_N:
            embed.add_field(name="Your rank",
                            value=f"#{viewer_rank[0]}  ·  {fmt_value(info['kind'], viewer_rank[1])}",
                            inline=False)
        return embed

    # --------------------------- monthly champions ---------------------------

    def _champions(self):
        return self.mongo.client[CHAMPIONS_DB][CHAMPIONS_COL]

    @tasks.loop(hours=6)
    async def champion_check(self):
        """Once a month has fully ended, pay its #1s and announce them. Runs a few
        times a day and is idempotent, so a restart or a late start still pays out
        exactly once."""
        col = self._champions()
        cur = month_key()

        # First run ever: remember when we started so we never reach back and
        # "award" months that predate this feature (their data is partial/empty).
        meta = col.find_one({"_id": "meta"})
        if meta is None:
            col.insert_one({"_id": "meta", "start_month": cur})
            return

        prev = prev_month_key(cur)
        if prev < meta["start_month"] or col.find_one({"_id": prev}):
            return  # before we started, or already paid out
        if not self.client.guilds:
            return  # need the guild to announce / resolve members; try next tick
        await self._award_month(prev)

    async def _award_month(self, month):
        guild = self.client.guilds[0]
        leveling = self.client.get_cog("Leveling")
        if leveling is None:
            return  # can't pay XP without it; retry next tick

        winners = {}
        for metric in CHAMPION_CATEGORIES:
            rows = self._rows(metric, month)
            if rows:
                winners[metric] = rows[0]  # (user_id, value), already sorted desc

        # Mark the month done BEFORE paying so a mid-way crash can't double-pay.
        self._champions().insert_one(
            {"_id": month,
             "winners": {m: {"id": str(u), "value": v} for m, (u, v) in winners.items()}})

        for uid, _ in winners.values():
            leveling._add_xp(int(uid), CHAMPION_XP)

        if winners:
            await self._announce_champions(guild, month, winners)

    async def _announce_champions(self, guild, month, winners):
        channel = guild.system_channel or discord.utils.get(guild.text_channels, name="🤠general-chat🤠")
        if channel is None:
            return
        title = datetime.datetime.strptime(month, "%Y-%m").strftime("%B %Y")

        lines, mentions = [], []
        for metric in CHAMPION_CATEGORIES:
            if metric not in winners:
                continue
            uid, val = winners[metric]
            info = METRICS[metric]
            member = guild.get_member(int(uid))
            name = member.mention if member else "Unknown member"
            if member and member.mention not in mentions:
                mentions.append(member.mention)
            lines.append(f"{info['emoji']}  **{info['label']}** — {name}  ·  {fmt_value(info['kind'], val)}")

        embed = discord.Embed(
            title=f"👑  {title} Champions!  👑",
            description=(f"Last month's top chillers each earned **+{CHAMPION_XP:,} XP**! "
                         "New month, fresh race, go get it! 🏆\n\n" + "\n".join(lines)),
            colour=PINK)
        try:
            await channel.send(content=" ".join(mentions) or None, embed=embed)
        except discord.HTTPException:
            pass

    # --------------------------- command ---------------------------

    @commands.guild_only()
    @commands.command(name="leaderboard", aliases=["lb"])
    async def leaderboard(self, ctx, stat: str = None):
        """Show the server leaderboards."""
        metrics = ORDER
        if stat is not None:
            key = ALIASES.get(stat.lower())
            if key is None:
                await ctx.send("Unknown board. Try one of: "
                               + ", ".join(f"`{m}`" for m in ORDER)
                               + "  (or just `$lb` for all of them).")
                return
            metrics = [key]

        idx = 0
        window = "total"  # all-time by default

        def render():
            metric = metrics[idx]
            embed = self._board_embed(ctx.guild, ctx.author, metric, window)
            if len(metrics) > 1:
                embed.set_footer(text="◀ ▶ switch board   ·   📅 month / all-time   ·   ❌ close")
            else:
                embed.set_footer(text="◀ ▶ month / all-time   ·   ❌ close")
            return embed

        controls = ["◀️", "▶️", "📅", "❌"]

        def check(reaction, user):
            return (user == ctx.author and reaction.message.id == message.id
                    and str(reaction.emoji) in controls)

        message = await ctx.send(embed=render())
        for e in controls:
            await message.add_reaction(e)

        while True:
            try:
                reaction, user = await self.client.wait_for("reaction_add", timeout=120, check=check)
            except asyncio.TimeoutError:
                try:
                    await message.clear_reactions()
                except discord.HTTPException:
                    pass
                break

            emoji = str(reaction.emoji)
            if emoji == "❌":
                await message.delete()
                break
            elif emoji == "📅":
                window = month_key() if window == "total" else "total"
            elif emoji in ("◀️", "▶️"):
                if len(metrics) > 1:
                    step = 1 if emoji == "▶️" else -1
                    idx = (idx + step) % len(metrics)
                else:
                    # Single board: the two pages are monthly and all-time.
                    window = month_key() if window == "total" else "total"

            await message.edit(embed=render())
            try:
                await message.remove_reaction(reaction, user)
            except discord.HTTPException:
                pass


async def setup(client):
    await client.add_cog(Leaderboard(client))
