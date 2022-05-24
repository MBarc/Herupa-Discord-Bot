import discord
import datetime
from datetime import datetime as dt
from discord.ext import commands, tasks

class MovieAnnouncement(commands.Cog):

    def __init__(self, client):
        self.client = client
        self.movieannouncement.start()

    @tasks.loop(seconds=60)
    async def movieannouncement(self):

        def numberToDayofWeek(today):
            if today == 0:
                return "Monday"
            if today == 1:
                return "Tuesday"
            if today == 2:
                return "Wednesday"
            if today == 3:
                return "Thursday"
            if today == 4:
                return "Friday"
            if today == 5:
                return "Saturday"
            if today == 6:
                return "Sunday"

        dayOfWeek = numberToDayofWeek(datetime.datetime.today().weekday())
        currentHour = int(datetime.datetime.now().hour)

        #change to friday and 12
        if dayOfWeek == 'Sunday' and currentHour == 22:

            currentDay = dt.utcnow()  # should be friday
            lastMonday = currentDay - datetime.timedelta(days=currentDay.weekday())
            lastMonday = dt.utcnow()

            generalChat = discord.utils.get(self.client.guilds[0].channels, name="🤠general-chat🤠")


            #Filtering out irrelevant messages
            messages = [message async for message in generalChat.history(limit=300) if message.author.name == 'Simple Poll'] # looks back 300 messages to grab messages by Simple Polls
            messages = [message for message in messages if (message.created_at.day == lastMonday.day) and (message.created_at.strftime('%V') == lastMonday.strftime('%V'))] # filters out any messages no created on last monday
            #messages = [message for message in messages if (int(message.created_at.strftime('%H')) == currentHour + 4)] # filters out any messages no sent between 12pm-12:59pm; +4 because Discord uses UTC time.
            messages = [message for message in messages if ('What movies would you like to see this weekend? Please pick 3 options only.' in message.content)] # filters out any messages that doesn't have "What movies would you like to see this weekend? Please pick 3 options only."

            for i in messages:
                options = i.embeds[0].description.split('\n')
                print(options)
                tracker = {}  # keeps track of all options with their count/placement
                for option in options:
                    for reaction in i.reactions:
                        if str(reaction) in option:
                            tracker.update({f"{reaction}": int(reaction.count)})

                #Getting first, second, and third place reactions
                for i in range (0, 3):
                    if i == 0:
                        print('entered first if statement')
                        firstPlace = max(tracker, key=tracker.get)
                        del tracker[firstPlace]

                    if i == 1:
                        secondPlace = max(tracker, key=tracker.get)
                        del tracker[secondPlace]

                    if i == 2:
                        thirdPlace = max(tracker, key=tracker.get)
                        del tracker[thirdPlace]

                # Comparing reactions to options to see which option won
                for option in options:
                    if firstPlace in option:
                        firstPlace = option

                    if secondPlace in option:
                        secondPlace = option

                    if thirdPlace in option:
                        thirdPlace = option

                #Sending results to general chat
                generalChat = discord.utils.get(self.client.guild.categories, name="🤠general-chat🤠")
                await generalChat.send(f"This weekend we will be playing the following movies: \n Friday: {firstPlace[1:]} \n Saturday: {secondPlace[1:]} \n Sunday: {thirdPlace[1:]}")

    @movieannouncement.before_loop
    async def movieannouncement_before(self):
        await self.client.wait_until_ready()

def setup(client):
    client.add_cog(MovieAnnouncement(client))