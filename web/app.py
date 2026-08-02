"""Herupa's web control room.

Runs beside the bot on the Pi as its own systemd service (herupa-web). Shares
the bot's Mongo and talks to Discord over REST with the bot token, so a UI
crash can never take Herupa down. Auth is a single admin password from
/etc/environment (HERUPA_WEB_PASSWORD) with signed-random session cookies.
"""

import calendar
import hashlib
import hmac
import json
import os
import re
import secrets
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from typing import List
from zoneinfo import ZoneInfo

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pymongo import MongoClient

# ------------------------- config -------------------------

DEFAULT_GUILD_ID = "645847490020638720"   # Chill Club (Herupa's home server)
LOG_GUILD_ID = "1249872743520931870"      # dedicated logging server (not selectable)
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
# Stamped onto every static URL (?v=...) so browsers refetch css/js after a
# deploy — the service restarts on deploy, which mints a fresh stamp.
templates.env.globals["asset_v"] = str(int(time.time()))

# ------------------------- auth -------------------------
# Sessions are stateless: the cookie is "<expiry>.<hmac>", validated by
# signature so it survives a service restart (no server-side session store to
# wipe). The signing secret is stable across restarts (env, with a
# password-derived fallback), so a deploy no longer logs the admin out.

LOGIN_FAILS = {}       # ip -> [fail epochs]
SESSION_TTL = 7 * 86400
SECRET = (os.environ.get("HERUPA_WEB_SECRET") or ("hs-fallback:" + PASSWORD)).encode()


def _make_token(ttl=SESSION_TTL):
    exp = str(int(time.time()) + ttl)
    sig = hmac.new(SECRET, exp.encode(), hashlib.sha256).hexdigest()
    return exp + "." + sig


