#!/usr/bin/env python3
"""Game -> Discord half of the Minecraft chat bridge, one channel per world.

Runs ON the Minecraft host (systemd: mc-bridge.service), tails the server's
logs/latest.log, works out which world each event happened in, and posts to
that world's Discord channel webhook:

  chat lines       as the player (their name + mc-heads.net head avatar)
  joins / leaves   🟢 / 🔴 one-liners
  deaths           💀 the vanilla death message
  advancements     🏆 advancement / goal / challenge lines
  server up/down   🟩 / 🟥 (to the default webhook only)

WORLD ROUTING: log lines don't say where the player is, so the bridge keeps
a player -> world map by asking Multiverse over LOCAL RCON (`mv who <world>`
per loaded world from `mv list`; the RCON port/password are read from the
server's own server.properties -- this process runs as the minecraft user).
The map refreshes lazily: only when a line actually needs routing and the
map is older than REFRESH seconds, so an idle server costs nothing. A
world's nether/end dimensions (<world>_nether / <world>_the_end) route to
the parent world's channel. Unknown worlds fall back to the default webhook
with a [World] prefix.

The Discord -> game direction lives in Herupa (cogs/MinecraftBridge.py, RCON
tellraw); this script never reads Discord, so the two can't loop.

Stdlib only. Config via environment (see mc-bridge.service):
  MC_BRIDGE_WEBHOOKS  JSON {"WorldName": "webhook url", ..., "default": url}
  MC_LOG              log path (default /opt/minecraft/server/logs/latest.log)
  MC_PROPS            server.properties path (default alongside the log)
"""

import json
import os
import re
import socket
import struct
import sys
import time
import urllib.error
import urllib.request

HOOKS = json.loads(os.environ.get("MC_BRIDGE_WEBHOOKS", "{}"))
LOG = os.environ.get("MC_LOG", "/opt/minecraft/server/logs/latest.log")
PROPS = os.environ.get("MC_PROPS", "/opt/minecraft/server/server.properties")
REFRESH = 15   # max staleness (seconds) of the player->world map when routing

INFO = re.compile(r"^\[\d{2}:\d{2}:\d{2}\] \[Server thread/INFO\]: (.*)$")
CHAT = re.compile(r"^(?:\[Not Secure\] )?<([A-Za-z0-9_]{1,16})> (.*)$")
JOIN = re.compile(r"^([A-Za-z0-9_]{1,16}) joined the game$")
LEAVE = re.compile(r"^([A-Za-z0-9_]{1,16}) left the game$")
ADVANCEMENT = re.compile(r"^([A-Za-z0-9_]{1,16}) has "
                         r"(made the advancement|reached the goal|completed the challenge) "
                         r"(\[.+\])$")
STARTED = re.compile(r"^Done \(")
STOPPING = re.compile(r"^Stopping the server$")
COLORS = re.compile("§.")

# Vanilla death messages all start with the victim's name; the fragments
# below cover every vanilla cause. Checked only for players known online, so
# mobs with player-like names can't fake one.
DEATH_HINTS = (
    "was slain", "was shot", "was killed", "was fireballed", "was pummeled",
    "was pricked", "was stung", "was squashed", "was skewered", "was impaled",
    "was struck by lightning", "was frozen", "froze to death", "was poked",
    "was obliterated", "was blown up", "blew up", "hit the ground",
    "fell from", "fell off", "fell out of", "fell while", "drowned",
    "burned to death", "went up in flames", "went off with a bang",
    "tried to swim in lava", "walked into fire", "walked into a cactus",
    "walked into the danger zone", "discovered the floor was lava",
    "suffocated", "starved to death", "withered away", "left the confines",
    "experienced kinetic energy", "didn't want to live", "was doomed",
    "died", "was roasted", "was squished",
)

player_world = {}   # name -> world (raw, e.g. Survival_nether) or None
map_stamp = 0.0     # monotonic time of the last successful refresh
worlds = []         # loaded world names from mv list


# ----------------------------- local rcon -----------------------------

def rcon_creds():
    port, password = 25575, ""
    with open(PROPS, encoding="utf-8", errors="replace") as f:
        for line in f:
            if line.startswith("rcon.port="):
                port = int(line.split("=", 1)[1].strip())
            elif line.startswith("rcon.password="):
                password = line.split("=", 1)[1].strip()
    return port, password


def rcon(command, timeout=6):
    port, password = rcon_creds()
    s = socket.create_connection(("127.0.0.1", port), timeout=timeout)
    try:
        def send(rid, ptype, payload):
            body = struct.pack("<ii", rid, ptype) + payload.encode() + b"\x00\x00"
            s.sendall(struct.pack("<i", len(body)) + body)

        def recv():
            raw = b""
            while len(raw) < 4:
                chunk = s.recv(4 - len(raw))
                if not chunk:
                    raise OSError("rcon closed")
                raw += chunk
            (length,) = struct.unpack("<i", raw)
            body = b""
            while len(body) < length:
                chunk = s.recv(length - len(body))
                if not chunk:
                    raise OSError("rcon closed")
                body += chunk
            rid, _ = struct.unpack("<ii", body[:8])
            return rid, body[8:-2].decode("utf-8", "replace")

        send(1, 3, password)
        rid, _ = recv()
        if rid == -1:
            raise PermissionError("rcon auth failed")
        send(2, 2, command)
        _, text = recv()
        return COLORS.sub("", text)
    finally:
        s.close()


def world_key(world):
    """Survival_nether / Survival_the_end -> Survival."""
    if not world:
        return None
    for suffix in ("_nether", "_the_end"):
        if world.endswith(suffix):
            return world[: -len(suffix)]
    return world


