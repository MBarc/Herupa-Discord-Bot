#!/bin/bash
# Daily yt-dlp updater for the Herupa host.
#
# YouTube regularly changes things that break yt-dlp's extraction, and the
# fix only reaches us through yt-dlp releases. This keeps the host at most
# one day behind: update yt-dlp, and restart the bot ONLY when the version
# actually changed (the bot imports yt-dlp in-process, so a restart is the
# only way a new version takes effect). No release, no restart, no
# interrupted music sessions.
#
# Installed by scripts/setup.sh to ~/bin/update-ytdlp.sh and run from the
# bot user's crontab at 4:30am local time:
#
#   30 4 * * * $HOME/bin/update-ytdlp.sh
#
# Requires passwordless sudo for systemctl. Activity is logged to
# ~/ytdlp-update.log (kept to the last 200 lines) and to journald under
# the tag "ytdlp-update".

set -u
LOG="$HOME/ytdlp-update.log"

before=$(python3 -m pip show yt-dlp 2>/dev/null | awk '/^Version:/{print $2}')
python3 -m pip install --user --break-system-packages --quiet -U yt-dlp >>"$LOG" 2>&1 \
    || python3 -m pip install --user --quiet -U yt-dlp >>"$LOG" 2>&1
after=$(python3 -m pip show yt-dlp 2>/dev/null | awk '/^Version:/{print $2}')

ts=$(date '+%F %T')
if [ -n "$after" ] && [ "$before" != "$after" ]; then
    echo "$ts updated yt-dlp $before -> $after; restarting herupa-bot" >>"$LOG"
    logger -t ytdlp-update "updated yt-dlp $before -> $after; restarting herupa-bot"
    sudo systemctl restart herupa-bot.service
else
    echo "$ts no change ($before)" >>"$LOG"
fi

tail -n 200 "$LOG" >"$LOG.tmp" && mv "$LOG.tmp" "$LOG"
