'''
Purpose: Project management inside Discord, built on forum channels.

Every project is a FORUM channel ($project create <name>, manager-gated).
Every task is a POST in that forum: create one the native Discord way (New
Post) or with $task from anywhere, and Herupa tracks it — she applies the
status tag, drops a task card (embed with Claim / Done buttons) into the
thread, and mirrors the metadata into Mongo. All discussion about a task
lives in its own thread, like Discord intended.

Inside a task thread:
  $assign @member   route the task (bare $assign takes it yourself)
  $due <when>       "friday", "tomorrow", "8/15", "in 3 days", "none" to clear
  $priority <p>     low / normal / high / urgent (urgent adds a 🔥 tag)
  $status <s>       todo / doing / review / done
  $done             finish the task (tags it ✅ and archives the thread)

Anywhere: $mytasks (your open tasks), $board (per-project status summary).

DAILY AUTOMATION (one pass per guild per day, from the hour set by config key
"daily_hour" in the guild's timezone — default 13:00, which in the default
UTC timezone lands around 9am US Eastern; dedupe state in "projects"/"meta"):
DM reminders to assignees for tasks due today/tomorrow,
overdue nudges posted into the task threads, and a morning digest to the
channel set with `$project digest` (config key digest_channel_id). Each piece
has its own $feature switch: project-reminders, project-nudges,
project-digest.

MULTI-SERVER: per-guild config in Mongo (db "projects", collection "config"):
{"guild_id", "forums": {"<forum_id>": {"name", "tags": {status -> tag id}}},
"default_reaction": "terranova", "timezone": "America/New_York"}, forums
written by $project create. The optional timezone (an IANA name) drives due
dates, the overdue math, and the daily pass; it defaults to UTC. The optional
daily_hour (0-23, in that timezone) moves the daily pass. The
optional default_reaction (a guild emoji NAME, or a unicode emoji) becomes
every new project forum's default post reaction. The optional "forum_roles"
list (role names, case-insensitive) locks every NEW project forum down to
those roles: @everyone loses view, the listed roles can see/post/reply.
Absent, the forum just inherits its category's permissions. Tasks live in "projects"/"tasks", one doc per
thread: {"guild_id", "forum_id", "thread_id", "title", "status", "priority",
"assignee_id", "due" (YYYY-MM-DD or None), "created_by", "created_at",
"completed_at", "embed_message_id"}. Config is read per event (project
activity is low-volume), so Mongo edits apply immediately.

Requires the guild to have forum channels (Community enabled). Respects the
$feature "projects" toggle, including the buttons and the forum listener.
'''

import re
import sys
import os
import time
import traceback
from datetime import datetime, timedelta, date
from zoneinfo import ZoneInfo

import discord
from discord.ext import commands, tasks

current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
sys.path.append(parent_dir)

from tools.HerupaMongo import HerupaMongo

UTC = ZoneInfo("UTC")
PINK = 0xFFB7C5

STATUSES = {"todo": ("📋", "To Do"), "doing": ("🔨", "In Progress"),
            "review": ("👀", "Review"), "done": ("✅", "Done")}
PRIORITIES = ("low", "normal", "high", "urgent")
TAG_NAMES = {"todo": "📋 To Do", "doing": "🔨 In Progress",
             "review": "👀 Review", "done": "✅ Done", "urgent": "🔥 Urgent"}

_WD = {}
for _i, _n in enumerate(["monday", "tuesday", "wednesday", "thursday",
                         "friday", "saturday", "sunday"]):
    _WD[_n] = _i
    _WD[_n[:3]] = _i
_MONTHS = {}
for _i, _n in enumerate(["january", "february", "march", "april", "may", "june",
                         "july", "august", "september", "october", "november",
                         "december"], 1):
    _MONTHS[_n] = _i
    _MONTHS[_n[:3]] = _i


def parse_due(text, tz):
    """'today', 'friday', '8/15', 'aug 15', 'in 3 days', 'none' ->
    date | "clear" | None (unreadable)."""
    text = text.strip().lower()
    today = datetime.now(tz).date()
    if text in ("none", "clear", "never"):
        return "clear"
    if text == "today":
        return today
    if text == "tomorrow":
        return today + timedelta(days=1)
    m = re.fullmatch(r"in (\d{1,3}) days?", text)
    if m:
        return today + timedelta(days=int(m.group(1)))
    wd = _WD.get(text.removeprefix("next "))
    if wd is not None:
        ahead = (wd - today.weekday()) % 7 or 7
        return today + timedelta(days=ahead)
    m = re.fullmatch(r"(\d{1,2})[/\-](\d{1,2})(?:[/\-](\d{4}))?", text)
    month = day = year = None
    if m:
        month, day = int(m.group(1)), int(m.group(2))
        year = int(m.group(3)) if m.group(3) else None
    else:
        m = re.fullmatch(r"([a-z]{3,9}),? (\d{1,2})(?:,? (\d{4}))?", text)
        if m and m.group(1) in _MONTHS:
            month, day = _MONTHS[m.group(1)], int(m.group(2))
            year = int(m.group(3)) if m.group(3) else None
    if month is None:
        return None
    try:
        d = date(year or today.year, month, day)
    except ValueError:
        return None
    if year is None and d < today:
        d = date(today.year + 1, month, day)
    return d


