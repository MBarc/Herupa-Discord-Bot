#!/bin/bash
# Herupa fresh-host setup for Debian/Ubuntu-family Linux (incl. Raspberry Pi OS).
# Everything runs in Docker: the bot, the web control room, and MongoDB.
#
# Run as the user that should own the deployment (NOT root), from anywhere
# inside the cloned repo:
#
#   git clone https://github.com/MBarc/Herupa-Discord-Bot.git
#   cd Herupa-Discord-Bot
#   ./scripts/setup.sh
#
# What it does, in order:
#   1. installs Docker (official get.docker.com script) if missing, enables
#      it at boot, and adds this user to the docker group
#   2. prompts for secrets and writes docker/.env (existing values are kept;
#      the web password/secret auto-generate if left blank)
#   3. builds the Herupa image (python 3.11 + ffmpeg/libopus + pip deps +
#      the patches/voice_recv-dave overlay that $mock needs)
#   4. starts the stack: herupa-bot, herupa-web (port 8462), herupa-mongo
#      (data lives in a named Docker volume and starts EMPTY on a fresh
#      host - levels, tickets, birthdays etc. are not migrated)
#   5. installs the daily yt-dlp auto-updater cron (updates inside the
#      container, restarts it only when the version changed)
#
# Code deploys stay simple: the repo is bind-mounted into the containers,
# so editing a cog on the host hot-reloads live. Rebuild the image only
# when requirements.txt or patches/ change:
#   docker compose -f docker/docker-compose.yml build && docker compose -f docker/docker-compose.yml up -d
#
# Idempotent-ish: safe to re-run. Existing .env values, cron entries, the
# image, and the mongo volume are left alone.

set -euo pipefail

if [ "$(id -u)" -eq 0 ]; then
    echo "Run this as the user that should own Herupa (it will sudo when needed), not as root."
    exit 1
fi

REPO="$(cd "$(dirname "$0")/.." && pwd)"
ENVFILE="$REPO/docker/.env"
echo "==> Repo: $REPO"

# -------------------------------------------------------------- 1. docker ----
if ! command -v docker >/dev/null 2>&1; then
    echo "==> Installing Docker (get.docker.com)..."
    curl -fsSL https://get.docker.com | sudo sh
else
    echo "==> Docker already installed: $(docker --version)"
fi
sudo systemctl enable --now docker
sudo usermod -aG docker "$USER" || true
# docker group membership needs a new login; use sudo for docker below so
# this run works either way.
DOCKER="sudo docker"
if ! $DOCKER compose version >/dev/null 2>&1; then
    echo "Docker Compose v2 is missing (very old docker package?). Install the"
    echo "docker-compose-plugin package and re-run."
    exit 1
fi

# ------------------------------------------------------------- 2. secrets ----
echo "==> Secrets -> docker/.env (existing values are kept)"
touch "$ENVFILE"
chmod 600 "$ENVFILE"
add_env() {  # add_env KEY "prompt text" [generate|default:VALUE]
    local key="$1" prompt="$2" mode="${3:-}" val=""
    if grep -q "^${key}=..*" "$ENVFILE" 2>/dev/null; then
        echo "    $key already set, keeping it"
        return
    fi
    case "$mode" in
        default:*)
            val="${mode#default:}"
            echo "    $key defaulting to '$val'"
            ;;
        *)
            read -r -p "    $prompt: " val
            if [ -z "$val" ] && [ "$mode" = "generate" ]; then
                val=$(openssl rand -hex 32 2>/dev/null || head -c 32 /dev/urandom | od -An -tx1 | tr -d ' \n')
                echo "    (generated a random value)"
            fi
            ;;
    esac
    # replace an empty placeholder line if present, else append
    if grep -q "^${key}=" "$ENVFILE"; then
        sed -i "s|^${key}=.*|${key}=${val}|" "$ENVFILE"
    else
        echo "${key}=${val}" >>"$ENVFILE"
    fi
}
add_env DISCORD_TOKEN       "Herupa's Discord bot token (required)"
add_env MUSIC_BOT_TOKENS    "Hibiki music bot tokens, comma-separated (blank = no music)"
add_env BITLY_TOKEN         "Bitly token (blank = link shortening off)"
add_env HERUPA_WEB_PASSWORD "Web control-room admin password (blank = generate)" generate
add_env HERUPA_WEB_SECRET   "Web session-signing secret (blank = generate)" generate
add_env MONGO_USERNAME      "" "default:admin"
add_env MONGO_PASSWORD      "" "default:admin"
add_env TZ                  "" "default:America/New_York"

# --------------------------------------------------------- 3+4. build, up ----
echo "==> Building the Herupa image (first build takes a while on a Pi)..."
$DOCKER compose -f "$REPO/docker/docker-compose.yml" build
echo "==> Starting the stack..."
$DOCKER compose -f "$REPO/docker/docker-compose.yml" up -d

# ---------------------------------------------------------------- 5. cron ----
echo "==> Installing the daily yt-dlp auto-updater..."
mkdir -p "$HOME/bin"
cp "$REPO/scripts/update-ytdlp.sh" "$HOME/bin/update-ytdlp.sh"
chmod +x "$HOME/bin/update-ytdlp.sh"
(crontab -l 2>/dev/null | grep -v update-ytdlp; \
 echo "30 4 * * * $HOME/bin/update-ytdlp.sh") | crontab -

# ----------------------------------------------------------------- report ----
echo
echo "======================================================================"
echo "Done. Containers:"
$DOCKER compose -f "$REPO/docker/docker-compose.yml" ps --format '  {{.Name}}: {{.Status}}' 2>/dev/null \
    || $DOCKER ps --format '  {{.Names}}: {{.Status}}'
echo
echo "Web control room: http://$(hostname).local:8462 (password in docker/.env)"
echo "Bot logs:         docker logs -f herupa-bot"
echo
echo "Reminders for a fresh host:"
echo "  - Mongo starts EMPTY (named volume mongo_data): levels, birthdays,"
echo "    tickets, and shop purchases start over"
echo "  - code deploys = edit files in this repo; cogwatch hot-reloads them"
echo "    inside the container (no rebuild). Rebuild only for requirements/"
echo "    patch changes."
echo "  - the 4:30am cron updates yt-dlp inside the container and restarts"
echo "    it only when the version changed"
echo "  - log out and back in once so 'docker' works without sudo"
echo "======================================================================"
