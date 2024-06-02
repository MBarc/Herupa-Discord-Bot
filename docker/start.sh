#!/bin/sh

# Start cron and push it to the back so we can start the second command
#exec crond -f &

# Start the discord bot
cd herupa/Herupa
crond && python ./bot.py &

/bin/sh
