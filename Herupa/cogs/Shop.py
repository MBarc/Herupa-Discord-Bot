'''
Purpose: A level shop. XP/levels are the currency: buying an item priced at N
levels drops the buyer's level by N (their XP is set to the floor of the new
level). Spending real levels also lowers leaderboard standing, that tradeoff is
intentional.

Items:
  - Name colors (2 levels): equip a color role; $removecolor takes it off free.
  - Vanity title roles (3-5 levels): cosmetic flex roles.
  - Name your voice room (3 levels): a custom name for your auto-created VC.
  - Change someone's nickname (3 levels): the prank, with guardrails (no staff/
    bots, 32-char cap, slur-filtered, logged to law-chat, target can undo).

Commands: $shop to browse, $buy <item> [options], $removecolor.
'''

import os
import re
import sys

import discord
from discord.ext import commands
from discord.utils import get
from better_profanity import profanity

current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
sys.path.append(parent_dir)

from tools.HerupaMongo import HerupaMongo

PINK = discord.Colour.from_rgb(255, 183, 197)
COLOR_NAMES = ["Pink", "Red", "Orange", "Gold", "Green", "Teal", "Blue", "Purple"]
COLOR_COST = 2
TITLES = {"Certified Chiller": 3, "Chill Veteran": 5, "Big Spender": 5}
ROOMNAME_COST = 3
NICKNAME_COST = 3
STAFF_ROLES = {"head chill", "sheriff", "deputy"}
LAW_CHAT = 803751026355863553


# --- MEE6 level curve (same as the Leveling cog) ---
def _xp_to_advance(level):
    return 5 * level * level + 50 * level + 100

def total_xp_for_level(level):
    return sum(_xp_to_advance(n) for n in range(level))

def level_for_xp(total_xp):
    level, remaining = 0, int(total_xp)
    while remaining >= _xp_to_advance(level):
        remaining -= _xp_to_advance(level)
        level += 1
    return level


