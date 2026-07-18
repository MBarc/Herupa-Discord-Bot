#!/bin/bash
# Daily yt-dlp updater for the Herupa Pi.
#
# YouTube regularly changes things that break yt-dlp's extraction, and the
# fix only reaches us through yt-dlp releases. This keeps the Pi at most one
# day behind: update yt-dlp, and restart the bot ONLY when the version
# actually changed (the bot imports yt-dlp in-process, so a restart is the
# only way a new version takes effect). No release, no restart, no
# interrupted music sessions.
#
# Installed on the Pi at /home/michael/bin/update-ytdlp.sh and run by
# michael's crontab at 4:30am Eastern (the Pi's local timezone):
#
#   30 4 * * * /home/michael/bin/update-ytdlp.sh
#
# Requires passwordless sudo for systemctl (already set up for michael).
# Activity is logged to /home/michael/ytdlp-update.log (kept to the last
# 200 lines) and to journald under the tag "ytdlp-update".

set -u
LOG=/home/michael/ytdlp-update.log

before=$(python -m pip show yt-dlp 2>/dev/null | awk '/^Version:/{print $2}')
python -m pip install --user --break-system-packages --quiet -U yt-dlp >>"$LOG" 2>&1
after=$(python -m pip show yt-dlp 2>/dev/null | awk '/^Version:/{print $2}')

ts=$(date '+%F %T')
if [ -n "$after" ] && [ "$before" != "$after" ]; then
    echo "$ts updated yt-dlp $before -> $after; restarting herupa-bot" >>"$LOG"
    logger -t ytdlp-update "updated yt-dlp $before -> $after; restarting herupa-bot"
    sudo systemctl restart herupa-bot.service
else
    echo "$ts no change ($before)" >>"$LOG"
fi

tail -n 200 "$LOG" >"$LOG.tmp" && mv "$LOG.tmp" "$LOG"
