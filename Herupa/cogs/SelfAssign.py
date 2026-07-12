'''
Purpose: Button-based self-assign role panels (replaces the old reaction-role
$createreactmessage system).

Staff run $rolepanel to post a panel of buttons in the current channel;
members click a button to toggle the matching role on/off, with a private
(ephemeral) confirmation. Panels are STATELESS: each button's custom_id
carries the role ID, so panels keep working across restarts (registered as a
DynamicItem) and need no database. Deleting the panel message is the only
cleanup there is, and there is no reaction-event replay to miss — the button
reads your CURRENT roles at click time, so state can't drift.

Usage:
    $rolepanel <title...> <@role> [<@role> ...]
    $rolepanel single <title...> <@role> [<@role> ...]

"single" makes the panel exclusive: picking a role removes the panel's other
roles from you (e.g. pick exactly one pronoun; click your current one to clear
it). An emoji placed right before a role mention becomes that button's emoji:
    $rolepanel Pick a region! 🍁 @america 🍺 @europe

Safety: the invoker needs Manage Roles and may only offer roles that sit below
BOTH their own top role and Herupa's; managed/integration roles and roles
carrying moderation-level permissions are refused. The same checks run again
on every click, so a role that is later given dangerous permissions (or moved
above Herupa) stops being grantable instead of becoming an escalation hole.
'''

import asyncio
import re
import sys
import os
import traceback

import discord
from discord.ext import commands

# Ephemeral confirmations delete themselves after this many seconds so they
# don't linger in the member's view until they navigate away or dismiss them.
AUTO_DISMISS_SECONDS = 6

# Get the parent directory of the current script
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)

# Add the parent directory to the Python path so we can import our custom library
sys.path.append(parent_dir)

from tools.HerupaLogger import HerupaLogger

# custom_id layout: herupa:role:<mode>:<role_id>  (mode: t=toggle, s=single)
CUSTOM_ID_RE = r"herupa:role:(?P<mode>[ts]):(?P<role_id>[0-9]+)"

# A role holding ANY of these is never self-assignable, no matter who made the panel.
ELEVATED = discord.Permissions(
    administrator=True, kick_members=True, ban_members=True,
    manage_channels=True, manage_guild=True, manage_messages=True,
    manage_roles=True, manage_webhooks=True, manage_nicknames=True,
    mention_everyone=True, moderate_members=True, manage_threads=True,
    manage_events=True, view_audit_log=True,
)


def role_problem(role, guild):
    """Why this role may not be self-assigned — or None if it's fine."""
    if role is None:
        return "the role no longer exists"
    if role.is_default() or role.managed:
        return f"**{role.name}** is managed by Discord or an integration"
    if role >= guild.me.top_role:
        return f"**{role.name}** is above my highest role"
    if role.permissions.value & ELEVATED.value:
        return f"**{role.name}** carries moderation permissions"
    return None


class RoleButton(discord.ui.DynamicItem[discord.ui.Button], template=CUSTOM_ID_RE):
    """One self-assign button. Everything it needs is in its custom_id."""

    def __init__(self, role_id, mode="t", label=None, emoji=None):
        self.role_id = role_id
        self.mode = mode
        super().__init__(discord.ui.Button(
            label=label, emoji=emoji, style=discord.ButtonStyle.secondary,
            custom_id=f"herupa:role:{mode}:{role_id}"))

    @classmethod
    async def from_custom_id(cls, interaction, item, match):
        return cls(int(match["role_id"]), match["mode"])

    async def callback(self, interaction):
        # Interactions have a hard 3-second ACK deadline, so defer before any work.
        await interaction.response.defer(ephemeral=True)
        try:
            message = await self._toggle(interaction)
        except Exception:
            traceback.print_exc()
            try:
                await HerupaLogger(interaction.client).send("error", embed=discord.Embed(
                    title="SELF-ASSIGN BUTTON FAILED",
                    description=f"role_id `{self.role_id}` in {interaction.channel.mention}\n```{traceback.format_exc()[-900:]}```",
                    colour=discord.Colour.red()))
            except discord.HTTPException:
                pass
            message = "Something went wrong. Please let staff know."
        if message:
            await self._reply(interaction, message)

    async def _reply(self, interaction, text):
        """Send an ephemeral confirmation that removes itself after a short delay."""
        try:
            sent = await interaction.followup.send(text, ephemeral=True)
        except discord.HTTPException:
            return
        await asyncio.sleep(AUTO_DISMISS_SECONDS)
        try:
            await sent.delete()
        except discord.HTTPException:
            pass  # already dismissed by the member, or the token expired

    async def _toggle(self, interaction):
        guild = interaction.guild
        member = interaction.user
        if guild is None or not isinstance(member, discord.Member):
            return None

        role = guild.get_role(self.role_id)
        problem = role_problem(role, guild)
        if problem:
            return f"I can't manage this role anymore ({problem}). Please let staff know."

        if role in member.roles:
            await member.remove_roles(role, reason="self-assign panel")
            return f"➖ Removed **{role.name}**."

        # Exclusive panels: drop the panel's other roles before adding this one.
        swapped_out = []
        if self.mode == "s":
            for other_id in self._sibling_role_ids(interaction.message):
                other = guild.get_role(other_id)
                if other and other != role and other in member.roles \
                        and role_problem(other, guild) is None:
                    swapped_out.append(other)
        if swapped_out:
            await member.remove_roles(*swapped_out, reason="self-assign panel (exclusive)")
        await member.add_roles(role, reason="self-assign panel")

        message = f"➕ You now have **{role.name}**."
        if swapped_out:
            message += " (Removed **" + "**, **".join(r.name for r in swapped_out) + "**.)"
        return message

    @staticmethod
    def _sibling_role_ids(message):
        """Role IDs of every self-assign button on this panel message."""
        ids = []
        for row in message.components:
            for child in getattr(row, "children", []):
                match = re.fullmatch(CUSTOM_ID_RE, getattr(child, "custom_id", "") or "")
                if match:
                    ids.append(int(match["role_id"]))
        return ids


