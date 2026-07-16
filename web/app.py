"""Herupa's web control room.

Runs beside the bot on the Pi as its own systemd service (herupa-web). Shares
the bot's Mongo and talks to Discord over REST with the bot token, so a UI
crash can never take Herupa down. Auth is a single admin password from
/etc/environment (HERUPA_WEB_PASSWORD) with signed-random session cookies.
"""

import calendar
import json
import os
import secrets
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pymongo import MongoClient

# ------------------------- config -------------------------

GUILD_ID = "645847490020638720"           # Chill Club
LOG_GUILD_ID = "1249872743520931870"      # dedicated logging server
TICKET_LOG_CHANNEL = "1525359402670886932"
LAW_CHAT_ID = "803751026355863553"
HERUPA_ID = "643562852741021707"
BRAND = 0xFFB7C5
EASTERN = ZoneInfo("America/New_York")

TOKEN = os.environ["DISCORD_TOKEN"]
PASSWORD = os.environ["HERUPA_WEB_PASSWORD"]

DANGEROUS_PERMS = (0x8 | 0x2 | 0x4 | 0x10 | 0x20 | 0x10000000 | 0x20000000
                   | 0x2000 | 0x10000000000)  # admin/kick/ban/manage guild,channels,roles,webhooks,messages,moderate

mongo = MongoClient(f"mongodb://{os.environ.get('MONGO_USERNAME', 'admin')}:"
                    f"{os.environ.get('MONGO_PASSWORD', 'admin')}@"
                    f"{os.environ.get('MONGO_HOST', 'localhost:27017')}/")

app = FastAPI()
BASE = os.path.dirname(os.path.abspath(__file__))
app.mount("/static", StaticFiles(directory=os.path.join(BASE, "static")), name="static")
templates = Jinja2Templates(directory=os.path.join(BASE, "templates"))

# ------------------------- auth -------------------------

SESSIONS = {}          # token -> expiry epoch
LOGIN_FAILS = {}       # ip -> [fail epochs]
SESSION_TTL = 7 * 86400


def _session_ok(request):
    tok = request.cookies.get("hs")
    return bool(tok) and SESSIONS.get(tok, 0) > time.time()


def guard(request):
    """Redirect to login unless the session cookie is valid."""
    if _session_ok(request):
        return None
    return RedirectResponse("/login", status_code=303)


@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request, err: str = ""):
    return templates.TemplateResponse(request, "login.html", {"err": err})


@app.post("/login")
def login(request: Request, password: str = Form("")):
    ip = request.client.host if request.client else "?"
    fails = [t for t in LOGIN_FAILS.get(ip, []) if t > time.time() - 600]
    if len(fails) >= 10:
        return RedirectResponse("/login?err=Too+many+attempts.+Wait+ten+minutes.", status_code=303)
    if not secrets.compare_digest(password, PASSWORD):
        fails.append(time.time())
        LOGIN_FAILS[ip] = fails
        return RedirectResponse("/login?err=That+password+is+not+right.", status_code=303)
    tok = secrets.token_urlsafe(32)
    SESSIONS[tok] = time.time() + SESSION_TTL
    resp = RedirectResponse("/", status_code=303)
    resp.set_cookie("hs", tok, max_age=SESSION_TTL, httponly=True, samesite="lax")
    return resp


@app.get("/logout")
def logout(request: Request):
    SESSIONS.pop(request.cookies.get("hs", ""), None)
    resp = RedirectResponse("/login", status_code=303)
    resp.delete_cookie("hs")
    return resp


# ------------------------- discord REST -------------------------