class Shop(commands.Cog):

    def __init__(self, client):
        self.client = client
        self.mongo = HerupaMongo()

    # --------------------------- currency ---------------------------
    def _lvl_col(self):
        return self.mongo.client["leveling"]["members"]

    def _level(self, uid):
        doc = self._lvl_col().find_one({"_id": str(uid)})
        return level_for_xp(int(doc["xp"])) if doc and "xp" in doc else 0

    def _spend(self, uid, cost):
        """Deduct `cost` levels. Returns (ok, level_after_or_current)."""
        lvl = self._level(uid)
        if lvl < cost:
            return False, lvl
        self._lvl_col().update_one({"_id": str(uid)},
                                   {"$set": {"xp": total_xp_for_level(lvl - cost)}}, upsert=True)
        return True, lvl - cost

    async def _afford_fail(self, ctx, cost, have):
        await ctx.send(f"You need **{cost} levels** for that, but you're only level **{have}**. "
                       f"Keep chatting and hanging out to level up!")

    # --------------------------- $shop ---------------------------
    @commands.guild_only()
    @commands.command(name="shop")
    async def shop(self, ctx):
        embed = discord.Embed(
            title="🛒  Level Shop",
            description=("Spend your levels on rewards. Buying something drops your level by its price "
                         f"(you're currently level **{self._level(ctx.author.id)}**).\n​"),
            colour=PINK)
        embed.add_field(
            name="🎨  Name Colors  ·  2 levels",
            value=(", ".join(COLOR_NAMES) + "\n`$buy color <name>` to equip  ·  `$removecolor` to take it off (free)"),
            inline=False)
        embed.add_field(
            name="🏅  Titles",
            value="\n".join(f"**{t}** ({c} levels)  ·  `$buy title {t.split()[0].lower()}`"
                            for t, c in TITLES.items()),
            inline=False)
        embed.add_field(
            name="🎙️  Name Your Voice Room  ·  3 levels",
            value="`$buy roomname <name>` gives your auto-created voice room a custom name.",
            inline=False)
        embed.add_field(
            name="😈  Change a Nickname  ·  3 levels",
            value="`$buy nickname @user <new name>` renames someone (not staff or bots).",
            inline=False)
        embed.set_footer(text="Prices are in levels. Spending lowers your leaderboard rank too.")
        await ctx.send(embed=embed)

    # --------------------------- $buy ---------------------------
    @commands.guild_only()
    @commands.command(name="buy")
    async def buy(self, ctx, item: str = None, *, rest: str = None):
        item = (item or "").lower()
        if item == "color":
            await self._buy_color(ctx, rest)
        elif item == "title":
            await self._buy_title(ctx, rest)
        elif item == "roomname":
            await self._buy_roomname(ctx, rest)
        elif item == "nickname":
            await self._buy_nickname(ctx, rest)
        else:
            await ctx.send("Usage: `$buy color <name>`, `$buy title <name>`, "
                           "`$buy roomname <name>`, or `$buy nickname @user <name>`. See `$shop`.")

    async def _buy_color(self, ctx, name):
        if not name:
            await ctx.send("Pick a color: " + ", ".join(COLOR_NAMES)); return
        match = next((c for c in COLOR_NAMES if c.lower() == name.strip().lower()), None)
        if match is None:
            await ctx.send("Unknown color. Options: " + ", ".join(COLOR_NAMES)); return
        role = get(ctx.guild.roles, name=match)
        if role is None:
            await ctx.send("That color role is missing, let staff know."); return
        if role in ctx.author.roles:
            await ctx.send(f"You already have **{match}**! Use `$removecolor` to take it off."); return
        ok, lvl = self._spend(ctx.author.id, COLOR_COST)
        if not ok:
            await self._afford_fail(ctx, COLOR_COST, lvl); return
        old = [r for r in ctx.author.roles if r.name in COLOR_NAMES]
        if old:
            await ctx.author.remove_roles(*old, reason="shop: color swap")
        await ctx.author.add_roles(role, reason="shop: color purchase")
        await ctx.send(f"🎨 {ctx.author.mention} is now **{match}**! (-{COLOR_COST} levels, you're level **{lvl}**)")

    async def _buy_title(self, ctx, name):
        if not name:
            await ctx.send("Titles: " + ", ".join(TITLES)); return
        key = name.strip().lower()
        match = next((t for t in TITLES if t.lower() == key or t.split()[0].lower() == key), None)
        if match is None:
            await ctx.send("Unknown title. Options: " + ", ".join(TITLES)); return
        role = get(ctx.guild.roles, name=match)
        if role in ctx.author.roles:
            await ctx.send(f"You already own **{match}**."); return
        cost = TITLES[match]
        ok, lvl = self._spend(ctx.author.id, cost)
        if not ok:
            await self._afford_fail(ctx, cost, lvl); return
        await ctx.author.add_roles(role, reason="shop: title purchase")
        await ctx.send(f"🏅 {ctx.author.mention} earned the **{match}** title! (-{cost} levels, you're level **{lvl}**)")

    async def _buy_roomname(self, ctx, name):
        if not name:
            await ctx.send("Usage: `$buy roomname <name>`"); return
        name = name.strip()[:30]
        if profanity.contains_profanity(name):
            await ctx.send("Let's keep it clean, pick a different room name."); return
        ok, lvl = self._spend(ctx.author.id, ROOMNAME_COST)
        if not ok:
            await self._afford_fail(ctx, ROOMNAME_COST, lvl); return
        self.mongo.client["roomnames"]["names"].update_one(
            {"_id": str(ctx.author.id)}, {"$set": {"name": name}}, upsert=True)
        await ctx.send(f"🎙️ Your voice room will now be named **{name}**! "
                       f"(-{ROOMNAME_COST} levels, you're level **{lvl}**) It applies to your next room.")

    async def _buy_nickname(self, ctx, rest):
        if not ctx.message.mentions or not rest:
            await ctx.send("Usage: `$buy nickname @user <new name>`"); return
        target = ctx.message.mentions[0]
        nick = re.sub(r"<@!?\d+>", "", rest).strip()[:32]
        if not nick:
            await ctx.send("Give them an actual nickname: `$buy nickname @user <new name>`"); return
        if target.bot:
            await ctx.send("You can't nickname a bot."); return
        if any(r.name.lower() in STAFF_ROLES for r in target.roles):
            await ctx.send("You can't nickname staff. Nice try."); return
        if profanity.contains_profanity(nick):
            await ctx.send("That nickname isn't allowed."); return
        ok, lvl = self._spend(ctx.author.id, NICKNAME_COST)
        if not ok:
            await self._afford_fail(ctx, NICKNAME_COST, lvl); return
        try:
            await target.edit(nick=nick, reason=f"shop nickname by {ctx.author}")
        except discord.Forbidden:
            # refund and bail if Discord blocks it (target ranked above Herupa)
            self._lvl_col().update_one({"_id": str(ctx.author.id)},
                                       {"$set": {"xp": total_xp_for_level(lvl + NICKNAME_COST)}})
            await ctx.send("I can't change that member's nickname (they outrank me). Refunded."); return
        await ctx.send(f"😈 {ctx.author.mention} renamed {target.mention} to **{nick}**! "
                       f"(-{NICKNAME_COST} levels, you're level **{lvl}**)")
        log = ctx.guild.get_channel(LAW_CHAT)
        if log:
            try:
                await log.send(embed=discord.Embed(
                    description=f"😈 {ctx.author.mention} used the shop to nickname {target.mention} to **{nick}**.",
                    colour=0x888888), allowed_mentions=discord.AllowedMentions.none())
            except discord.HTTPException:
                pass

    @commands.guild_only()
    @commands.command(name="removecolor", aliases=["uncolor"])
    async def removecolor(self, ctx):
        old = [r for r in ctx.author.roles if r.name in COLOR_NAMES]
        if not old:
            await ctx.send("You don't have a color equipped."); return
        await ctx.author.remove_roles(*old, reason="shop: removed color")
        await ctx.send(f"🎨 Removed your color, {ctx.author.mention}. Grab a new one anytime with `$buy color <name>`.")


async def setup(client):
    await client.add_cog(Shop(client))
