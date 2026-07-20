#!/bin/bash
# Daily yt-dlp updater for the Herupa host.
#
# YouTube regularly changes things that break yt-dlp's extraction, and the
# fix only reaches us through yt-dlp releases. This keeps the host at most
# one day behind: update yt-dlp, and restart the bot ONLY when the version
# actually changed (yt-dlp is imported in-process, so a restart is the only
# way a new version takes effect). No release, no restart, no interrupted
# music sessions.
#
# Works in both deployment modes and picks automatically:
#   - containerized (a "herupa-bot" container exists): pip-update inside the
#     container, "docker restart" on change. The in-container update lives in
#     the container layer, so it survives restarts; recreating the container
#     from the image reverts to the image's version until the next 4:30am run
#     (rebuild the image now and then to re-baseline).
#   - host mode (systemd herupa-bot.service): pip --user update, systemctl
#     restart on change (needs passwordless sudo for systemctl).
#
# Installed by scripts/setup.sh to ~/bin/update-ytdlp.sh and run from the
# bot user's crontab at 4:30am local time:
#
#   30 4 * * * $HOME/bin/update-ytdlp.sh
#
# Logged to ~/ytdlp-update.log (last 200 lines) + journald tag "ytdlp-update".

set -u
LOG="$HOME/ytdlp-update.log"
ts() { date '+%F %T'; }

DOCKER="docker"
docker ps >/dev/null 2>&1 || DOCKER="sudo docker"

if $DOCKER ps --format '{{.Names}}' 2>/dev/null | grep -qx 'herupa-bot'; then
    # ---- containerized mode ----
    before=$($DOCKER exec herupa-bot python -m pip show yt-dlp 2>/dev/null | awk '/^Version:/{print $2}')
    $DOCKER exec herupa-bot python -m pip install --quiet -U yt-dlp >>"$LOG" 2>&1
    after=$($DOCKER exec herupa-bot python -m pip show yt-dlp 2>/dev/null | awk '/^Version:/{print $2}')
    if [ -n "$after" ] && [ "$before" != "$after" ]; then
        echo "$(ts) updated yt-dlp $before -> $after in container; restarting herupa-bot" >>"$LOG"
        logger -t ytdlp-update "updated yt-dlp $before -> $after in container; restarting herupa-bot"
        $DOCKER restart herupa-bot >>"$LOG" 2>&1
    else
        echo "$(ts) no change ($before, container)" >>"$LOG"
    fi
else
    # ---- host mode (systemd) ----
    before=$(python3 -m pip show yt-dlp 2>/dev/null | awk '/^Version:/{print $2}')
    python3 -m pip install --user --break-system-packages --quiet -U yt-dlp >>"$LOG" 2>&1 \
        || python3 -m pip install --user --quiet -U yt-dlp >>"$LOG" 2>&1
    after=$(python3 -m pip show yt-dlp 2>/dev/null | awk '/^Version:/{print $2}')
    if [ -n "$after" ] && [ "$before" != "$after" ]; then
        echo "$(ts) updated yt-dlp $before -> $after; restarting herupa-bot" >>"$LOG"
        logger -t ytdlp-update "updated yt-dlp $before -> $after; restarting herupa-bot"
        sudo systemctl restart herupa-bot.service
    else
        echo "$(ts) no change ($before, host)" >>"$LOG"
    fi
fi

tail -n 200 "$LOG" >"$LOG.tmp" && mv "$LOG.tmp" "$LOG"