class ProjectCreateModal(discord.ui.Modal, title="New project"):
    """Popup form for $project create (modals can only open from a button)."""

    name = discord.ui.TextInput(label="Project name", max_length=90,
                                placeholder="e.g. TerraNova Game")
    about = discord.ui.TextInput(label="What is it about?", required=False,
                                 style=discord.TextStyle.paragraph, max_length=300,
                                 placeholder="Optional. Becomes the forum's topic line.")

    def __init__(self, cog, category):
        super().__init__()
        self.cog = cog
        self.category = category

    async def on_submit(self, interaction):
        await interaction.response.defer()
        msg, _ = await self.cog._create_project(
            interaction.guild, self.category, interaction.user,
            str(self.name).strip(), str(self.about).strip() or None)
        await interaction.followup.send(msg)


class TaskView(discord.ui.View):
    """Persistent Claim / Done buttons on every task card."""

    def __init__(self, cog):
        super().__init__(timeout=None)
        self.cog = cog

    @discord.ui.button(label="Claim", emoji="🙋",
                       style=discord.ButtonStyle.primary, custom_id="herupa_task_claim")
    async def claim(self, interaction, button):
        await self.cog.button_claim(interaction)

    @discord.ui.button(label="Done", emoji="✅",
                       style=discord.ButtonStyle.success, custom_id="herupa_task_done")
    async def done(self, interaction, button):
        await self.cog.button_done(interaction)