class SelfAssign(commands.Cog):

    ROLE_MENTION = re.compile(r"<@&([0-9]+)>$")
    CUSTOM_EMOJI = re.compile(r"<a?:\w+:[0-9]+>$")

    def __init__(self, client):
        self.client = client

    async def cog_load(self):
        self.client.add_dynamic_items(RoleButton)

    async def cog_unload(self):
        self.client.remove_dynamic_items(RoleButton)

    def _looks_like_emoji(self, token):
        if self.CUSTOM_EMOJI.match(token):
            return True
        return all(ord(c) >= 0x2000 for c in token)

    def parse_spec(self, tokens):
        """Split the command tokens into (mode, title, [(role_id, emoji), ...])."""
        mode = "t"
        if tokens and tokens[0].lower() == "single":
            mode = "s"
            tokens = tokens[1:]

        title, entries, pending_emoji = [], [], None
        for token in tokens:
            mention = self.ROLE_MENTION.match(token)
            if mention:
                entries.append((int(mention.group(1)), pending_emoji))
                pending_emoji = None
                continue
            if self._looks_like_emoji(token):
                if pending_emoji:
                    title.append(pending_emoji)
                pending_emoji = token
                continue
            if pending_emoji:
                title.append(pending_emoji)
                pending_emoji = None
            title.append(token)
        if pending_emoji:
            title.append(pending_emoji)
        return mode, " ".join(title), entries

    @commands.guild_only()
    @commands.has_guild_permissions(manage_roles=True)
    @commands.command(name="rolepanel",
                      description="Posts a panel of buttons that members click to give or remove roles on themselves. "
                                  "Start with 'single' to make the choices exclusive (picking one removes the others).",
                      brief="Creates a self-assign role button panel.",
                      aliases=["rp"])
    async def RolePanel(self, ctx):

        mode, title, entries = self.parse_spec(ctx.message.content.split()[1:])

        if not entries:
            await ctx.send('Usage: `$rolepanel [single] <title> @role1 @role2 ...` '
                           '(an emoji right before a role mention becomes that button\'s emoji)')
            return
        if len(entries) > 25:
            raise commands.BadArgument("Too many roles! A panel holds at most 25 buttons.")

        problems = []
        for role_id, _ in entries:
            role = ctx.guild.get_role(role_id)
            problem = role_problem(role, ctx.guild)
            if problem is None and ctx.author != ctx.guild.owner and role >= ctx.author.top_role:
                problem = f"**{role.name}** is not below your own highest role"
            if problem:
                problems.append(problem)
        if problems:
            raise commands.BadArgument("I can't offer these roles: " + "; ".join(problems))

        view = discord.ui.View(timeout=None)
        for role_id, emoji in entries:
            role = ctx.guild.get_role(role_id)
            view.add_item(RoleButton(role_id, mode, label=role.name,
                                     emoji=discord.PartialEmoji.from_str(emoji) if emoji else None))

        embed = discord.Embed(
            title=title or "Choose your roles!",
            description=("Pick one. Choosing another swaps it out. Click your current one to remove it."
                         if mode == "s" else
                         "Click a button to give yourself the role. Click again to remove it."),
            colour=discord.Colour.from_rgb(255, 183, 197))

        await ctx.send(embed=embed, view=view)
        try:
            await ctx.message.delete()
        except discord.HTTPException:
            pass


async def setup(client):
    await client.add_cog(SelfAssign(client))
