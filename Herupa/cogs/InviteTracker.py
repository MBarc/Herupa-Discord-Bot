'''
Purpose: Invite tracking — record who invited each new member.

On join, Herupa compares the guild's current invite `uses` against a cached
snapshot to find which invite was used, attributes the join to that invite's
creator, logs "X joined — invited by Y" to the join-and-leave-log channel, and
stores it (queryable with $invitedby / $invites).

Requires the members intent (join events) and **Manage Guild** (to read the
guild's invites — Herupa has it via admin today; keep it if admin is stripped).
Limitation shared by every invite tracker: joins that happen while Herupa is
offline can't be attributed (the cached snapshot goes stale).
'''

import sys
import os
import time
import asyncio

import discord
from discord.ext import commands
from discord.utils import get

current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
sys.path.append(parent_dir)

from tools.HerupaMongo import HerupaMongo

LOG_CHANNEL_NAME = "📄join-and-leave-log📄"


class InviteTracker(commands.Cog):

    def __init__(self, client):
        self.client = client
        self.db = "invites"
        self.col = "joins"
        self.mongo = HerupaMongo()
        # guild_id -> {code: {"uses", "inviter_id", "inviter_name"}}
        self.cache = {}

    # ------------------------- invite counter -------------------------
    # A persistent per-inviter running total, seeded from the old bot's log
    # history. This is what "who now has N invites" reports. Discord's own
    # invite `uses` can't be used for this: it resets per invite link, so it
    # loses the historical total the community is used to seeing.

    def _counts(self):
        return self.mongo.client[self.db]["counts"]

    def _bump_count(self, inviter_id, delta):
        """Adjust an inviter's running total and return the new value (min 0)."""
        col = self._counts()
        col.update_one({"_id": str(inviter_id)}, {"$inc": {"count": delta}}, upsert=True)
        n = (col.find_one({"_id": str(inviter_id)}) or {}).get("count", 0)
        if n < 0:
            n = 0
            col.update_one({"_id": str(inviter_id)}, {"$set": {"count": 0}})
        return n

    # ------------------------- snapshot upkeep -------------------------

    def _pack(self, invites):
        return {
            i.code: {
                "uses": i.uses or 0,
                "inviter_id": str(i.inviter.id) if i.inviter else None,
                "inviter_name": i.inviter.name if i.inviter else "unknown",
            }
            for i in invites
        }

    async def _snapshot(self, guild):
        try:
            invites = await guild.invites()
        except (discord.Forbidden, discord.HTTPException):
            return
        self.cache[guild.id] = self._pack(invites)

    async def cog_load(self):
        # on_ready is unreliable on this bot (custom client.start() + cogwatch, so it
        # only fires on reconnect), so prime by waiting for the guild cache to fill.
        asyncio.create_task(self._prime_when_ready())

    async def _prime_when_ready(self):
        for _ in range(120):
            if self.client.guilds:
                for g in self.client.guilds:
                    await self._snapshot(g)
                print(f"[InviteTracker] invite cache primed: "
                      f"{ {gid: len(v) for gid, v in self.cache.items()} }", flush=True)
                return
            await asyncio.sleep(2)

    @commands.Cog.listener()
    async def on_ready(self):
        # Re-prime after a reconnect.
        for g in self.client.guilds:
            await self._snapshot(g)

    @commands.Cog.listener()
    async def on_invite_create(self, invite):
        self.cache.setdefault(invite.guild.id, {})[invite.code] = {
            "uses": invite.uses or 0,
            "inviter_id": str(invite.inviter.id) if invite.inviter else None,
            "inviter_name": invite.inviter.name if invite.inviter else "unknown",
        }

    @commands.Cog.listener()
    async def on_invite_delete(self, invite):
        self.cache.get(invite.guild.id, {}).pop(invite.code, None)

    # ------------------------- attribution -------------------------

    @commands.Cog.listener()
    async def on_member_join(self, member):
        if member.bot:
            return
        guild = member.guild
        before = self.cache.get(guild.id)

        try:
            current = await guild.invites()
        except (discord.Forbidden, discord.HTTPException):
            current = None

        inviter_id = inviter_name = code = None
        if current is not None and before is not None:
            after = {i.code: i for i in current}
            # 1) an invite whose use count went up
            for c, inv in after.items():
                if (inv.uses or 0) > before.get(c, {}).get("uses", 0):
                    code = c
                    inviter_id = str(inv.inviter.id) if inv.inviter else None
                    inviter_name = inv.inviter.name if inv.inviter else "unknown"
                    break
            # 2) else a single-use invite that was consumed and auto-deleted
            if code is None:
                vanished = [c for c in before if c not in after]
                if len(vanished) == 1:
                    code = vanished[0]
                    inviter_id = before[code].get("inviter_id")
                    inviter_name = before[code].get("inviter_name", "unknown")
            self.cache[guild.id] = self._pack(current)
        elif current is not None:
            # No baseline yet (fresh start) — can't attribute this one; prime for next time.
            self.cache[guild.id] = self._pack(current)

        # Bump the inviter's persistent running total and show the new value.
        invite_count = self._bump_count(inviter_id, 1) if inviter_id else None

        self.mongo.addCollectionEntry(database_name=self.db, collection_name=self.col, payload={
            "guild_id": str(guild.id), "member_id": str(member.id), "member_name": str(member),
            "inviter_id": inviter_id, "inviter_name": inviter_name, "code": code,
            "invite_count": invite_count, "joined_at": int(time.time()),
        })

        log = get(guild.text_channels, name=LOG_CHANNEL_NAME)
        if log is not None:
            # Show the joiner by name (as text): a mention of a brand-new member
            # renders as a raw ID for viewers who don't have them cached yet, and
            # we suppress pings in the log so the mention isn't resolvable.
            who = f"**{member.display_name}**"
            if inviter_id and invite_count is not None:
                unit = "invite" if invite_count == 1 else "invites"
                desc = (f"📥 {who} joined, invited by <@{inviter_id}>, "
                        f"who now has **{invite_count}** {unit}.")
            elif inviter_id:
                desc = f"📥 {who} joined, invited by <@{inviter_id}>."
            else:
                desc = (f"📥 {who} joined. Inviter unknown "
                        "(vanity link, another bot, or I was offline at join time).")
            embed = discord.Embed(description=desc, colour=0x2ECC71)
            try:
                await log.send(embed=embed, allowed_mentions=discord.AllowedMentions.none())
            except discord.HTTPException:
                pass

    @commands.Cog.listener()
    async def on_member_remove(self, member):
        if member.bot:
            return
        guild = member.guild

        # Look up how they joined from the stored records (most recent wins).
        rec = None
        for r in self._records():
            if r.get("guild_id") == str(guild.id) and r.get("member_id") == str(member.id):
                rec = r
        inviter_id = rec.get("inviter_id") if rec else None

        # Someone their inviter brought in has left, so drop the inviter's total
        # by one (mirrors how the old bot's count went down on departures).
        if inviter_id:
            self._bump_count(inviter_id, -1)

        log = get(guild.text_channels, name=LOG_CHANNEL_NAME)
        if log is None:
            return
        if inviter_id:
            desc = f"📤 **{member.display_name}** left the server, they were invited by <@{inviter_id}>."
        else:
            desc = f"📤 **{member.display_name}** left the server. I couldn't figure out how they joined."
        embed = discord.Embed(description=desc, colour=0x888888)
        try:
            await log.send(embed=embed, allowed_mentions=discord.AllowedMentions.none())
        except discord.HTTPException:
            pass

    # ------------------------- lookups -------------------------

    def _records(self):
        return self.mongo.returnCollectionEntries(database_name=self.db, collection_name=self.col)

    @commands.command(name="invitedby")
    async def invitedby(self, ctx, member: discord.Member = None):
        """Show who invited a member."""
        member = member or ctx.author
        rec = None
        for r in self._records():
            if r.get("guild_id") == str(ctx.guild.id) and r.get("member_id") == str(member.id):
                rec = r  # most recent join wins
        none = discord.AllowedMentions.none()
        if rec and rec.get("inviter_id"):
            await ctx.send(f"{member.mention} was invited by <@{rec['inviter_id']}>.", allowed_mentions=none)
        elif rec:
            await ctx.send(f"I couldn't determine who invited {member.mention} "
                           "(vanity link, a bot, or I was offline at the time).", allowed_mentions=none)
        else:
            await ctx.send(f"No invite record for {member.mention} — they joined before I started tracking.",
                           allowed_mentions=none)

    @commands.command(name="invites", aliases=["invited"])
    async def invites(self, ctx, member: discord.Member = None):
        """Show who a member has invited."""
        member = member or ctx.author
        invited = [r for r in self._records()
                   if r.get("guild_id") == str(ctx.guild.id) and r.get("inviter_id") == str(member.id)]
        none = discord.AllowedMentions.none()
        if not invited:
            await ctx.send(f"{member.mention} hasn't invited anyone I've tracked yet.", allowed_mentions=none)
            return
        names = ", ".join(f"<@{r['member_id']}>" for r in invited[:25])
        more = f" (+{len(invited) - 25} more)" if len(invited) > 25 else ""
        await ctx.send(f"{member.mention} has invited **{len(invited)}** member(s): {names}{more}",
                       allowed_mentions=none)


async def setup(client):
    await client.add_cog(InviteTracker(client))