class Projects(commands.Cog):

    def __init__(self, client):
        self.client = client
        self.db = "projects"
        self.mongo = HerupaMongo()

    async def cog_load(self):
        self.client.add_view(TaskView(self))
        self.daily.start()

    async def cog_unload(self):
        self.daily.cancel()

    # ------------------------- config / data -------------------------

    def _config_col(self):
        return self.mongo.client[self.db]["config"]

    def _tasks_col(self):
        return self.mongo.client[self.db]["tasks"]

    def _conf(self, guild_id):
        return self._config_col().find_one({"guild_id": str(guild_id)})

    def _forum_conf(self, guild_id, forum_id):
        conf = self._conf(guild_id)
        if conf is None:
            return None
        return conf.get("forums", {}).get(str(forum_id))

    def _task(self, thread_id):
        return self._tasks_col().find_one({"thread_id": str(thread_id)})

    def _feature_on(self, guild_id):
        fm = self.client.get_cog("FeatureManager")
        return fm is None or fm.is_enabled(guild_id, "projects")

    def _tz(self, guild_id, conf=None):
        """The guild's timezone (config key "timezone", IANA name; UTC default)."""
        if conf is None:
            conf = self._conf(guild_id) or {}
        try:
            return ZoneInfo(conf.get("timezone") or "UTC")
        except (KeyError, ValueError):
            return UTC

    def _daily_hour(self, conf):
        """Hour (in the guild's timezone) the daily pass fires from. The
        default, 13:00 UTC, lands around 9am US Eastern."""
        try:
            return min(23, max(0, int(conf.get("daily_hour", 13))))
        except (TypeError, ValueError):
            return 13

    # ------------------------- task card -------------------------

    def _card(self, task):
        emoji, label = STATUSES.get(task.get("status", "todo"), ("📋", "To Do"))
        embed = discord.Embed(title=f"🗂️ {task['title']}", colour=PINK)
        embed.add_field(name="Status", value=f"{emoji} {label}")
        embed.add_field(name="Priority", value=task.get("priority", "normal").capitalize())
        assignee = task.get("assignee_id")
        embed.add_field(name="Assignee", value=f"<@{assignee}>" if assignee else "Unassigned")
        due = task.get("due")
        if due:
            overdue = (task.get("status") != "done"
                       and due < datetime.now(self._tz(task["guild_id"])).date().isoformat())
            embed.add_field(name="Due", value=due + (" ⚠️ overdue" if overdue else ""))
        embed.set_footer(text="Work happens right here in this thread. "
                              "$assign @member · $due <when> · $priority <level> · "
                              "$status <stage> · $done")
        return embed

    async def _refresh_card(self, thread, task):
        msg_id = task.get("embed_message_id")
        if not msg_id:
            return
        try:
            msg = await thread.fetch_message(int(msg_id))
            await msg.edit(embed=self._card(task))
        except discord.HTTPException:
            pass

    async def _apply_tags(self, thread, fc, status, priority):
        parent = thread.parent or self.client.get_channel(thread.parent_id)
        if parent is None:
            return
        wanted = {fc["tags"].get(status)}
        if priority == "urgent":
            wanted.add(fc["tags"].get("urgent"))
        tags = [t for t in parent.available_tags if t.id in wanted]
        # Keep tags the bot doesn't own (a poster's or mod's own labels) —
        # only the status/urgent set gets swapped out. Discord caps a post
        # at 5 applied tags, so the status tags win if it's tight.
        owned = set(fc["tags"].values())
        tags += [t for t in thread.applied_tags if t.id not in owned]
        try:
            await thread.edit(applied_tags=tags[:5])
        except discord.HTTPException:
            pass

    async def _update_task(self, thread, task, changes, note=None):
        task = dict(task, **changes)
        self._tasks_col().update_one({"thread_id": str(thread.id)}, {"$set": changes})
        fc = self._forum_conf(thread.guild.id, task["forum_id"])
        if fc and ("status" in changes or "priority" in changes):
            await self._apply_tags(thread, fc, task.get("status", "todo"),
                                   task.get("priority", "normal"))
        await self._refresh_card(thread, task)
        if note:
            try:
                await thread.send(note, allowed_mentions=discord.AllowedMentions(users=True))
            except discord.HTTPException:
                pass
        return task

    async def _register_thread(self, thread, creator_id, announce_creator=False):
        """Make a forum post a tracked task: doc, To Do tag, task card."""
        doc = {
            "guild_id": str(thread.guild.id), "forum_id": str(thread.parent_id),
            "thread_id": str(thread.id), "title": thread.name[:200],
            "status": "todo", "priority": "normal", "assignee_id": None,
            "due": None, "created_by": str(creator_id),
            "created_at": int(time.time()), "completed_at": None,
        }
        self._tasks_col().update_one({"thread_id": str(thread.id)},
                                     {"$setOnInsert": doc}, upsert=True)
        fc = self._forum_conf(thread.guild.id, thread.parent_id)
        if fc:
            await self._apply_tags(thread, fc, "todo", "normal")
        content = f"Task created by <@{creator_id}>." if announce_creator else None
        try:
            msg = await thread.send(content=content, embed=self._card(doc),
                                    view=TaskView(self),
                                    allowed_mentions=discord.AllowedMentions.none())
            self._tasks_col().update_one({"thread_id": str(thread.id)},
                                         {"$set": {"embed_message_id": str(msg.id)}})
        except discord.HTTPException:
            pass

    # ------------------------- daily automation -------------------------
    # One pass per guild per day, from daily_hour in the guild's timezone
    # (13:00 UTC by default, ~9am US Eastern): due-date DM reminders,
    # overdue nudges in the task threads, and the morning digest. Each piece
    # has its own $feature toggle (project-reminders / project-nudges /
    # project-digest) on top of the overall projects switch.

    @tasks.loop(minutes=30)
    async def daily(self):
        fm = self.client.get_cog("FeatureManager")

        def on(guild_id, feature):
            return fm is None or fm.is_enabled(guild_id, feature)

        for conf in self._config_col().find():
            gid = conf.get("guild_id")
            guild = self.client.get_guild(int(gid)) if gid else None
            if guild is None or not conf.get("forums"):
                continue
            if not on(guild.id, "projects"):
                continue
            now = datetime.now(self._tz(guild.id, conf))
            if now.hour < self._daily_hour(conf):
                continue
            today = now.date()
            meta = self.mongo.client[self.db]["meta"]
            state_id = f"daily:{gid}"
            state = meta.find_one({"_id": state_id}) or {}
            if state.get("last") == today.isoformat():
                continue
            # One guild blowing up must not kill the loop (tasks.loop stops
            # on an unhandled exception) or the other guilds' runs. The day
            # is only stamped done on success, so a transient failure gets
            # retried on the next half-hour tick.
            try:
                await self._run_daily(guild, conf, today, on)
            except Exception:
                traceback.print_exc()
                continue
            meta.update_one({"_id": state_id},
                            {"$set": {"last": today.isoformat()}}, upsert=True)

    @daily.before_loop
    async def _before_daily(self):
        await self.client.wait_until_ready()

    async def _run_daily(self, guild, conf, today, on):
        gid = str(guild.id)
        open_tasks = list(self._tasks_col().find({"guild_id": gid,
                                                  "status": {"$ne": "done"}}))
        if not open_tasks:
            return
        iso_today = today.isoformat()
        iso_tomorrow = (today + timedelta(days=1)).isoformat()
        due_today = [t for t in open_tasks if t.get("due") == iso_today]
        due_tomorrow = [t for t in open_tasks if t.get("due") == iso_tomorrow]
        overdue = [t for t in open_tasks if t.get("due") and t["due"] < iso_today]

        if on(guild.id, "project-reminders"):
            for label, batch in (("due **today**", due_today),
                                 ("due **tomorrow**", due_tomorrow)):
                for t in batch:
                    if not t.get("assignee_id"):
                        continue
                    member = guild.get_member(int(t["assignee_id"]))
                    if member is None or member.bot:
                        continue
                    try:
                        await member.send(
                            f"🗓️ Heads up! Your task **{t['title']}** in **{guild.name}** "
                            f"is {label}: "
                            f"https://discord.com/channels/{gid}/{t['thread_id']}")
                    except discord.HTTPException:
                        pass

        if on(guild.id, "project-nudges"):
            for t in overdue:
                thread = guild.get_thread(int(t["thread_id"]))
                if thread is None:
                    try:
                        thread = await guild.fetch_channel(int(t["thread_id"]))
                    except discord.HTTPException:
                        continue
                days = (today - date.fromisoformat(t["due"])).days
                mention = f"<@{t['assignee_id']}> " if t.get("assignee_id") else ""
                try:
                    await thread.send(
                        f"⚠️ {mention}this task is **{days} day{'s' if days != 1 else ''} "
                        f"overdue** (was due {t['due']}).",
                        allowed_mentions=discord.AllowedMentions(users=True))
                except discord.HTTPException:
                    pass

        if on(guild.id, "project-digest"):
            ch_id = conf.get("digest_channel_id")
            channel = guild.get_channel(int(ch_id)) if ch_id else None
            if channel is not None:
                counts = {}
                for t in open_tasks:
                    s = t.get("status", "todo")
                    counts[s] = counts.get(s, 0) + 1
                summary = " · ".join(f"{e} {counts.get(k, 0)}"
                                     for k, (e, _) in STATUSES.items() if k != "done")
                lines = [f"Open tasks: **{len(open_tasks)}**  ({summary})"]

                def fmt(ts):
                    out = ", ".join(f"<#{t['thread_id']}>" for t in ts[:8])
                    return out + (f" and {len(ts) - 8} more" if len(ts) > 8 else "")

                if due_today:
                    lines.append(f"🗓️ Due today: {fmt(due_today)}")
                if due_tomorrow:
                    lines.append(f"⏭️ Due tomorrow: {fmt(due_tomorrow)}")
                if overdue:
                    lines.append(f"⚠️ Overdue: {fmt(overdue)}")
                embed = discord.Embed(title="🗂️ Morning project digest",
                                      description="\n".join(lines), colour=PINK)
                try:
                    await channel.send(embed=embed)
                except discord.HTTPException:
                    pass

    # ------------------------- forum listener -------------------------

    @commands.Cog.listener()
    async def on_thread_create(self, thread):
        # A member made a post in a project forum the native way -> track it.
        # ($task-created posts are owned by Herupa and handled in the command.)
        if thread.owner_id == self.client.user.id:
            return
        if self._forum_conf(thread.guild.id, thread.parent_id) is None:
            return
        if not self._feature_on(thread.guild.id):
            return
        if self._task(thread.id):
            return
        await self._register_thread(thread, thread.owner_id)

    # These three run even when the $feature is off: they keep Mongo in step
    # with what happens in Discord, and stale records would otherwise haunt
    # $board, $mytasks, the digest, and the nudge pass forever.

    @commands.Cog.listener()
    async def on_raw_thread_delete(self, payload):
        # A task post deleted by hand takes its task record with it.
        self._tasks_col().delete_one({"thread_id": str(payload.thread_id)})

    @commands.Cog.listener()
    async def on_guild_channel_delete(self, channel):
        # Same for a whole project forum deleted outside $project delete.
        conf = self._conf(channel.guild.id)
        if conf is None or str(channel.id) not in conf.get("forums", {}):
            return
        self._config_col().update_one({"guild_id": str(channel.guild.id)},
                                      {"$unset": {f"forums.{channel.id}": ""}})
        self._tasks_col().delete_many({"guild_id": str(channel.guild.id),
                                       "forum_id": str(channel.id)})

    @commands.Cog.listener()
    async def on_thread_update(self, before, after):
        # Renaming a task post renames the task (card, DMs, web board).
        if before.name == after.name:
            return
        task = self._task(after.id)
        if task is None:
            return
        title = after.name[:200]
        self._tasks_col().update_one({"thread_id": str(after.id)},
                                     {"$set": {"title": title}})
        await self._refresh_card(after, dict(task, title=title))

    # ------------------------- thread context helper -------------------------

    async def _here(self, ctx):
        """(thread, task) when invoked inside a task thread, else (None, None)
        with the excuse already sent."""
        ch = ctx.channel
        if isinstance(ch, discord.Thread) and self._forum_conf(ctx.guild.id, ch.parent_id):
            task = self._task(ch.id)
            if task:
                return ch, task
        await ctx.send("Run this inside a task's thread (a post in a project forum).")
        return None, None

    # ------------------------- commands -------------------------

    @commands.command(name="project")
    @commands.guild_only()
    async def project(self, ctx, action: str = None, *, name: str = None):
        """$project create <name> / $project delete <name> (managers only)."""
        if action not in ("create", "delete", "digest"):
            await ctx.send("Usage: `$project create`, `$project delete`, or "
                           "`$project digest` (run in the channel that should get "
                           "the morning digest; `$project digest off` stops it).")
            return
        fm = self.client.get_cog("FeatureManager")
        if fm is None or not fm.is_manager(ctx.author):
            await ctx.send("Only the owner, admins, or bot managers can manage projects.")
            return
        if action == "delete":
            await self._project_delete(ctx, name)
            return
        if action == "digest":
            if name and name.strip().lower() == "off":
                self._config_col().update_one({"guild_id": str(ctx.guild.id)},
                                              {"$unset": {"digest_channel_id": ""}})
                await ctx.send("🗂️ Morning digest turned off. "
                               "Run `$project digest` in a channel to start it again.")
            else:
                self._config_col().update_one(
                    {"guild_id": str(ctx.guild.id)},
                    {"$set": {"digest_channel_id": str(ctx.channel.id)}}, upsert=True)
                conf = self._conf(ctx.guild.id) or {}
                tz = self._tz(ctx.guild.id, conf)
                await ctx.send(f"🗂️ Morning project digest will land in {ctx.channel.mention} "
                               f"each day from {self._daily_hour(conf)}:00 {tz.key} time "
                               "(when there are open tasks).")
            return
        if name:
            # Fast path: name given inline.
            msg, _ = await self._create_project(ctx.guild, ctx.channel.category,
                                                ctx.author, name.strip())
            await ctx.send(msg)
            return
        # Bare $project create: a button that opens the popup form (Discord
        # only lets a modal open from an interaction, not from a message).
        view = discord.ui.View(timeout=60)
        button = discord.ui.Button(label="New project", emoji="🗂️",
                                   style=discord.ButtonStyle.primary)

        async def open_modal(interaction):
            if interaction.user.id != ctx.author.id:
                await interaction.response.send_message(
                    "Only the person who asked can use this.", ephemeral=True)
                return
            await interaction.response.send_modal(
                ProjectCreateModal(self, ctx.channel.category))

        button.callback = open_modal
        view.add_item(button)
        await ctx.send("Let's set one up:", view=view)

    async def _create_project(self, guild, category, author, name, about=None):
        """Create the project forum + config. Returns (reply text, forum|None)."""
        if "COMMUNITY" not in guild.features:
            return ("This server needs Community enabled for forum channels "
                    "(Server Settings, Enable Community).", None)
        topic = about or f"Project board: {name}. New posts become tracked tasks."
        conf = self._conf(guild.id) or {}
        kwargs = {}
        wanted = conf.get("default_reaction")
        if wanted:
            # A guild emoji name (e.g. "terranova") or a plain unicode emoji.
            kwargs["default_reaction_emoji"] = \
                discord.utils.get(guild.emojis, name=wanted) or wanted
        role_names = conf.get("forum_roles")
        if role_names:
            # Staff-only board: hide from @everyone, open to the listed roles.
            overwrites = {
                guild.default_role: discord.PermissionOverwrite(view_channel=False),
                guild.me: discord.PermissionOverwrite(
                    view_channel=True, send_messages=True, send_messages_in_threads=True,
                    manage_channels=True, manage_threads=True, read_message_history=True),
            }
            for rname in role_names:
                low = rname.lower()
                role = next((r for r in guild.roles if r.name.lower() == low), None)
                if role:
                    overwrites[role] = discord.PermissionOverwrite(
                        view_channel=True, send_messages=True,
                        send_messages_in_threads=True, read_message_history=True)
            kwargs["overwrites"] = overwrites
        try:
            forum = await guild.create_forum(
                name=name, category=category, topic=topic,
                available_tags=[discord.ForumTag(name=n) for n in TAG_NAMES.values()],
                reason=f"Project created by {author}", **kwargs)
        except discord.Forbidden:
            return ("I couldn't create the forum (missing permissions).", None)
        except discord.HTTPException:
            # e.g. a bad default_reaction config value: retry without it (but
            # keep the permission overwrites) rather than failing the project.
            kwargs.pop("default_reaction_emoji", None)
            forum = await guild.create_forum(
                name=name, category=category, topic=topic,
                available_tags=[discord.ForumTag(name=n) for n in TAG_NAMES.values()],
                reason=f"Project created by {author}", **kwargs)
        tag_ids = {}
        for key, tag_name in TAG_NAMES.items():
            tag = next((t for t in forum.available_tags if t.name == tag_name), None)
            if tag:
                tag_ids[key] = tag.id
        self._config_col().update_one(
            {"guild_id": str(guild.id)},
            {"$set": {f"forums.{forum.id}": {"name": name, "tags": tag_ids}}},
            upsert=True)
        return (f"🗂️ Project **{name}** is live: {forum.mention}. "
                "Make a post there (or use `$task <title>`) and I'll track it as a task.",
                forum)

    def _open_count(self, guild_id, forum_id):
        return self._tasks_col().count_documents(
            {"guild_id": str(guild_id), "forum_id": forum_id,
             "status": {"$ne": "done"}})

    async def _project_delete(self, ctx, name):
        conf = self._conf(ctx.guild.id) or {}
        forums = conf.get("forums", {})
        if not forums:
            await ctx.send("There are no projects here to delete.")
            return
        ordered = sorted(forums.items(), key=lambda kv: kv[1]["name"].casefold())

        # A name or list number skips the picker.
        if name:
            q = name.strip()
            if q.isdigit() and 1 <= int(q) <= len(ordered):
                forum_id = ordered[int(q) - 1][0]
            else:
                forum_id = next((fid for fid, fc in ordered
                                 if fc["name"].casefold() == q.casefold()), None)
            if forum_id is None:
                names = ", ".join(fc["name"] for _, fc in ordered)
                await ctx.send(f"I don't know a project called **{q}**. Projects here: {names}.")
                return
            await self._confirm_delete(ctx, forum_id)
            return

        # Bare $project delete: numbered list + a dropdown to pick from.
        lines, options = [], []
        for position, (fid, fc) in enumerate(ordered, start=1):
            open_count = self._open_count(ctx.guild.id, fid)
            lines.append(f"{position}. **{fc['name']}** ({open_count} open)")
            options.append(discord.SelectOption(
                label=f"{position}. {fc['name']}"[:100], value=fid,
                description=f"{open_count} open task(s)"))
        view = discord.ui.View(timeout=60)
        select = discord.ui.Select(placeholder="Pick the project to delete...",
                                   options=options[:25])

        async def chosen(interaction):
            if interaction.user.id != ctx.author.id:
                await interaction.response.send_message(
                    "Only the person who asked can pick.", ephemeral=True)
                return
            await interaction.response.defer()
            view.stop()
            try:
                await interaction.message.delete()
            except discord.HTTPException:
                pass
            await self._confirm_delete(ctx, select.values[0])

        select.callback = chosen
        view.add_item(select)
        embed = discord.Embed(title="🗑️ Delete which project?",
                              description="\n".join(lines), colour=PINK)
        await ctx.send(embed=embed, view=view)

    async def _confirm_delete(self, ctx, forum_id):
        conf = self._conf(ctx.guild.id) or {}
        fc = conf.get("forums", {}).get(forum_id)
        if fc is None:
            await ctx.send("That project is already gone.")
            return
        open_count = self._open_count(ctx.guild.id, forum_id)

        # Deleting the forum takes every task thread and its discussion with
        # it, so make the invoker confirm on a button first.
        view = discord.ui.View(timeout=60)
        button = discord.ui.Button(label=f"Delete {fc['name']} forever",
                                   emoji="🗑️", style=discord.ButtonStyle.danger)

        async def confirm(interaction):
            if interaction.user.id != ctx.author.id:
                await interaction.response.send_message(
                    "Only the person who asked can confirm this.", ephemeral=True)
                return
            await interaction.response.defer()
            view.stop()
            forum = ctx.guild.get_channel(int(forum_id))
            if forum is not None:
                try:
                    await forum.delete(reason=f"Project deleted by {ctx.author}")
                except discord.HTTPException:
                    await interaction.followup.send(
                        "I couldn't delete the forum channel, so I left everything in place.")
                    return
            self._config_col().update_one({"guild_id": str(ctx.guild.id)},
                                          {"$unset": {f"forums.{forum_id}": ""}})
            self._tasks_col().delete_many({"guild_id": str(ctx.guild.id),
                                           "forum_id": forum_id})
            try:
                await interaction.followup.send(
                    f"🗑️ Project **{fc['name']}** is gone, along with its task records.")
            except discord.HTTPException:
                pass

        button.callback = confirm
        view.add_item(button)
        await ctx.send(
            f"⚠️ This deletes the **{fc['name']}** forum, every task thread in it "
            f"({open_count} still open), and its task records. There is no undo. "
            "Sure?", view=view)

    @commands.command(name="task")
    @commands.guild_only()
    async def task(self, ctx, *, title: str = None):
        """$task <title> (or $task <project> | <title> when there are several)."""
        if not title or not title.strip():
            await ctx.send("Usage: `$task <title>` or `$task <project> | <title>`.")
            return
        conf = self._conf(ctx.guild.id) or {}
        forums = conf.get("forums", {})
        if not forums:
            await ctx.send("No projects here yet. An admin can make one with `$project create <name>`.")
            return
        forum_id = None
        if " | " in title:
            proj, title = (p.strip() for p in title.split(" | ", 1))
            forum_id = next((fid for fid, fc in forums.items()
                             if fc["name"].casefold() == proj.casefold()), None)
            if forum_id is None:
                names = ", ".join(fc["name"] for fc in forums.values())
                await ctx.send(f"I don't know a project called **{proj}**. Projects here: {names}.")
                return
        elif len(forums) == 1:
            forum_id = next(iter(forums))
        elif isinstance(ctx.channel, discord.Thread) and str(ctx.channel.parent_id) in forums:
            forum_id = str(ctx.channel.parent_id)
        else:
            names = ", ".join(fc["name"] for fc in forums.values())
            await ctx.send(f"Which project? Use `$task <project> | <title>`. Projects here: {names}.")
            return
        forum = ctx.guild.get_channel(int(forum_id))
        if forum is None:
            await ctx.send("That project's forum seems to be gone.")
            return
        try:
            created = await forum.create_thread(
                name=title[:100], content=f"Task created by {ctx.author.mention}.",
                allowed_mentions=discord.AllowedMentions.none())
        except discord.HTTPException as e:
            await ctx.send(f"I couldn't create the task: {e}")
            return
        await self._register_thread(created.thread, ctx.author.id)
        await ctx.send(f"🗂️ Task opened: {created.thread.mention}")

    @commands.command(name="assign")
    @commands.guild_only()
    async def assign(self, ctx, member: discord.Member = None):
        thread, task = await self._here(ctx)
        if task is None:
            return
        member = member or ctx.author
        changes = {"assignee_id": str(member.id)}
        if task.get("status") == "todo":
            changes["status"] = "doing"
        await self._update_task(thread, task, changes,
                                note=f"🙋 Assigned to {member.mention}.")

    @commands.command(name="due")
    @commands.guild_only()
    async def due(self, ctx, *, when: str = None):
        thread, task = await self._here(ctx)
        if task is None:
            return
        if not when:
            await ctx.send("Usage: `$due <when>`, e.g. `$due friday`, `$due 8/15`, `$due none`.")
            return
        parsed = parse_due(when, self._tz(ctx.guild.id))
        if parsed is None:
            await ctx.send("I couldn't read that date. Try `friday`, `tomorrow`, `8/15`, or `in 3 days`.")
            return
        if parsed == "clear":
            await self._update_task(thread, task, {"due": None}, note="🗓️ Due date cleared.")
            return
        await self._update_task(thread, task, {"due": parsed.isoformat()},
                                note=f"🗓️ Due **{parsed.strftime('%A, %B %d')}**.")

    @commands.command(name="priority")
    @commands.guild_only()
    async def priority(self, ctx, level: str = None):
        thread, task = await self._here(ctx)
        if task is None:
            return
        level = (level or "").lower()
        if level not in PRIORITIES:
            await ctx.send("Usage: `$priority low / normal / high / urgent`.")
            return
        await self._update_task(thread, task, {"priority": level},
                                note=("🔥 Marked **urgent**." if level == "urgent"
                                      else f"Priority set to **{level}**."))

    @commands.command(name="status")
    @commands.guild_only()
    async def status(self, ctx, stage: str = None):
        thread, task = await self._here(ctx)
        if task is None:
            return
        stage = (stage or "").lower()
        if stage not in STATUSES:
            await ctx.send("Usage: `$status todo / doing / review / done`.")
            return
        if stage == "done":
            await self._finish(thread, task, ctx.author)
            return
        emoji, label = STATUSES[stage]
        await self._update_task(thread, task, {"status": stage, "completed_at": None},
                                note=f"{emoji} Status: **{label}**.")

    @commands.command(name="done")
    @commands.guild_only()
    async def done(self, ctx):
        thread, task = await self._here(ctx)
        if task is None:
            return
        await self._finish(thread, task, ctx.author)

    async def _finish(self, thread, task, closer):
        task = await self._update_task(
            thread, task,
            {"status": "done", "completed_at": int(time.time())},
            note=f"✅ Done! Closed out by {closer.mention}. Nice work. 🌸")
        try:
            await thread.edit(archived=True)
        except discord.HTTPException:
            pass

    # ------------------------- buttons -------------------------

    async def _button_task(self, interaction):
        if not self._feature_on(interaction.guild_id):
            await interaction.response.send_message(
                "The projects feature is turned off in this server.", ephemeral=True)
            return None, None
        task = self._task(interaction.channel.id)
        if task is None:
            await interaction.response.send_message(
                "This thread isn't a tracked task anymore.", ephemeral=True)
            return None, None
        return interaction.channel, task

    async def button_claim(self, interaction):
        thread, task = await self._button_task(interaction)
        if task is None:
            return
        await interaction.response.defer()
        changes = {"assignee_id": str(interaction.user.id)}
        if task.get("status") == "todo":
            changes["status"] = "doing"
        await self._update_task(thread, task, changes,
                                note=f"🙋 {interaction.user.mention} claimed this task.")

    async def button_done(self, interaction):
        thread, task = await self._button_task(interaction)
        if task is None:
            return
        await interaction.response.defer()
        await self._finish(thread, task, interaction.user)

    # ------------------------- overviews -------------------------

    @commands.command(name="mytasks")
    @commands.guild_only()
    async def mytasks(self, ctx):
        docs = list(self._tasks_col().find({"guild_id": str(ctx.guild.id),
                                            "assignee_id": str(ctx.author.id),
                                            "status": {"$ne": "done"}}))
        if not docs:
            await ctx.send("You have no open tasks here. Enjoy it while it lasts. 🌸")
            return
        docs.sort(key=lambda d: (d.get("due") or "9999-99-99", -d.get("created_at", 0)))
        today = datetime.now(self._tz(ctx.guild.id)).date().isoformat()
        lines = []
        for d in docs[:15]:
            emoji, _ = STATUSES.get(d.get("status", "todo"), ("📋", ""))
            line = f"{emoji} <#{d['thread_id']}>"
            if d.get("due"):
                line += f" · due {d['due']}" + (" ⚠️" if d["due"] < today else "")
            if d.get("priority") == "urgent":
                line += " · 🔥"
            lines.append(line)
        embed = discord.Embed(title=f"🗂️ Your open tasks ({len(docs)})",
                              description="\n".join(lines), colour=PINK)
        await ctx.send(embed=embed)

    @commands.command(name="board")
    @commands.guild_only()
    async def board(self, ctx):
        conf = self._conf(ctx.guild.id) or {}
        forums = conf.get("forums", {})
        if not forums:
            await ctx.send("No projects here yet. An admin can make one with `$project create <name>`.")
            return
        today = datetime.now(self._tz(ctx.guild.id)).date().isoformat()
        embed = discord.Embed(title="🗂️ Project board", colour=PINK)
        for fid, fc in forums.items():
            docs = list(self._tasks_col().find({"guild_id": str(ctx.guild.id),
                                                "forum_id": fid}))
            counts = {k: 0 for k in STATUSES}
            overdue = 0
            for d in docs:
                counts[d.get("status", "todo")] = counts.get(d.get("status", "todo"), 0) + 1
                if d.get("due") and d.get("status") != "done" and d["due"] < today:
                    overdue += 1
            line = " · ".join(f"{e} {counts[k]}" for k, (e, _) in STATUSES.items())
            if overdue:
                line += f"\n⚠️ {overdue} overdue"
            embed.add_field(name=f"{fc['name']}  (<#{fid}>)", value=line, inline=False)
        await ctx.send(embed=embed)


async def setup(client):
    await client.add_cog(Projects(client))