def api(method, path, body=None):
    req = urllib.request.Request(
        "https://discord.com/api/v10" + path,
        data=json.dumps(body).encode() if body is not None else None,
        method=method,
        headers={"Authorization": "Bot " + TOKEN,
                 "Content-Type": "application/json",
                 "User-Agent": "HerupaWebUI/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            data = r.read()
            return json.loads(data) if data else None
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"Discord API {e.code}: {e.read().decode(errors='replace')[:300]}")


_CACHE = {}

def cached(key, ttl, fn):
    hit = _CACHE.get(key)
    if hit and hit[0] > time.time():
        return hit[1]
    val = fn()
    _CACHE[key] = (time.time() + ttl, val)
    return val


def guild_channels():
    return cached("channels", 60, lambda: api("GET", f"/guilds/{GUILD_ID}/channels"))


def text_channels():
    out = [dict(c, label="#" + c["name"]) for c in guild_channels() if c["type"] in (0, 5)]
    return sorted(out, key=lambda c: c["position"])


def messageable_channels():
    """Text channels plus voice and stage chats (they take messages too)."""
    voice = [dict(c, label="🔊 " + c["name"])
             for c in guild_channels() if c["type"] in (2, 13)]
    return text_channels() + sorted(voice, key=lambda c: c["position"])


def guild_roles():
    return cached("roles", 60, lambda: api("GET", f"/guilds/{GUILD_ID}/roles"))


def herupa_top_position():
    member = cached("me_member", 300,
                    lambda: api("GET", f"/guilds/{GUILD_ID}/members/{HERUPA_ID}"))
    positions = [r["position"] for r in guild_roles() if r["id"] in member["roles"]]
    return max(positions) if positions else 0


def assignable_roles():
    """Roles a self-assign panel may offer: nothing managed, dangerous, or
    at/above Herupa's own top role."""
    top = herupa_top_position()
    out = []
    for r in guild_roles():
        if r["id"] == GUILD_ID or r.get("managed"):
            continue
        if int(r["permissions"]) & DANGEROUS_PERMS:
            continue
        if r["position"] >= top:
            continue
        out.append(r)
    return sorted(out, key=lambda r: -r["position"])


def all_members():
    """Every guild member (paginated REST list), cached five minutes."""
    def fetch():
        out, after = {}, "0"
        while True:
            batch = api("GET", f"/guilds/{GUILD_ID}/members?limit=1000&after={after}")
            if not batch:
                return out
            for m in batch:
                u = m["user"]
                out[u["id"]] = {
                    "name": m.get("nick") or u.get("global_name") or u["username"],
                    "bot": u.get("bot", False),
                    "avatar": (f"https://cdn.discordapp.com/avatars/{u['id']}/{u['avatar']}.png?size=32"
                               if u.get("avatar") else
                               "https://cdn.discordapp.com/embed/avatars/0.png"),
                }
            if len(batch) < 1000:
                return out
            after = batch[-1]["user"]["id"]
    return cached("all_members", 300, fetch)


_NAMES = {}

def display_name(user_id):
    """Best-effort member name, cached ten minutes."""
    user_id = str(user_id)
    hit = _NAMES.get(user_id)
    if hit and hit[0] > time.time():
        return hit[1]
    try:
        m = api("GET", f"/guilds/{GUILD_ID}/members/{user_id}")
        name = m.get("nick") or m["user"].get("global_name") or m["user"]["username"]
    except RuntimeError:
        name = f"user {user_id}"
    _NAMES[user_id] = (time.time() + 600, name)
    return name


# ------------------------- leveling math -------------------------

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


# ------------------------- schedule helpers -------------------------

from datetime import date


def _nth_weekday(year, month, weekday, n):
    first = date(year, month, 1).weekday()
    return date(year, month, 1 + ((weekday - first) % 7) + (n - 1) * 7)


def _last_weekday(year, month, weekday):
    last = date(year, month, calendar.monthrange(year, month)[1])
    return last - timedelta(days=(last.weekday() - weekday) % 7)


def _easter(y):
    a, b, c = y % 19, y // 100, y % 100
    d, e, f = b // 4, b % 4, (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = c // 4, c % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    return date(y, (h + l - 7 * m + 114) // 31, ((h + l - 7 * m + 114) % 31) + 1)


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


def repeat_label(repeat):
    if repeat.startswith("holiday:"):
        rule = HOLIDAY_RULES.get(repeat.split(":", 1)[1])
        return f"every {rule[0]}" if rule else repeat
    return repeat


def parse_wall(wall):
    return datetime.strptime(wall, "%Y-%m-%dT%H:%M").replace(tzinfo=EASTERN)


def advance_wall(dt, repeat):
    if repeat == "daily":
        return dt + timedelta(days=1)
    if repeat == "weekly":
        return dt + timedelta(days=7)
    if repeat == "monthly":
        year, month = (dt.year, dt.month + 1) if dt.month < 12 else (dt.year + 1, 1)
        return dt.replace(year=year, month=month,
                          day=min(dt.day, calendar.monthrange(year, month)[1]))
    if repeat == "yearly":
        year = dt.year + 1
        return dt.replace(year=year,
                          day=min(dt.day, calendar.monthrange(year, dt.month)[1]))
    return None


def next_fire_utc(wall, repeat, after=None):
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


def fmt_eastern(dt_utc):
    """Naive-UTC datetime from Mongo -> friendly Eastern string."""
    if dt_utc is None:
        return ""
    return (dt_utc.replace(tzinfo=timezone.utc).astimezone(EASTERN)
            .strftime("%b %d %Y, %I:%M %p"))


def audit(action, detail):
    mongo["webui"]["audit"].insert_one(
        {"ts": datetime.utcnow(), "action": action, "detail": detail})


def page(request, name, **ctx):
    ctx.setdefault("ok", request.query_params.get("ok", ""))
    ctx.setdefault("err", request.query_params.get("err", ""))
    ctx["active"] = name.split(".")[0]
    return templates.TemplateResponse(request, name, ctx)


def back(path, ok=None, err=None):
    q = ("?ok=" + urllib.parse.quote(ok)) if ok else ("?err=" + urllib.parse.quote(err)) if err else ""
    return RedirectResponse(path + q, status_code=303)


# ------------------------- dashboard -------------------------

@app.get("/", response_class=HTMLResponse)
def dashboard(request: Request):
    if (r := guard(request)):
        return r
    checks = {}
    try:
        out = subprocess.run(["systemctl", "is-active", "herupa-bot.service"],
                             capture_output=True, text=True, timeout=5)
        checks["bot"] = out.stdout.strip() == "active"
    except Exception:
        checks["bot"] = False
    try:
        mongo.admin.command("ping")
        checks["mongo"] = True
    except Exception:
        checks["mongo"] = False
    t0 = time.time()
    try:
        api("GET", "/users/@me")
        checks["discord"] = True
        checks["discord_ms"] = int((time.time() - t0) * 1000)
    except Exception:
        checks["discord"] = False
        checks["discord_ms"] = 0

    try:
        g = cached("guild", 120, lambda: api("GET", f"/guilds/{GUILD_ID}?with_counts=true"))
        members = g.get("approximate_member_count", 0)
        online = g.get("approximate_presence_count", 0)
        gname = g.get("name", "")
        icon = (f"https://cdn.discordapp.com/icons/{GUILD_ID}/{g['icon']}.png?size=64"
                if g.get("icon") else "")
    except Exception:
        members = online = 0
        gname, icon = "", ""

    open_tickets = mongo["tickets"]["tickets"].count_documents({"status": "open"})
    debts = mongo["mockdebt"]["pending"].count_documents({})
    upcoming = list(mongo["webui"]["scheduled"].find({"enabled": True})
                    .sort("next_fire", 1).limit(5))
    for s in upcoming:
        s["when"] = fmt_eastern(s.get("next_fire"))
        s["repeat"] = repeat_label(s.get("repeat", "none"))
    recent = list(mongo["webui"]["audit"].find().sort("ts", -1).limit(6))
    for a in recent:
        a["when"] = fmt_eastern(a.get("ts"))

    return page(request, "dashboard.html", checks=checks, members=members,
                online=online, gname=gname, icon=icon, open_tickets=open_tickets,
                debts=debts, upcoming=upcoming, recent=recent)


# ------------------------- scheduler -------------------------

@app.get("/schedule", response_class=HTMLResponse)
def schedule(request: Request):
    if (r := guard(request)):
        return r
    docs = list(mongo["webui"]["scheduled"].find().sort([("enabled", -1), ("next_fire", 1)]))
    chan_labels = {c["id"]: c["label"] for c in messageable_channels()}
    for d in docs:
        d["id"] = str(d["_id"])
        d["when"] = fmt_eastern(d.get("next_fire"))
        d["last"] = fmt_eastern(d.get("last_fired"))
        d["channel"] = chan_labels.get(str(d.get("channel_id")), str(d.get("channel_id")))
        d["repeat_label"] = repeat_label(d.get("repeat", "none"))
    events = [{"id": d["id"], "name": d["name"], "wall": d["wall"],
               "repeat": d.get("repeat", "none"), "enabled": d["enabled"],
               "channel": d["channel"], "content": (d.get("content") or "")[:200],
               "when": d["when"], "last": d["last"]} for d in docs]
    events_json = json.dumps(events).replace("<", "\\u003c")
    return page(request, "schedule.html", docs=docs, channels=messageable_channels(),
                events_json=events_json)


@app.post("/schedule/create")
def schedule_create(request: Request, name: str = Form(...), channel_id: str = Form(...),
                    wall: str = Form(...), repeat: str = Form("none"),
                    content: str = Form(""), use_embed: str = Form(""),
                    embed_title: str = Form(""), embed_description: str = Form(""),
                    embed_color: str = Form("#FFB7C5")):
    if (r := guard(request)):
        return r
    if not content.strip() and not (use_embed and (embed_title or embed_description)):
        return back("/schedule", err="Give the message some content.")
    nxt = next_fire_utc(wall, repeat)
    if nxt is None:
        return back("/schedule", err="That time is already in the past. Pick a future time or add a repeat.")
    embed = None
    if use_embed:
        embed = {"title": embed_title.strip(), "description": embed_description.strip(),
                 "color": int(embed_color.lstrip("#") or "FFB7C5", 16)}
    mongo["webui"]["scheduled"].insert_one({
        "name": name.strip() or "Untitled", "channel_id": int(channel_id),
        "content": content.strip(), "embed": embed, "wall": wall,
        "repeat": repeat, "next_fire": nxt, "enabled": True, "last_fired": None})
    audit("schedule.create", f"{name.strip()} -> #{channel_id} ({repeat})")
    return back("/schedule", ok=f"Scheduled. First send {fmt_eastern(nxt)} Eastern.")


@app.post("/schedule/toggle")
def schedule_toggle(request: Request, doc_id: str = Form(...)):
    if (r := guard(request)):
        return r
    from bson import ObjectId
    doc = mongo["webui"]["scheduled"].find_one({"_id": ObjectId(doc_id)})
    if not doc:
        return back("/schedule", err="That schedule is gone.")
    enable = not doc["enabled"]
    update = {"enabled": enable}
    if enable:
        nxt = next_fire_utc(doc["wall"], doc.get("repeat", "none"))
        if nxt is None:
            return back("/schedule", err="Its time is in the past. Delete it and make a new one.")
        update["next_fire"] = nxt
    mongo["webui"]["scheduled"].update_one({"_id": doc["_id"]}, {"$set": update})
    return back("/schedule", ok=("Enabled." if enable else "Paused."))


@app.post("/schedule/delete")
def schedule_delete(request: Request, doc_id: str = Form(...)):
    if (r := guard(request)):
        return r
    from bson import ObjectId
    mongo["webui"]["scheduled"].delete_one({"_id": ObjectId(doc_id)})
    return back("/schedule", ok="Deleted.")


# ------------------------- composer -------------------------

@app.get("/composer", response_class=HTMLResponse)
def composer(request: Request):
    if (r := guard(request)):
        return r
    return page(request, "composer.html", channels=messageable_channels())


@app.post("/composer/send")
def composer_send(request: Request, channel_id: str = Form(...), content: str = Form(""),
                  use_embed: str = Form(""), embed_title: str = Form(""),
                  embed_description: str = Form(""), embed_color: str = Form("#FFB7C5"),
                  embed_footer: str = Form("")):
    if (r := guard(request)):
        return r
    body = {}
    if content.strip():
        body["content"] = content.strip()
    if use_embed and (embed_title.strip() or embed_description.strip()):
        embed = {"color": int(embed_color.lstrip("#") or "FFB7C5", 16)}
        if embed_title.strip():
            embed["title"] = embed_title.strip()
        if embed_description.strip():
            embed["description"] = embed_description.strip()
        if embed_footer.strip():
            embed["footer"] = {"text": embed_footer.strip()}
        body["embeds"] = [embed]
    if not body:
        return back("/composer", err="Write something first.")
    try:
        api("POST", f"/channels/{channel_id}/messages", body)
    except RuntimeError as e:
        return back("/composer", err=str(e))
    label = next((c["label"] for c in messageable_channels() if c["id"] == channel_id),
                 channel_id)
    audit("composer.send", f"-> {label}")
    return back("/composer", ok=f"Sent to {label}.")


# ------------------------- levels -------------------------

@app.get("/levels", response_class=HTMLResponse)
def levels(request: Request, q: str = ""):
    if (r := guard(request)):
        return r
    results = []
    if q.strip():
        try:
            found = api("GET", f"/guilds/{GUILD_ID}/members/search?"
                        + urllib.parse.urlencode({"query": q.strip(), "limit": 8}))
        except RuntimeError:
            found = []
        for m in found:
            uid = m["user"]["id"]
            doc = mongo["leveling"]["members"].find_one({"_id": uid}) or {}
            xp = int(doc.get("xp", 0))
            lvl = level_for_xp(xp)
            floor, ceil = total_xp_for_level(lvl), total_xp_for_level(lvl + 1)
            daily = mongo["leveling"]["daily"].find_one({"_id": uid}) or {}
            avatar = (f"https://cdn.discordapp.com/avatars/{uid}/{m['user']['avatar']}.png?size=64"
                      if m["user"].get("avatar") else
                      "https://cdn.discordapp.com/embed/avatars/0.png")
            results.append({
                "id": uid, "bot": m["user"].get("bot", False),
                "name": m.get("nick") or m["user"].get("global_name") or m["user"]["username"],
                "username": m["user"]["username"], "avatar": avatar,
                "xp": xp, "level": lvl,
                "pct": int(100 * (xp - floor) / (ceil - floor)) if ceil > floor else 0,
                "to_next": ceil - xp,
                "streak": daily.get("streak", 0), "last_daily": daily.get("last", "never"),
            })
    # full roster, leaderboard-ordered
    members = all_members()
    streaks = {d["_id"]: d.get("streak", 0)
               for d in mongo["leveling"]["daily"].find({}, {"streak": 1})}
    roster = []
    for doc in mongo["leveling"]["members"].find({}, {"xp": 1}):
        uid = doc["_id"]
        xp = int(doc.get("xp", 0))
        info = members.get(uid)
        if info and info["bot"]:
            continue
        roster.append({
            "id": uid, "xp": xp, "level": level_for_xp(xp),
            "streak": streaks.get(uid, 0),
            "name": info["name"] if info else f"left the server ({uid})",
            "avatar": info["avatar"] if info else "https://cdn.discordapp.com/embed/avatars/0.png",
            "gone": info is None,
        })
    roster.sort(key=lambda r: -r["xp"])
    for i, r_ in enumerate(roster, 1):
        r_["rank"] = i
    return page(request, "levels.html", q=q, results=results, roster=roster)


@app.post("/levels/adjust")
def levels_adjust(request: Request, user_id: str = Form(...), q: str = Form(""),
                  levels_delta: str = Form(""), xp_delta: str = Form(""),
                  note: str = Form("")):
    if (r := guard(request)):
        return r
    try:
        dl = int(levels_delta or 0)
        dx = int(xp_delta or 0)
    except ValueError:
        return back(f"/levels?q={urllib.parse.quote(q)}", err="Use whole numbers.")
    if not dl and not dx:
        return back(f"/levels?q={urllib.parse.quote(q)}", err="Enter a level or XP change.")
    doc = mongo["leveling"]["members"].find_one({"_id": user_id}) or {}
    old_xp = int(doc.get("xp", 0))
    new_xp = old_xp + dx
    if dl:
        lvl = level_for_xp(old_xp)
        target = max(0, lvl + dl)
        new_xp += total_xp_for_level(target) - total_xp_for_level(lvl)
    new_xp = max(0, new_xp)
    mongo["leveling"]["members"].update_one({"_id": user_id},
                                            {"$set": {"xp": new_xp}}, upsert=True)
    audit("levels.adjust",
          f"{display_name(user_id)}: xp {old_xp} -> {new_xp}" + (f" ({note})" if note else ""))
    return back(f"/levels?q={urllib.parse.quote(q)}",
                ok=f"Done. {display_name(user_id)} is now level {level_for_xp(new_xp)}.")


# ------------------------- moderation -------------------------

@app.get("/moderation", response_class=HTMLResponse)
def moderation(request: Request):
    if (r := guard(request)):
        return r
    cutoff = int(time.time()) - 3600
    removals = list(mongo["moderation"]["deputy_removals"].find().sort("timestamp", -1).limit(20))
    budgets = {}
    for e in removals:
        if e.get("timestamp", 0) >= cutoff:
            budgets[e["deputy_id"]] = budgets.get(e["deputy_id"], 0) + 1
    budget_rows = [{"name": display_name(d), "used": n, "limit": 3} for d, n in budgets.items()]
    for e in removals:
        e["deputy"] = display_name(e.get("deputy_id"))
        e["target"] = display_name(e.get("target_id"))
        e["when"] = fmt_eastern(datetime.utcfromtimestamp(e["timestamp"])) if e.get("timestamp") else ""

    try:
        rules = api("GET", f"/guilds/{GUILD_ID}/auto-moderation/rules")
    except RuntimeError:
        rules = []

    debts = list(mongo["mockdebt"]["pending"].find())
    for d in debts:
        d["target"] = display_name(d.get("target_id"))
        d["buyer"] = display_name(d.get("buyer_id"))
        d["secs"] = int(d.get("remaining", 0))

    feed = []
    try:
        for m in api("GET", f"/channels/{LAW_CHAT_ID}/messages?limit=15"):
            text = m.get("content") or (m["embeds"][0].get("description", "")
                                        if m.get("embeds") else "")
            when = datetime.fromisoformat(m["timestamp"]).astimezone(EASTERN).strftime("%b %d, %I:%M %p")
            feed.append({"author": m["author"]["username"], "text": text[:300], "when": when})
    except (RuntimeError, ValueError, KeyError):
        pass

    return page(request, "moderation.html", budgets=budget_rows, removals=removals,
                rules=rules, debts=debts, feed=feed)


@app.post("/moderation/debt/forgive")
def forgive_debt(request: Request, key: str = Form(...)):
    if (r := guard(request)):
        return r
    doc = mongo["mockdebt"]["pending"].find_one_and_delete({"_id": key})
    if doc:
        audit("mockdebt.forgive", f"{display_name(doc.get('target_id'))} "
                                  f"({int(doc.get('remaining', 0))}s)")
    return back("/moderation", ok="Debt forgiven.")


# ------------------------- tickets -------------------------

@app.get("/tickets", response_class=HTMLResponse)
def tickets(request: Request):
    if (r := guard(request)):
        return r
    docs = list(mongo["tickets"]["tickets"].find().sort("number", -1).limit(60))
    for t in docs:
        t["opener"] = "Anonymous" if t.get("anonymous") else display_name(t.get("opener_id"))
        t["claimer"] = display_name(t["claimed_by"]) if t.get("claimed_by") else ""
        t["when"] = (fmt_eastern(datetime.utcfromtimestamp(t["opened_at"]))
                     if t.get("opened_at") else "")
        t["link"] = f"https://discord.com/channels/{GUILD_ID}/{t.get('channel_id')}"
    open_docs = [t for t in docs if t.get("status") == "open"]
    closed_docs = [t for t in docs if t.get("status") != "open"][:25]

    transcripts = []
    try:
        for m in api("GET", f"/channels/{TICKET_LOG_CHANNEL}/messages?limit=25"):
            for a in m.get("attachments", []):
                when = datetime.fromisoformat(m["timestamp"]).astimezone(EASTERN).strftime("%b %d %Y")
                transcripts.append({"name": a["filename"], "url": a["url"], "when": when})
    except (RuntimeError, ValueError, KeyError):
        pass

    return page(request, "tickets.html", open_docs=open_docs,
                closed_docs=closed_docs, transcripts=transcripts)


# ------------------------- direct messages -------------------------

def dm_channel_id(user_id):
    """Herupa's DM channel with this user (create-or-get), cached an hour."""
    return cached(f"dm:{user_id}", 3600,
                  lambda: api("POST", "/users/@me/channels",
                              {"recipient_id": str(user_id)})["id"])


def fetch_thread(user_id, limit=50):
    msgs = api("GET", f"/channels/{dm_channel_id(user_id)}/messages?limit={limit}")
    out = []
    for m in reversed(msgs):
        content = m.get("content") or ""
        if not content and m.get("embeds"):
            e = m["embeds"][0]
            content = "[embed] " + (e.get("title") or e.get("description") or "")[:200]
        out.append({
            "id": m["id"],
            "her": m["author"]["id"] == HERUPA_ID,
            "content": content,
            "attachments": [{"name": a["filename"], "url": a["url"]}
                            for a in m.get("attachments", [])],
            "when": datetime.fromisoformat(m["timestamp"]).astimezone(EASTERN)
                    .strftime("%b %d, %I:%M %p"),
        })
    return out


def _avatar_of(uid, members):
    info = members.get(uid)
    return info["avatar"] if info else "https://cdn.discordapp.com/embed/avatars/0.png"


@app.get("/dms", response_class=HTMLResponse)
def dms(request: Request, u: str = "", q: str = ""):
    if (r := guard(request)):
        return r
    members = all_members()
    convos = list(mongo["dms"]["conversations"].find().sort("last_ts", -1).limit(60))
    for c in convos:
        info = members.get(c["_id"])
        c["display"] = info["name"] if info else c.get("name", c["_id"])
        c["avatar"] = _avatar_of(c["_id"], members)
        c["when"] = fmt_eastern(c.get("last_ts"))

    found = []
    if q.strip():
        try:
            hits = api("GET", f"/guilds/{GUILD_ID}/members/search?"
                       + urllib.parse.urlencode({"query": q.strip(), "limit": 8}))
        except RuntimeError:
            hits = []
        found = [{"id": m["user"]["id"],
                  "name": m.get("nick") or m["user"].get("global_name") or m["user"]["username"]}
                 for m in hits if not m["user"].get("bot")]

    convo, thread = None, []
    if u:
        info = members.get(u)
        name = (info["name"] if info else
                next((c["display"] for c in convos if c["_id"] == u), f"user {u}"))
        try:
            thread = fetch_thread(u)
        except RuntimeError as e:
            return page(request, "dms.html", convos=convos, found=found, q=q,
                        convo=None, thread_json="[]",
                        err=f"Could not open that DM: {e}")
        convo = {"id": u, "name": name, "avatar": _avatar_of(u, members)}
    thread_json = json.dumps(thread).replace("<", "\\u003c")
    return page(request, "dms.html", convos=convos, found=found, q=q,
                convo=convo, thread_json=thread_json)


@app.get("/dms/search")
def dms_search(request: Request, q: str = ""):
    if not _session_ok(request):
        return JSONResponse([], status_code=401)
    if not q.strip():
        return JSONResponse([])
    try:
        hits = api("GET", f"/guilds/{GUILD_ID}/members/search?"
                   + urllib.parse.urlencode({"query": q.strip(), "limit": 8}))
    except RuntimeError:
        return JSONResponse([], status_code=502)
    members = all_members()
    return JSONResponse([
        {"id": m["user"]["id"],
         "name": m.get("nick") or m["user"].get("global_name") or m["user"]["username"],
         "avatar": _avatar_of(m["user"]["id"], members)}
        for m in hits if not m["user"].get("bot")])


@app.get("/dms/thread")
def dms_thread(request: Request, u: str):
    if not _session_ok(request):
        return JSONResponse([], status_code=401)
    try:
        return JSONResponse(fetch_thread(u))
    except RuntimeError:
        return JSONResponse([], status_code=502)


@app.post("/dms/send")
def dms_send(request: Request, user_id: str = Form(...), content: str = Form(...)):
    if (r := guard(request)):
        return r
    if not content.strip():
        return back(f"/dms?u={user_id}", err="Write something first.")
    try:
        api("POST", f"/channels/{dm_channel_id(user_id)}/messages",
            {"content": content.strip()})
    except RuntimeError as e:
        return back(f"/dms?u={user_id}", err=str(e))
    name = display_name(user_id)
    mongo["dms"]["conversations"].update_one(
        {"_id": str(user_id)},
        {"$set": {"name": name, "last_ts": datetime.utcnow(),
                  "preview": content.strip()[:80]}},
        upsert=True)
    audit("dms.send", f"-> {name}")
    return back(f"/dms?u={user_id}")


# ------------------------- panels -------------------------

@app.get("/panels", response_class=HTMLResponse)
def panels(request: Request):
    if (r := guard(request)):
        return r
    return page(request, "panels.html", channels=text_channels(), roles=assignable_roles())


@app.post("/panels/roles")
def post_role_panel(request: Request, channel_id: str = Form(...), title: str = Form(...),
                    description: str = Form(""), mode: str = Form("t"),
                    role_ids: list[str] = Form([])):
    if (r := guard(request)):
        return r
    allowed = {x["id"]: x for x in assignable_roles()}
    picked = [allowed[i] for i in role_ids if i in allowed][:25]
    if not picked:
        return back("/panels", err="Pick at least one role.")
    rows, row = [], []
    for role in picked:
        row.append({"type": 2, "style": 2, "label": role["name"][:80],
                    "custom_id": f"herupa:role:{'s' if mode == 's' else 't'}:{role['id']}"})
        if len(row) == 5:
            rows.append({"type": 1, "components": row})
            row = []
    if row:
        rows.append({"type": 1, "components": row})
    embed = {"title": title.strip(), "color": BRAND}
    if description.strip():
        embed["description"] = description.strip()
    if mode == "s":
        embed.setdefault("footer", {"text": "Pick one. Choosing another swaps it."})
    else:
        embed.setdefault("footer", {"text": "Click to add a role. Click again to remove it."})
    try:
        api("POST", f"/channels/{channel_id}/messages",
            {"embeds": [embed], "components": rows})
    except RuntimeError as e:
        return back("/panels", err=str(e))
    audit("panels.roles", f"{title.strip()} ({len(picked)} roles)")
    return back("/panels", ok="Role panel posted.")


@app.post("/panels/tickets")
def post_ticket_panel(request: Request, channel_id: str = Form(...)):
    if (r := guard(request)):
        return r
    embed = {
        "title": "🎫 Need a hand? Open a ticket",
        "color": BRAND,
        "description": ("Pick the team you need and a private channel opens "
                        "between you and them.\n\n"
                        "🤖 **Tech Support**: server or bot issues\n"
                        "👀 **Moderation**: report a problem with a member\n"
                        "📸 **Media**: events, media, and content"),
    }
    rows = [{"type": 1, "components": [
        {"type": 2, "style": 1, "label": "Tech Support", "emoji": {"name": "🤖"},
         "custom_id": "herupa_ticket_tech"},
        {"type": 2, "style": 4, "label": "Moderation", "emoji": {"name": "👀"},
         "custom_id": "herupa_ticket_mod"},
        {"type": 2, "style": 2, "label": "Media", "emoji": {"name": "📸"},
         "custom_id": "herupa_ticket_media"},
    ]}]
    try:
        msg = api("POST", f"/channels/{channel_id}/messages",
                  {"embeds": [embed], "components": rows})
        api("PUT", f"/channels/{channel_id}/pins/{msg['id']}")
    except RuntimeError as e:
        return back("/panels", err=str(e))
    audit("panels.tickets", f"-> {channel_id}")
    return back("/panels", ok="Ticket panel posted and pinned.")
