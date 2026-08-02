#!/usr/bin/env python3
"""Game -> Discord half of the Minecraft chat bridge.

Runs ON the Minecraft host (systemd: mc-bridge.service), tails the server's
logs/latest.log, and posts straight to a Discord channel webhook:

  chat lines       as the player (their name + mc-heads.net head avatar)
  joins / leaves   🟢 / 🔴 one-liners
  deaths           💀 the vanilla death message
  advancements     🏆 advancement / goal / challenge lines
  server up/down   🟩 / 🟥

The Discord -> game direction lives in Herupa (cogs/MinecraftBridge.py, RCON
tellraw); this script never reads Discord, so the two can't loop.

Stdlib only. Config via environment (see mc-bridge.service):
  MC_BRIDGE_WEBHOOK   the channel webhook URL (required)
  MC_LOG              log path (default /opt/minecraft/server/logs/latest.log)

Starts at the END of the log (no history replay) and follows rotation:
latest.log is renamed away and recreated on every server restart, so reopen
whenever the inode changes or the file shrinks.
"""

import json
import os
import re
import sys
import time
import urllib.error
import urllib.request

WEBHOOK = os.environ.get("MC_BRIDGE_WEBHOOK", "")
LOG = os.environ.get("MC_LOG", "/opt/minecraft/server/logs/latest.log")

INFO = re.compile(r"^\[\d{2}:\d{2}:\d{2}\] \[Server thread/INFO\]: (.*)$")
CHAT = re.compile(r"^(?:\[Not Secure\] )?<([A-Za-z0-9_]{1,16})> (.*)$")
JOIN = re.compile(r"^([A-Za-z0-9_]{1,16}) joined the game$")
LEAVE = re.compile(r"^([A-Za-z0-9_]{1,16}) left the game$")
ADVANCEMENT = re.compile(r"^([A-Za-z0-9_]{1,16}) has "
                         r"(made the advancement|reached the goal|completed the challenge) "
                         r"(\[.+\])$")
STARTED = re.compile(r"^Done \(")
STOPPING = re.compile(r"^Stopping the server$")

# Vanilla death messages all start with the victim's name; the fragments
# below cover every vanilla cause. Checked only for players seen online, so
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

online = set()


def post(payload, tries=3):
    payload.setdefault("allowed_mentions", {"parse": []})
    data = json.dumps(payload).encode()
    for _ in range(tries):
        req = urllib.request.Request(
            WEBHOOK, data=data, headers={"Content-Type": "application/json",
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


def handle(line):
    m = INFO.match(line.rstrip("\n"))
    if not m:
        return
    body = m.group(1)

    if (m := CHAT.match(body)):
        name, text = m.groups()
        post({"username": name,
              "avatar_url": f"https://mc-heads.net/avatar/{name}/64",
              "content": text[:1900]})
    elif (m := JOIN.match(body)):
        online.add(m.group(1))
        post({"content": f"🟢 **{m.group(1)}** joined the game"})
    elif (m := LEAVE.match(body)):
        online.discard(m.group(1))
        post({"content": f"🔴 **{m.group(1)}** left the game"})
    elif (m := ADVANCEMENT.match(body)):
        name, kind, what = m.groups()
        post({"content": f"🏆 **{name}** has {kind} **{what}**"})
    elif STARTED.match(body):
        post({"content": "🟩 Server is up!"})
    elif STOPPING.match(body):
        online.clear()
        post({"content": "🟥 Server is shutting down."})
    else:
        first, _, rest = body.partition(" ")
        if first in online and any(h in rest for h in DEATH_HINTS):
            post({"content": f"💀 {body}"})


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
    if not WEBHOOK:
        sys.exit("MC_BRIDGE_WEBHOOK is not set")
    print(f"following {LOG}")
    for line in follow():
        try:
            handle(line)
        except Exception as e:  # one weird line must not kill the bridge
            print(f"line handler error: {e}", file=sys.stderr)


if __name__ == "__main__":
    main()