def _valid_token(tok):
    if not tok or "." not in tok:
        return False
    exp, sig = tok.rsplit(".", 1)
    good = hmac.new(SECRET, exp.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(sig, good):
        return False
    try:
        return int(exp) > time.time()
    except ValueError:
        return False


def _session_ok(request):
    return _valid_token(request.cookies.get("hs"))


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
    resp = RedirectResponse("/", status_code=303)
    resp.set_cookie("hs", _make_token(), max_age=SESSION_TTL, httponly=True, samesite="lax")
    return resp


@app.get("/logout")
def logout(request: Request):
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


def bot_guilds():
    """Servers Herupa is in (minus the logging server) for the picker, cached
    five minutes."""
    def fetch():
        out = []
        for g in api("GET", "/users/@me/guilds"):
            if g["id"] == LOG_GUILD_ID:
                continue
            out.append({"id": g["id"], "name": g["name"],
                        "icon": (f"https://cdn.discordapp.com/icons/{g['id']}/{g['icon']}.png?size=64"
                                 if g.get("icon") else "")})
        return out
    return cached("bot_guilds", 300, fetch)


def current_gid(request):
    """The server the admin is working in: the picker cookie when it names a
    guild Herupa is still in, else the home server."""
    gid = request.cookies.get("hg", "")
    if gid and any(g["id"] == gid for g in bot_guilds()):
        return gid
    return DEFAULT_GUILD_ID


def guild_channels(gid):
    return cached(f"channels:{gid}", 60, lambda: api("GET", f"/guilds/{gid}/channels"))


def text_channels(gid):
    out = [dict(c, label="#" + c["name"]) for c in guild_channels(gid) if c["type"] in (0, 5)]
    return sorted(out, key=lambda c: c["position"])


def messageable_channels(gid):
    """Text channels plus voice and stage chats (they take messages too)."""
    voice = [dict(c, label="🔊 " + c["name"])
             for c in guild_channels(gid) if c["type"] in (2, 13)]
    return text_channels(gid) + sorted(voice, key=lambda c: c["position"])


def guild_roles(gid):
    return cached(f"roles:{gid}", 60, lambda: api("GET", f"/guilds/{gid}/roles"))


def herupa_top_position(gid):
    member = cached(f"me_member:{gid}", 300,
                    lambda: api("GET", f"/guilds/{gid}/members/{HERUPA_ID}"))
    positions = [r["position"] for r in guild_roles(gid) if r["id"] in member["roles"]]
    return max(positions) if positions else 0


def assignable_roles(gid):
    """Roles a self-assign panel may offer: nothing managed, dangerous, or
    at/above Herupa's own top role."""
    top = herupa_top_position(gid)
    out = []
    for r in guild_roles(gid):
        if r["id"] == gid or r.get("managed"):
            continue
        if int(r["permissions"]) & DANGEROUS_PERMS:
            continue
        if r["position"] >= top:
            continue
        out.append(r)
    return sorted(out, key=lambda r: -r["position"])


def all_members(gid):
    """Every guild member (paginated REST list), cached five minutes."""
    def fetch():
        out, after = {}, "0"
        while True:
            batch = api("GET", f"/guilds/{gid}/members?limit=1000&after={after}")
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
    return cached(f"all_members:{gid}", 300, fetch)


_NAMES = {}

def display_name(user_id):
    """Best-effort member name, cached ten minutes."""
    user_id = str(user_id)
    hit = _NAMES.get(user_id)
    if hit and hit[0] > time.time():
        return hit[1]
    try:
        m = api("GET", f"/guilds/{DEFAULT_GUILD_ID}/members/{user_id}")
        name = m.get("nick") or m["user"].get("global_name") or m["user"]["username"]
    except RuntimeError:
        try:
            u = api("GET", f"/users/{user_id}")
            name = u.get("global_name") or u["username"]
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


def feature_disabled(gid, feature):
    """Mirror of the bot's $feature toggles (Mongo features/config)."""
    doc = mongo["features"]["config"].find_one({"guild_id": str(gid)}) or {}
    return feature in [f.lower() for f in doc.get("disabled", [])]


def audit(action, detail):
    mongo["webui"]["audit"].insert_one(
        {"ts": datetime.utcnow(), "action": action, "detail": detail})


def page(request, name, **ctx):
    ctx.setdefault("ok", request.query_params.get("ok", ""))
    ctx.setdefault("err", request.query_params.get("err", ""))
    ctx["active"] = name.split(".")[0]
    # Server picker in the sidebar: every page knows the guild list and which
    # one is selected.
    try:
        ctx.setdefault("guilds", bot_guilds())
    except RuntimeError:
        ctx.setdefault("guilds", [])
    ctx.setdefault("gid", current_gid(request))
    return templates.TemplateResponse(request, name, ctx)


@app.get("/guild/select")
def guild_select(request: Request, id: str = ""):
    if (r := guard(request)):
        return r
    dest = request.headers.get("referer") or "/"
    resp = RedirectResponse(dest, status_code=303)
    if any(g["id"] == id for g in bot_guilds()):
        resp.set_cookie("hg", id, max_age=365 * 86400, httponly=True, samesite="lax")
    return resp


def back(path, ok=None, err=None):
    sep = "&" if "?" in path else "?"   # path may already carry a query (e.g. ?u=)
    if ok:
        q = sep + "ok=" + urllib.parse.quote(ok)
    elif err:
        q = sep + "err=" + urllib.parse.quote(err)
    else:
        q = ""
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

    gid = current_gid(request)
    try:
        g = cached(f"guild:{gid}", 120, lambda: api("GET", f"/guilds/{gid}?with_counts=true"))
        members = g.get("approximate_member_count", 0)
        online = g.get("approximate_presence_count", 0)
        gname = g.get("name", "")
        icon = (f"https://cdn.discordapp.com/icons/{gid}/{g['icon']}.png?size=64"
                if g.get("icon") else "")
    except Exception:
        members = online = 0
        gname, icon = "", ""

    upcoming = list(mongo["webui"]["scheduled"].find({"enabled": True})
                    .sort("next_fire", 1).limit(5))
    for s in upcoming:
        s["when"] = fmt_eastern(s.get("next_fire"))
        s["repeat"] = repeat_label(s.get("repeat", "none"))
    recent = list(mongo["webui"]["audit"].find().sort("ts", -1).limit(6))
    for a in recent:
        a["when"] = fmt_eastern(a.get("ts"))

    return page(request, "dashboard.html", checks=checks, members=members,
                online=online, gname=gname, icon=icon,
                upcoming=upcoming, recent=recent)


# ------------------------- scheduler -------------------------

@app.get("/schedule", response_class=HTMLResponse)
def schedule(request: Request):
    if (r := guard(request)):
        return r
    gid = current_gid(request)
    # Channel labels across every server, plus which guild owns each channel,
    # so the list can be filtered to the selected server.
    chan_labels, chan_guild = {}, {}
    for g in bot_guilds():
        try:
            for c in messageable_channels(g["id"]):
                chan_labels[c["id"]] = c["label"]
                chan_guild[c["id"]] = g["id"]
        except RuntimeError:
            pass
    docs = list(mongo["webui"]["scheduled"].find().sort([("enabled", -1), ("next_fire", 1)]))
    # Keep DM schedules (not tied to a server) and this server's channel sends.
    docs = [d for d in docs
            if d.get("user_id")
            or chan_guild.get(str(d.get("channel_id")), gid) == gid]
    for d in docs:
        d["id"] = str(d["_id"])
        d["when"] = fmt_eastern(d.get("next_fire"))
        d["last"] = fmt_eastern(d.get("last_fired"))
        if d.get("user_id"):
            d["channel"] = "💬 " + d.get("dm_name", "DM")
        else:
            d["channel"] = chan_labels.get(str(d.get("channel_id")), str(d.get("channel_id")))
        d["repeat_label"] = repeat_label(d.get("repeat", "none"))
    events = [{"id": d["id"], "name": d["name"], "wall": d["wall"],
               "repeat": d.get("repeat", "none"), "enabled": d["enabled"],
               "channel": d["channel"], "content": d.get("content") or "",
               "channel_id": str(d.get("channel_id") or ""),
               "user_id": str(d.get("user_id") or ""),
               "dm_name": d.get("dm_name", ""), "embed": d.get("embed"),
               "when": d["when"], "last": d["last"]} for d in docs]
    events_json = json.dumps(events).replace("<", "\\u003c")
    members = all_members(gid)
    bdays = []
    for b in mongo["birthdays"]["dates"].find({"guild_id": gid}):
        info = members.get(b["user_id"])
        if info and info.get("bot"):
            continue
        bdays.append({"name": info["name"] if info else b.get("name", "member"),
                      "month": b["month"], "day": b["day"]})
    bdays_json = json.dumps(bdays).replace("<", "\\u003c")
    return page(request, "schedule.html", docs=docs, channels=messageable_channels(gid),
                events_json=events_json, bdays_json=bdays_json)


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


@app.post("/schedule/edit")
def schedule_edit(request: Request, doc_id: str = Form(...), name: str = Form(...),
                  wall: str = Form(...), repeat: str = Form("none"),
                  content: str = Form(""), channel_id: str = Form(""),
                  use_embed: str = Form(""), embed_title: str = Form(""),
                  embed_description: str = Form(""), embed_color: str = Form("#FFB7C5")):
    if (r := guard(request)):
        return r
    from bson import ObjectId
    doc = mongo["webui"]["scheduled"].find_one({"_id": ObjectId(doc_id)})
    if not doc:
        return back("/schedule", err="That schedule is gone.")
    is_dm = bool(doc.get("user_id"))
    if not content.strip() and not (not is_dm and use_embed and (embed_title or embed_description)):
        return back("/schedule", err="Give the message some content.")
    nxt = next_fire_utc(wall, repeat)
    if nxt is None:
        return back("/schedule", err="That time is already in the past. Pick a future time or add a repeat.")
    update = {"name": name.strip() or "Untitled", "content": content.strip(),
              "wall": wall, "repeat": repeat, "next_fire": nxt, "enabled": True}
    if is_dm:
        update["embed"] = None            # DM schedules are text-only
    else:
        if channel_id:
            update["channel_id"] = int(channel_id)
        update["embed"] = ({"title": embed_title.strip(),
                            "description": embed_description.strip(),
                            "color": int(embed_color.lstrip("#") or "FFB7C5", 16)}
                           if use_embed else None)
    mongo["webui"]["scheduled"].update_one({"_id": doc["_id"]}, {"$set": update})
    audit("schedule.edit", f"{name.strip()} ({repeat})")
    return back("/schedule", ok=f"Updated. Next send {fmt_eastern(nxt)} Eastern.")


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
    return page(request, "composer.html", channels=messageable_channels(current_gid(request)))


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
    label = next((c["label"] for c in messageable_channels(current_gid(request))
                  if c["id"] == channel_id), channel_id)
    audit("composer.send", f"-> {label}")
    return back("/composer", ok=f"Sent to {label}.")


# ------------------------- levels -------------------------

@app.get("/levels", response_class=HTMLResponse)
def levels(request: Request, q: str = ""):
    if (r := guard(request)):
        return r
    gid = current_gid(request)
    if feature_disabled(gid, "leveling"):
        return page(request, "levels.html", q="", results=[], roster=[], feature_off=True)
    results = []
    if q.strip():
        try:
            found = api("GET", f"/guilds/{gid}/members/search?"
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
    # full roster, leaderboard-ordered (XP is global; names resolve against the
    # selected server, anyone not in it shows as left-the-server)
    members = all_members(gid)
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
    if feature_disabled(current_gid(request), "leveling"):
        return back("/levels", err="Leveling is turned off in this server.")
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


# ------------------------- direct messages -------------------------

def dm_channel_id(user_id):
    """Herupa's DM channel with this user (create-or-get), cached an hour."""
    return cached(f"dm:{user_id}", 3600,
                  lambda: api("POST", "/users/@me/channels",
                              {"recipient_id": str(user_id)})["id"])


def resolve_mentions(content, msg):
    """Turn <@id> tokens into readable @names using the message's mention list."""
    names = {u["id"]: (u.get("global_name") or u["username"])
             for u in msg.get("mentions", [])}
    return re.sub(r"<@!?(\d+)>",
                  lambda mo: "@" + names.get(mo.group(1), "user"), content)


def fetch_thread(user_id, limit=50):
    msgs = api("GET", f"/channels/{dm_channel_id(user_id)}/messages?limit={limit}")
    out = []
    for m in reversed(msgs):
        content = resolve_mentions(m.get("content") or "", m)
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
    members = all_members(current_gid(request))
    convos = list(mongo["dms"]["conversations"].find().sort("last_ts", -1).limit(60))
    for c in convos:
        info = members.get(c["_id"])
        c["display"] = info["name"] if info else c.get("name", c["_id"])
        c["avatar"] = _avatar_of(c["_id"], members)
        c["when"] = fmt_eastern(c.get("last_ts"))

    found = []
    if q.strip():
        try:
            hits = api("GET", f"/guilds/{current_gid(request)}/members/search?"
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
        hits = api("GET", f"/guilds/{current_gid(request)}/members/search?"
                   + urllib.parse.urlencode({"query": q.strip(), "limit": 8}))
    except RuntimeError:
        return JSONResponse([], status_code=502)
    members = all_members(current_gid(request))
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


@app.post("/dms/schedule")
def dms_schedule(request: Request, user_id: str = Form(...), content: str = Form(...),
                 wall: str = Form(...), repeat: str = Form("none")):
    if (r := guard(request)):
        return r
    if not content.strip():
        return back(f"/dms?u={user_id}", err="Write the message first.")
    nxt = next_fire_utc(wall, repeat)
    if nxt is None:
        return back(f"/dms?u={user_id}", err="That time is already past. Pick a future time.")
    name = display_name(user_id)
    mongo["webui"]["scheduled"].insert_one({
        "name": f"DM to {name}", "user_id": int(user_id), "dm_name": name,
        "channel_id": None, "content": content.strip(), "embed": None,
        "wall": wall, "repeat": repeat, "next_fire": nxt,
        "enabled": True, "last_fired": None})
    audit("dms.schedule", f"-> {name} at {fmt_eastern(nxt)}")
    return back(f"/dms?u={user_id}",
                ok=f"Scheduled a DM to {name} for {fmt_eastern(nxt)} Eastern.")


@app.post("/dms/delete")
def dms_delete(request: Request, user_id: str = Form(...), message_id: str = Form(...)):
    if not _session_ok(request):
        return JSONResponse({"ok": False, "error": "Not signed in."}, status_code=401)
    # Discord only lets a bot delete its OWN messages in a DM, so this can't
    # touch the other person's messages even if asked to.
    try:
        api("DELETE", f"/channels/{dm_channel_id(user_id)}/messages/{message_id}")
    except RuntimeError as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=400)
    audit("dms.delete", f"in DM with {display_name(user_id)}")
    return JSONResponse({"ok": True})


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


# ------------------------- projects -------------------------

PROJ_STATUSES = [("todo", "📋", "To Do"), ("doing", "🔨", "In Progress"),
                 ("review", "👀", "Review"), ("done", "✅", "Done")]


@app.get("/projects", response_class=HTMLResponse)
def projects(request: Request):
    if (r := guard(request)):
        return r
    gid = current_gid(request)
    if feature_disabled(gid, "projects"):
        return page(request, "projects.html", feature_off=True, boards=[],
                    statuses=PROJ_STATUSES)
    conf = mongo["projects"]["config"].find_one({"guild_id": gid}) or {}
    forums = conf.get("forums", {})
    members = all_members(gid) if forums else {}
    # Same "overdue" clock as the cog: the guild's projects timezone, UTC default.
    try:
        proj_tz = ZoneInfo(conf.get("timezone") or "UTC")
    except (KeyError, ValueError):
        proj_tz = ZoneInfo("UTC")
    today = datetime.now(proj_tz).date().isoformat()
    boards = []
    for fid, fc in sorted(forums.items(), key=lambda kv: kv[1]["name"].casefold()):
        docs = list(mongo["projects"]["tasks"].find({"guild_id": gid, "forum_id": fid}))
        cols = {key: [] for key, _, _ in PROJ_STATUSES}
        for d in docs:
            status = d.get("status") if d.get("status") in cols else "todo"
            info = members.get(d.get("assignee_id") or "")
            cols[status].append({
                "title": d.get("title", "untitled"),
                "url": f"https://discord.com/channels/{gid}/{d['thread_id']}",
                "assignee": info["name"] if info else None,
                "avatar": info["avatar"] if info else None,
                "due": d.get("due"),
                "overdue": bool(d.get("due") and status != "done" and d["due"] < today),
                "urgent": d.get("priority") == "urgent",
                "completed_at": d.get("completed_at") or 0,
                "created_at": d.get("created_at") or 0,
            })
        for key in ("todo", "doing", "review"):
            cols[key].sort(key=lambda c: (c["due"] or "9999-99-99", -c["created_at"]))
        done_total = len(cols["done"])
        cols["done"].sort(key=lambda c: -c["completed_at"])
        cols["done"] = cols["done"][:15]   # recent finishes only; the rest live in Discord
        boards.append({
            "name": fc["name"],
            "forum_url": f"https://discord.com/channels/{gid}/{fid}",
            "cols": cols, "done_total": done_total,
            "open": sum(len(cols[k]) for k in ("todo", "doing", "review")),
        })
    return page(request, "projects.html", boards=boards, statuses=PROJ_STATUSES,
                feature_off=False)


# ------------------------- features -------------------------
# Mirrors FEATURES in Herupa/cogs/FeatureManager.py (keep in sync). The bot
# re-reads Mongo every 30s, so toggles here apply without a reload.

FEATURES = [
    ("leveling", "XP earning, $rank, $daily, $leaderboard, and the level shop"),
    ("tickets", "the ticket panel and $whisper reports"),
    ("rooms", "auto-created voice rooms and $crpm"),
    ("music", "the Hibiki DJ crew"),
    ("moderation", "$kick, $ban, and $timeout"),
    ("accounts", "$link, $verify, and $lookup"),
    ("minecraft", "Minecraft account linking, whitelist sync, and the chat bridge"),
    ("birthdays", "$birthday and the daily wishes"),
    ("counting", "the counting game"),
    ("favorites", "favorite pings on voice join"),
    ("mock", "the $mock voice parrot"),
    ("projects", "forum project boards, $task and $board"),
    ("project-reminders", "DM assignees when their task is due today or tomorrow"),
    ("project-nudges", "daily overdue reminders inside task threads"),
    ("project-digest", "morning project summary to the digest channel"),
]


@app.get("/features", response_class=HTMLResponse)
def features(request: Request):
    if (r := guard(request)):
        return r
    gid = current_gid(request)
    doc = mongo["features"]["config"].find_one({"guild_id": gid}) or {}
    disabled = {f.lower() for f in doc.get("disabled", [])}
    rows = [{"name": n, "desc": d, "on": n not in disabled} for n, d in FEATURES]
    return page(request, "features.html", rows=rows)


@app.post("/features/toggle")
def features_toggle(request: Request, name: str = Form(...), state: str = Form(...)):
    if (r := guard(request)):
        return r
    gid = current_gid(request)
    if name not in {n for n, _ in FEATURES} or state not in ("on", "off"):
        return back("/features", err="I don't know that feature.")
    op = "$pull" if state == "on" else "$addToSet"
    mongo["features"]["config"].update_one(
        {"guild_id": gid}, {op: {"disabled": name}}, upsert=True)
    audit("features.toggle", f"{name} -> {state} in {gid}")
    return back("/features", ok=f"{name} is now {state}. "
                               "Herupa picks it up within half a minute.")


# ------------------------- minecraft -------------------------

import asyncio
import sys as _sys
_sys.path.append(os.path.join(BASE, "..", "Herupa"))
from tools.MinecraftRcon import rcon as mc_rcon  # noqa: E402

MC_GROUP_RE = re.compile(r"^[A-Za-z0-9_-]{1,36}$")


def mc_conf(gid):
    doc = mongo["accounts"]["config"].find_one({"guild_id": str(gid)}) or {}
    mc = doc.get("minecraft")
    return mc if isinstance(mc, dict) else None


def mc_command(mc, command):
    """One RCON command from the sync web process; raises on failure."""
    password = mc.get("rcon_password") or os.environ.get("MC_RCON_PASSWORD", "")
    return asyncio.run(mc_rcon(mc.get("rcon_host", "minecraft.local"),
                               int(mc.get("rcon_port", 25575)), password, command))


def _strip_mc_colors(text):
    return re.sub("§.", "", text or "")


@app.get("/minecraft", response_class=HTMLResponse)
def minecraft(request: Request):
    if (r := guard(request)):
        return r
    gid = current_gid(request)
    if feature_disabled(gid, "accounts") or feature_disabled(gid, "minecraft"):
        return page(request, "minecraft.html", feature_off=True, configured=True)
    mc = mc_conf(gid)
    if mc is None:
        return page(request, "minecraft.html", feature_off=False, configured=False)

    online, players, whitelist = False, [], []
    try:
        reply = _strip_mc_colors(mc_command(mc, "list"))
        online = True
        if ":" in reply:
            players = [p.strip() for p in reply.split(":", 1)[1].split(",") if p.strip()]
        wl = _strip_mc_colors(mc_command(mc, "whitelist list"))
        if ":" in wl:
            whitelist = sorted((n.strip() for n in wl.split(":", 1)[1].split(",")
                                if n.strip()), key=str.lower)
    except Exception:
        pass

    members = all_members(gid)
    linked = {}   # minecraft name (lower) -> member info
    for l in mongo["accounts"]["links"].find({"guild_id": gid, "type": "minecraft"}):
        info = members.get(l.get("user_id", ""))
        if l.get("username"):
            linked[l["username"].lower()] = info or {"name": "left the server?",
                                                     "avatar": None}
    wl_rows = [{"name": n, "member": linked.get(n.lower())} for n in whitelist]

    roles = [r for r in sorted(guild_roles(gid), key=lambda x: -x["position"])
             if r["id"] != gid and not r.get("managed")]
    mappings = []
    role_names = {r["id"]: r["name"] for r in roles}
    for rid, group in (mc.get("role_groups") or {}).items():
        mappings.append({"role_id": rid, "group": group,
                         "missing": rid not in role_names})
    world_rows = [{"world": w, "channel_id": str(wc.get("channel_id") or "")}
                  for w, wc in (mc.get("worlds") or {}).items()]
    return page(request, "minecraft.html", feature_off=False, configured=True,
                online=online, players=players, wl_rows=wl_rows, roles=roles,
                mappings=mappings, address=mc.get("address") or mc.get("rcon_host"),
                channels=text_channels(gid), world_rows=world_rows,
                playlist_channel_id=str(mc.get("playerlist_channel_id") or ""))


@app.post("/minecraft/bridge")
def minecraft_bridge(request: Request, world: List[str] = Form([]),
                     world_channel_id: List[str] = Form([]),
                     playlist_channel_id: str = Form("")):
    if (r := guard(request)):
        return r
    gid = current_gid(request)
    mc = mc_conf(gid)
    if mc is None:
        return back("/minecraft", err="No Minecraft server is configured for this server.")
    valid = {c["id"] for c in text_channels(gid)}
    worlds = mc.get("worlds") or {}
    sets, notes, moved = {}, [], 0
    for w, cid in zip(world, world_channel_id):
        wc = worlds.get(w)
        if wc is None or cid not in valid or str(wc.get("channel_id")) == cid:
            continue
        sets[f"minecraft.worlds.{w}.channel_id"] = cid
        moved += 1
        # The game->Discord feed posts to this world's webhook, so move it
        # too and the whole world follows the channel.
        wid = wc.get("webhook_id")
        if wid:
            try:
                api("PATCH", f"/webhooks/{wid}", {"channel_id": cid})
            except RuntimeError as e:
                notes.append(f"{w}'s in-game feed wouldn't move: {e}")
        else:
            notes.append(f"{w} has no webhook recorded; its in-game feed "
                         "stays where it was.")
    unsets = {}
    if (playlist_channel_id and playlist_channel_id in valid
            and playlist_channel_id != str(mc.get("playerlist_channel_id"))):
        sets["minecraft.playerlist_channel_id"] = playlist_channel_id
        unsets["minecraft.playerlist_message_id"] = ""
        old_ch, old_msg = mc.get("playerlist_channel_id"), mc.get("playerlist_message_id")
        if old_ch and old_msg:
            try:
                api("DELETE", f"/channels/{old_ch}/messages/{old_msg}")
            except RuntimeError:
                pass
        moved += 1
    if not sets:
        return back("/minecraft", ok="Nothing to change.")
    update = {"$set": sets}
    if unsets:
        update["$unset"] = unsets
    mongo["accounts"]["config"].update_one({"guild_id": gid}, update, upsert=True)
    audit("minecraft.bridge", f"{moved} change(s) in {gid}")
    msg = f"Saved {moved} bridge change(s). Herupa's side applies within 30 seconds."
    if notes:
        msg += " " + " ".join(notes)
    return back("/minecraft", ok=msg)


@app.post("/minecraft/roles")
def minecraft_roles(request: Request, role_id: List[str] = Form([]),
                    group: List[str] = Form([])):
    if (r := guard(request)):
        return r
    gid = current_gid(request)
    mc = mc_conf(gid)
    if mc is None:
        return back("/minecraft", err="No Minecraft server is configured for this server.")
    valid_roles = {x["id"] for x in guild_roles(gid)}
    new_map, bad = {}, []
    for rid, grp in zip(role_id, group):
        grp = grp.strip().lower()
        if not rid or rid == "none" or not grp:
            continue
        if rid not in valid_roles or not MC_GROUP_RE.match(grp):
            bad.append(grp or rid)
            continue
        new_map[rid] = grp
    if bad:
        return back("/minecraft", err="Skipped invalid entries: " + ", ".join(bad))
    mongo["accounts"]["config"].update_one(
        {"guild_id": gid}, {"$set": {"minecraft.role_groups": new_map}}, upsert=True)
    for grp in set(new_map.values()):
        try:
            mc_command(mc, f"lp creategroup {grp}")
        except Exception:
            break
    audit("minecraft.roles", f"{len(new_map)} mapping(s) in {gid}")
    return back("/minecraft", ok=f"Saved {len(new_map)} mapping(s). "
                                 "Herupa applies them within ten minutes.")


# ------------------------- panels -------------------------

@app.get("/panels", response_class=HTMLResponse)
def panels(request: Request):
    if (r := guard(request)):
        return r
    gid = current_gid(request)
    return page(request, "panels.html", channels=text_channels(gid), roles=assignable_roles(gid))


@app.post("/panels/roles")
def post_role_panel(request: Request, channel_id: str = Form(...), title: str = Form(...),
                    description: str = Form(""), mode: str = Form("t"),
                    role_ids: list[str] = Form([])):
    if (r := guard(request)):
        return r
    allowed = {x["id"]: x for x in assignable_roles(current_gid(request))}
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
    # Panel built from the selected server's ticket config (Mongo
    # tickets/config), mirroring the bot's $ticketpanel output so the buttons
    # bind to the same registered views.
    gid = current_gid(request)
    conf = mongo["tickets"]["config"].find_one({"guild_id": gid})
    if not conf or not conf.get("teams"):
        return back("/panels", err="Tickets are not configured for this server.")
    styles = {"primary": 1, "secondary": 2, "success": 3, "danger": 4}
    lines = ["Need a hand? Pick the team that fits and we'll open a private channel just for you.", ""]
    buttons = []
    for t in conf["teams"]:
        lines.append(f"{t.get('emoji', '🎫')} **{t['label']}**: {t.get('blurb', '')}")
        buttons.append({"type": 2, "style": styles.get(t.get("style"), 1),
                        "label": t["label"], "emoji": {"name": t.get("emoji", "🎫")},
                        "custom_id": f"herupa_ticket:{gid}:{t['key']}"})
    lines += ["", "Your ticket will be visible only to you and the team you choose."]
    if conf.get("anon_enabled", True):
        lines += ["", "🤫 **Want to stay anonymous?** DM me `$whisper <your message>` "
                      "instead and I'll open an anonymous ticket. Your name stays hidden."]
    embed = {"title": "🎫 Open a Ticket", "color": 0x5865F2,
             "description": "\n".join(lines)}
    rows = [{"type": 1, "components": buttons[:5]}]
    try:
        msg = api("POST", f"/channels/{channel_id}/messages",
                  {"embeds": [embed], "components": rows})
        api("PUT", f"/channels/{channel_id}/pins/{msg['id']}")
    except RuntimeError as e:
        return back("/panels", err=str(e))
    audit("panels.tickets", f"-> {channel_id}")
    return back("/panels", ok="Ticket panel posted and pinned.")
