# Herupa-Discord-Bot

Herupa is the backbone of the Chill Club Discord server. She is completely open source so feel free to make contributions to her code. Via Overhaul.py, any changes made to this Github repo will automatically get pushed to the live instance of Herupa.

### Setting up a new host

To stand Herupa up on a fresh Debian/Ubuntu-family Linux box (Raspberry Pi included), clone the repo and run the setup script as the user that should own the bot:

```sh
git clone https://github.com/MBarc/Herupa-Discord-Bot.git
cd Herupa-Discord-Bot
./scripts/setup.sh
```

Everything runs in Docker. The script installs Docker itself if needed, prompts for the Discord tokens and web password (written to `docker/.env`), builds Herupa's image (Python 3.11 with ffmpeg/libopus, all pip dependencies, and the `patches/voice_recv-dave` overlay that `$mock` needs), and starts the three containers: `herupa-bot`, `herupa-web` (port 8462), and `herupa-mongo`. It also installs a daily cron that keeps yt-dlp fresh inside the container.

The repo is bind-mounted into the containers, so editing a cog on the host hot-reloads live without a rebuild; rebuild the image only when `Herupa/requirements.txt` or `patches/` change. Data is not migrated: a fresh host starts with an empty database (levels, birthdays, tickets, and shop purchases start over). Bot logs: `docker logs -f herupa-bot`.

### Commands
avatarpic {@member}: Herupa will respond with the avatar pic of the member mentioned.\
clear {number}: Delete messages in bulk. If no number is specified, 5 messages are cleared.\
flip {heads or tails}: Have Herupa flip a coin. Specifying heads or tails is optional.\
herupa {name}: Herupa will join the voice channel and say the name specified.\
leave: Tell Herupa to leave the voice channel.\
lenny: Herupa responds with ( ͡° ͜ʖ ͡°)\
lennymoney: Herupa responds with [̲̅$̲̅(̲̅ ͡° ͜ʖ ͡°̲̅)̲̅$̲̅]\
migrate {channel name}: Move everyone in your current voice channel to another voice channel.\
rps: Play rock, paper, scissors against Herupa.\
github: Responds with a link to Herupa's Github page\
isslocation: Get the coordinates and map of where the International Space Station currently is.\
whoisinspace: Get the amount and names of astronauts currently in space.\
issprediction {country, region, city}: Get the amount and names of astronauts currently in space.\
addfavorite: Add member to your favorites. They must add you back in order to receive notifications of when each other joins a voice channel.\
removefavorite: Remove member from your favorites. They will no longer receive notifications of when you join a voice channel.\
myfavorites: See your list of favorites. This command works in either a public text channel or Herupa's DMs\
createroom {@members}: Create a private voice chat with the members specified. Specifying members is optional.\
add2room {@members}: Add members to private voice chat after the room has been created.\
kanye: Get a random Kanye West quote.\

### Background Tasks
AFK: Herupa automatically keeps track of how long members are AFK and moves them to the appropriate AFK voice channels.\
Newbie: Responsible for assigning the newbie role to new members and assigning the chillies role once members accept to our ToS.\
Clear Channel: Clears out certain text channels everyday at 6:30am EST.\
On Member Join: Greets new members with a unique greeting.\
Favorites: Sends a notification to all of your favorites (assuming you're their favorite too) letting them know that you connected to a voice chat.\
Destroy Room: Destroys a private voice chat if the last person leaves the channel. Redundant policy will delete the channel at 6:30am EST.\
