#!/bin/bash
# Herupa fresh-host setup for Debian/Ubuntu-family Linux (incl. Raspberry Pi OS).
#
# Run as the user that should own the bot (NOT root), from anywhere inside
# the cloned repo:
#
#   git clone https://github.com/MBarc/Herupa-Discord-Bot.git
#   cd Herupa-Discord-Bot
#   ./scripts/setup.sh
#
# What it does, in order:
#   1. apt packages: python3/pip, ffmpeg, libopus (voice), docker (for Mongo)
#   2. pip packages from Herupa/requirements.txt (discord.py, the
#      voice-recv DAVE fork, yt-dlp, web UI deps, watchfiles pin)
#   3. applies patches/voice_recv-dave over the installed voice-recv
#      package (required for $mock; see that folder's README)
#   4. starts MongoDB in Docker (mongo:4.4.18 from docker/docker-compose.yml;
#      data starts EMPTY on a fresh host - levels, tickets, birthdays etc.
#      are not migrated by this script)
#   5. prompts for secrets and writes any missing ones to /etc/environment:
#      DISCORD_TOKEN, MUSIC_BOT_TOKENS, BITLY_TOKEN,
#      HERUPA_WEB_PASSWORD, HERUPA_WEB_SECRET (auto-generated if blank)
#   6. installs + starts systemd services herupa-bot and herupa-web
#      (paths and user filled in from wherever this repo lives)
#   7. installs the daily yt-dlp auto-updater cron (scripts/update-ytdlp.sh)
#
# Idempotent-ish: safe to re-run; existing /etc/environment keys, cron
# entries, and containers are left alone.

set -euo pipefail

if [ "$(id -u)" -eq 0 ]; then
    echo "Run this as the user that should own Herupa (it will sudo when needed), not as root."
    exit 1
fi

REPO="$(cd "$(dirname "$0")/.." && pwd)"
PY="$(command -v python3)"
echo "==> Repo: $REPO"
echo "==> Python: $PY ($($PY --version 2>&1))"

# ---------------------------------------------------------------- 1. apt ----
echo "==> Installing system packages (sudo)..."
sudo apt-get update -qq
sudo apt-get install -y -qq python3 python3-pip ffmpeg libopus0 curl ca-certificates
# Docker: only for MongoDB. Skip if some docker is already present.
if ! command -v docker >/dev/null 2>&1; then
    sudo apt-get install -y -qq docker.io
fi
sudo apt-get install -y -qq docker-compose-plugin 2>/dev/null \
    || sudo apt-get install -y -qq docker-compose 2>/dev/null \
    || true
sudo systemctl enable --now docker
# Let this user talk to docker (takes effect on next login; sg used below)
sudo usermod -aG docker "$USER" || true

# ---------------------------------------------------------------- 2. pip ----
echo "==> Installing Python packages (this can take a while on a Pi)..."
# --break-system-packages is needed on PEP 668 distros (Debian 12+) and
# unknown to older pip, hence the fallback.
$PY -m pip install --user --break-system-packages -U -r "$REPO/Herupa/requirements.txt" \
    || $PY -m pip install --user -U -r "$REPO/Herupa/requirements.txt"

# -------------------------------------------------------------- 3. patch ----
echo "==> Applying the voice-recv DAVE patch (needed for \$mock)..."
SITE=$($PY -c "import discord.ext.voice_recv, os; print(os.path.dirname(discord.ext.voice_recv.__file__))")
cp "$REPO/patches/voice_recv-dave/opus.py" "$REPO/patches/voice_recv-dave/router.py" "$SITE/"
echo "    patched $SITE"

# -------------------------------------------------------------- 4. mongo ----
echo "==> Starting MongoDB (Docker)..."
# Only the mongo service from the compose file; the "herupa" service in
# there is the obsolete dockerized-bot approach and is not used. Compose
# may warn about its unset env vars - harmless.
if ! sudo docker ps --format '{{.Names}}' | grep -q mongo; then
    cd "$REPO/docker"
    sudo docker compose up -d herupa_mongo 2>/dev/null \
        || sudo docker-compose up -d herupa_mongo
    cd "$REPO"