def refresh_worlds():
    global worlds
    out = []
    for line in rcon("mv list").splitlines():
        m = re.match(r"^([A-Za-z0-9_-]+) - (NORMAL|NETHER|THE_END)$", line.strip())
        if m:
            out.append(m.group(1))
    if out:
        worlds = out


def refresh_map(force=False):
    """Rebuild player -> world from `mv who`. Quietly keeps the old map when
    the server is unreachable."""
    global player_world, map_stamp
    if not force and time.monotonic() - map_stamp < REFRESH:
        return
    try:
        if not worlds:
            refresh_worlds()
        fresh = {}
        for w in worlds:
            reply = rcon(f"mv who {w}")
            m = re.search(rf"^{re.escape(w)}: (.+)$", reply, re.M)
            if not m or m.group(1).strip() == "empty":
                continue
            for name in m.group(1).split(","):
                name = name.strip()
                if re.fullmatch(r"[A-Za-z0-9_]{1,16}", name):
                    fresh[name] = w
        player_world = fresh
        map_stamp = time.monotonic()
    except Exception as e:
        print(f"map refresh failed: {e}", file=sys.stderr)


# ----------------------------- discord -----------------------------

def post(world, payload, tries=3):
    """Post to the world's webhook (falls back to 'default')."""
    key = world_key(world)
    url = HOOKS.get(key) or HOOKS.get("default")
    if not url:
        return
    if url == HOOKS.get("default") and key and key not in HOOKS and "content" in payload:
        payload = dict(payload, content=f"[{key}] {payload['content']}")
    payload.setdefault("allowed_mentions", {"parse": []})
    data = json.dumps(payload).encode()
    for _ in range(tries):
        req = urllib.request.Request(
            url, data=data, headers={"Content-Type": "application/json",
                                     "User-Agent": "herupa-mc-bridge"})
        try:
            urllib.request.urlopen(req, timeout=10).read()
            return
        except urllib.error.HTTPError as e:
            if e.code == 429:
                try:
                    wait = float(json.load(e).get("retry_after", 2))
                except Exception:
                    wait = 2.0
                time.sleep(wait + 0.5)
                continue
            print(f"webhook HTTP {e.code}", file=sys.stderr)
            return
        except (urllib.error.URLError, OSError) as e:
            print(f"webhook unreachable: {e}", file=sys.stderr)
            time.sleep(3)
    print("webhook gave up on a line", file=sys.stderr)


def locate(name):
    """The world a player is in, refreshing the map if it's stale or the
    player is unknown (they may have just joined or changed worlds)."""
    refresh_map()
    if name not in player_world:
        refresh_map(force=True)
    return player_world.get(name)


# ----------------------------- line handling -----------------------------

def handle(line):
    m = INFO.match(line.rstrip("\n"))
    if not m:
        return
    body = m.group(1)

    if (m := CHAT.match(body)):
        name, text = m.groups()
        post(locate(name), {
            "username": name,
            "avatar_url": f"https://mc-heads.net/avatar/{name}/64",
            "content": text[:1900]})
    elif (m := JOIN.match(body)):
        name = m.group(1)
        refresh_map(force=True)
        post(player_world.get(name), {"content": f"🟢 **{name}** joined the game"})
    elif (m := LEAVE.match(body)):
        name = m.group(1)
        world = player_world.pop(name, None)
        post(world, {"content": f"🔴 **{name}** left the game"})
    elif (m := ADVANCEMENT.match(body)):
        name, kind, what = m.groups()
        post(locate(name), {"content": f"🏆 **{name}** has {kind} **{what}**"})
    elif STARTED.match(body):
        player_world.clear()
        refresh_worlds_safe()
        post(None, {"content": "🟩 Server is up!"})
    elif STOPPING.match(body):
        player_world.clear()
        post(None, {"content": "🟥 Server is shutting down."})
    else:
        first, _, rest = body.partition(" ")
        if first in player_world and any(h in rest for h in DEATH_HINTS):
            post(player_world.get(first), {"content": f"💀 {body}"})


def refresh_worlds_safe():
    try:
        refresh_worlds()
    except Exception as e:
        print(f"world list refresh failed: {e}", file=sys.stderr)


# ----------------------------- log following -----------------------------

def follow():
    """Yield lines forever, surviving log rotation and the file not existing."""
    f = None
    inode = None
    first_open = True
    while True:
        if f is None:
            try:
                f = open(LOG, encoding="utf-8", errors="replace")
                inode = os.fstat(f.fileno()).st_ino
                if first_open:
                    f.seek(0, os.SEEK_END)  # no history replay on service start
                first_open = False
            except FileNotFoundError:
                time.sleep(3)
                continue
        line = f.readline()
        if line:
            yield line
            continue
        time.sleep(1)
        try:
            st = os.stat(LOG)
            if st.st_ino != inode or st.st_size < f.tell():
                f.close()
                f = None  # rotated or truncated: reopen (from the start)
        except FileNotFoundError:
            f.close()
            f = None


def main():
    if not HOOKS.get("default"):
        sys.exit("MC_BRIDGE_WEBHOOKS needs at least a \"default\" entry")
    print(f"following {LOG}; webhooks for: {', '.join(sorted(HOOKS))}")
    refresh_worlds_safe()
    refresh_map(force=True)  # players may already be on when we start
    for line in follow():
        try:
            handle(line)
        except Exception as e:  # one weird line must not kill the bridge
            print(f"line handler error: {e}", file=sys.stderr)


if __name__ == "__main__":
    main()