else
    echo "    a mongo container is already running, leaving it alone"
fi

# ------------------------------------------------------------ 5. secrets ----
echo "==> Secrets -> /etc/environment (existing keys are kept)"
add_env() {  # add_env KEY "prompt text" [generate]
    local key="$1" prompt="$2" gen="${3:-}" val=""
    if sudo grep -q "^${key}=" /etc/environment; then
        echo "    $key already set, keeping it"
        return
    fi
    read -r -p "    $prompt: " val
    if [ -z "$val" ] && [ "$gen" = "generate" ]; then
        val=$(openssl rand -hex 32 2>/dev/null || head -c 32 /dev/urandom | od -An -tx1 | tr -d ' \n')
        echo "    (generated a random value)"
    fi
    if [ -n "$val" ]; then
        echo "${key}=${val}" | sudo tee -a /etc/environment >/dev/null
    else
        echo "    (left unset - the related feature will be off until you add it)"
    fi
}
add_env DISCORD_TOKEN      "Herupa's Discord bot token (required)"
add_env MUSIC_BOT_TOKENS   "Hibiki music bot tokens, comma-separated (blank = no music)"
add_env BITLY_TOKEN        "Bitly token (blank = link shortening off)"
add_env HERUPA_WEB_PASSWORD "Web control-room admin password (blank = generate)" generate
add_env HERUPA_WEB_SECRET  "Web session-signing secret (blank = generate)" generate

# ------------------------------------------------------------ 6. systemd ----
echo "==> Installing systemd services..."
sudo tee /etc/systemd/system/herupa-bot.service >/dev/null <<UNIT
[Unit]
Description=Herupa Discord Bot
After=network-online.target docker.service
Wants=network-online.target

[Service]
Type=simple
User=$USER
WorkingDirectory=$REPO/Herupa
EnvironmentFile=/etc/environment
Environment=PYTHONUNBUFFERED=1
ExecStart=$PY bot.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
UNIT

sudo tee /etc/systemd/system/herupa-web.service >/dev/null <<UNIT
[Unit]
Description=Herupa Web UI
After=network-online.target

[Service]
User=$USER
WorkingDirectory=$REPO/web
EnvironmentFile=/etc/environment
Environment=PYTHONUNBUFFERED=1
ExecStart=$PY -m uvicorn app:app --host 0.0.0.0 --port 8462
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
UNIT

sudo systemctl daemon-reload
sudo systemctl enable --now herupa-bot.service herupa-web.service

# --------------------------------------------------------------- 7. cron ----
echo "==> Installing the daily yt-dlp auto-updater..."
mkdir -p "$HOME/bin"
cp "$REPO/scripts/update-ytdlp.sh" "$HOME/bin/update-ytdlp.sh"
chmod +x "$HOME/bin/update-ytdlp.sh"
(crontab -l 2>/dev/null | grep -v update-ytdlp; \
 echo "30 4 * * * $HOME/bin/update-ytdlp.sh") | crontab -

# ---------------------------------------------------------------- report ----
echo
echo "======================================================================"
echo "Done. Status:"
systemctl is-active herupa-bot.service  | sed 's/^/  herupa-bot:  /'
systemctl is-active herupa-web.service  | sed 's/^/  herupa-web:  /'
sudo docker ps --format '  mongo:       {{.Image}} ({{.Status}})' | grep mongo || echo "  mongo:       NOT RUNNING"
echo
echo "Web control room: http://$(hostname).local:8462 (password from /etc/environment)"
echo "Logs:             journalctl -u herupa-bot.service -f"
echo
echo "Reminders for a fresh host:"
echo "  - Mongo starts EMPTY: levels, birthdays, tickets, shop purchases are gone"
echo "  - the yt-dlp cron restarts the bot at 4:30am ONLY when yt-dlp updated"
echo "  - reapply patches/voice_recv-dave if discord-ext-voice-recv is ever reinstalled"
echo "  - passwordless sudo for 'systemctl restart herupa-bot.service' is needed"
echo "    for the cron restart (visudo if this user doesn't have it)"
echo "======================================================================"
