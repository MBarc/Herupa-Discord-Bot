'''
Purpose: Change the Total Members channel name to correspond with the amount of members Chill Club has.
'''
# Importing custom config file and default libraries
import sys
import os
from pathlib import Path

configPath = Path(os.path.abspath(os.path.dirname(__file__))).parent.absolute()
sys.path.insert(0, configPath)
from config import configFile
from discord.ext import commands

# Importing libraries specifically used for this command
import requests
import random
import shlex
import discord
from discord.utils import get
from discord.ext import tasks
from datetime import datetime

class MovieTheater(commands.Cog):

    api_ip = "api-movietheater.chillclub.online"
    api_port = "5555"
    numberOfChoicesURL = f"http://{api_ip}:{api_port}/numberOfChoices"
    choiceURL = f"http://{api_ip}:{api_port}/movieChoice"
    pollmessageidURL = f"http://{api_ip}:{api_port}/pollmessageid"
    winningchoicesURL = f"http://{api_ip}:{api_port}/winningChoices"
    token = os.environ["TOKEN"]
    lobbyChannelID = 696213633297809478

    def __init__(self, client):
        self.client = client
        self.send_poll.start()
        self.count_poll.start()
        self.movie_notifier.start()

        self.emojiLetters = [
                "\N{REGIONAL INDICATOR SYMBOL LETTER A}",
                "\N{REGIONAL INDICATOR SYMBOL LETTER B}",
                "\N{REGIONAL INDICATOR SYMBOL LETTER C}",
                "\N{REGIONAL INDICATOR SYMBOL LETTER D}",
                "\N{REGIONAL INDICATOR SYMBOL LETTER E}", 
                "\N{REGIONAL INDICATOR SYMBOL LETTER F}",
                "\N{REGIONAL INDICATOR SYMBOL LETTER G}",
                "\N{REGIONAL INDICATOR SYMBOL LETTER H}",
                "\N{REGIONAL INDICATOR SYMBOL LETTER I}",
                "\N{REGIONAL INDICATOR SYMBOL LETTER J}",
                "\N{REGIONAL INDICATOR SYMBOL LETTER K}",
                "\N{REGIONAL INDICATOR SYMBOL LETTER L}",
                "\N{REGIONAL INDICATOR SYMBOL LETTER M}",
                "\N{REGIONAL INDICATOR SYMBOL LETTER N}",
                "\N{REGIONAL INDICATOR SYMBOL LETTER O}",
                "\N{REGIONAL INDICATOR SYMBOL LETTER P}",
                "\N{REGIONAL INDICATOR SYMBOL LETTER Q}",
                "\N{REGIONAL INDICATOR SYMBOL LETTER R}",
                "\N{REGIONAL INDICATOR SYMBOL LETTER S}",
                "\N{REGIONAL INDICATOR SYMBOL LETTER T}",
                "\N{REGIONAL INDICATOR SYMBOL LETTER U}",
                "\N{REGIONAL INDICATOR SYMBOL LETTER V}",
                "\N{REGIONAL INDICATOR SYMBOL LETTER W}",
                "\N{REGIONAL INDICATOR SYMBOL LETTER X}",
                "\N{REGIONAL INDICATOR SYMBOL LETTER Y}",
                "\N{REGIONAL INDICATOR SYMBOL LETTER Z}"
            ]

    def get_number_of_choices():
        """
        Performs a get request to return the number of choices
        """
        
        # Making the URL to get the information from
        full_url = f"{MovieTheater.numberOfChoicesURL}?token={MovieTheater.token}"

        # Getting the information and formatting it to json format
        r = requests.get(full_url).json()

        # Grabbing the piece of information we need
        number_of_choices = r["count"]

        # Returning the value
        return int(number_of_choices)

    def get_choice_by_number(choiceNumber):
        """
        Performs a get request to return choice given a number
        """

        full_url = f"{MovieTheater.choiceURL}?token={MovieTheater.token}&choiceNumber={choiceNumber}"

        print(full_url)

        choice = requests.get(full_url).json()[f"movie_choice_{choiceNumber}"][f"movie_choice_{choiceNumber}"]

        return choice[:-4]

    def get_title_and_choices(self, message):
        """
        Returns the title (as a string) and the choices (as a list) for the given poll/message
        """

        message = shlex.split(message, posix=False)
        message.remove(message[0])
        message = [s.replace('"', '') for s in message]

        title = message[0]
        message.remove(message[0])
        choices = message

        return title, choices

    def store_poll_id(message_id):
        """
        This will store the poll message ID in MongoDB so we may find it easily later on in the week.
        """

        full_url = f"{MovieTheater.pollmessageidURL}"

        response = requests.post(full_url, json={"token": MovieTheater.token, "id": message_id})

        print(response)

    def get_poll_id():
        """
        Getting the id of the poll that gets sent out on Mondays
        """

        full_url = f"{MovieTheater.pollmessageidURL}?token={MovieTheater.token}"

        r = requests.get(full_url).json()

        poll_id = r["id"]

        return poll_id

    def store_winning_choices(list_of_choices):
        """
        Storing the winning choices so that the choices may be seen by other processes
        """

        full_url = f"{MovieTheater.winningchoicesURL}"

        response = requests.post(full_url, json={"token": MovieTheater.token, "listOfChoices": f"{list_of_choices[0]},{list_of_choices[1]},{list_of_choices[2]}"})

    def movie_choice_renewer():
        """
        Rerolls the movie choices for the week.
        """

        # *-*-*-*-*-*-*-*-*-*-*-*-*-*-*-*-*-*-*-*-*-*-*-*-*
        # Step 1: Getting the number of how many movies we need to pick
        # *-*-*-*-*-*-*-*-*-*-*-*-*-*-*-*-*-*-*-*-*-*-*-*-*

        response = requests.get(MovieTheater.numberOfChoicesURL, json=MovieTheater.token)

        numberOfChoices = int(response.json()["count"])

        # *-*-*-*-*-*-*-*-*-*-*-*-*-*-*-*-*-*-*-*-*-*-*-*-*
        # Step 2: Get all the movies in the form of a list
        # *-*-*-*-*-*-*-*-*-*-*-*-*-*-*-*-*-*-*-*-*-*-*-*-*

        response = requests.get(MovieTheater.allMoviesURL, json=MovieTheater.token)

        allMovies = response.json()["all_movies_list"]

        # *-*-*-*-*-*-*-*-*-*-*-*-*-*-*-*-*-*-*-*-*-*-*-*-*-*-*-*-*-*-*-*-*-*-*
        # Step 3: Picking out the amount of movies specified in numberOfChoices
        # *-*-*-*-*-*-*-*-*-*-*-*-*-*-*-*-*-*-*-*-*-*-*-*-*-*-*-*-*-*-*-*-*-*-*

        new_options = []
        for i in range(0, numberOfChoices):
            new_options.append(random.choice(allMovies))

        # *-*-*-*-*-*-*-*-*-*-*-*-*-*-*-*-*-*-*-*-*-*-*-*-*-*-*-*-*-*-*
        # Step 3: Replacing the old movie choices with the new options
        # *-*-*-*-*-*-*-*-*-*-*-*-*-*-*-*-*-*-*-*-*-*-*-*-*-*-*-*-*-*-*

        for i in range(0, len(new_options)):

            url = f"{MovieTheater.choiceURL}/choiceNumber={i + 1}&choiceName={new_options[i]}" # +1 because of zero index

            response = requests.post(url, json=MovieTheater.token)

    @tasks.loop(minutes=1)
    async def send_poll(self):

        dayOfWeek = datetime.today().isoweekday()
        hour = datetime.utcnow().hour
        minute = datetime.utcnow().minute

        # If today is Monday and it is 12:00pm
        if dayOfWeek == 1 and hour == 16 and minute == 0:

            # Rerolling the movies for the week.
            MovieTheater.movie_choice_renewer()

            # Declaring the title of the embed
            title = "What movies do you want to see this weekend? Please cast up to 3 votes. First place will play on Friday, second place will play on Saturday, and third place will play on Sunday."

            # Getting the amount of choices we have available so we can iterate through all of them later
            number_of_choices = MovieTheater.get_number_of_choices()

            # Grabbing all movie choices and appending them to a list
            choices = []
            for i in range(0, number_of_choices):
                choices.append(MovieTheater.get_choice_by_number(i + 1))

            # There can only be a maximum of 26 choices because there are 26 letters in the alphabet
            if len(choices) > 26:
                raise Exception("Too many choices! Only a maximum of 26 choices are allowed.")

            # Creating the embed object, setting its title and color.
            embed = discord.Embed(title=title, colour=discord.Colour.from_rgb(255, 183, 197))

            # Adding each choice to the embed and assigning an emoji to the choice
            for i in range(len(choices)):
                embed.add_field(name=self.emojiLetters[i], value=choices[i], inline=False)

            # Getting the channel that we need to send
            channel = self.client.get_channel(MovieTheater.lobbyChannelID) # Currently, this ID is for 🗣the-lobby🗣

            # Keeping track of the message so we can add reactions to it
            message = await channel.send(embed=embed)

            # Adding the reactions to it
            for i in range(len(choices)):
                await message.add_reaction(self.emojiLetters[i])

            # Pinning the message so users can find it easier and it won't get deleted with $clear command
            await message.pin()

            # Storing the ID in MongoDB so we may easily reference it later this week when we need to count the votes
            MovieTheater.store_poll_id(message.id)

    @send_poll.before_loop
    async def send_poll_before(self):
        await self.client.wait_until_ready()

    @tasks.loop(minutes=1)
    async def count_poll(self):

        # Grabbing the current time info
        dayOfWeek = datetime.today().isoweekday()
        hour = datetime.utcnow().hour
        minute = datetime.utcnow().minute

        # If it is Wednesday at mightnight EST
        if dayOfWeek == 4 and hour == 4 and minute == 0:

            # Getting the channel that we need to send
            channel = self.client.get_channel(MovieTheater.lobbyChannelID) # Currently, this ID is for 🗣the-lobby🗣

            message = await channel.fetch_message(MovieTheater.get_poll_id())

            # Getting the count for each reaction and sorting it
            reaction_count = {}
            for reaction in message.reactions:

                reaction_count[reaction.emoji] =  reaction.count
            sorted_reaction_count = dict(sorted(reaction_count.items(), key=lambda item: item[1], reverse=True))

            # Organizing the results so we can easily get the information later on
            winning_choices = {
                "friday": {
                    "reaction": list(sorted_reaction_count.keys())[0],
                    "value": ""
                },
                "saturday": {
                    "reaction": list(sorted_reaction_count.keys())[1],
                    "value": ""
                },
                "sunday": {
                    "reaction": list(sorted_reaction_count.keys())[2],
                    "value": ""
                }
            }

            # Putting the reactions and values into a dict
            poll_content = message.embeds[0].to_dict()

            # For every option in the poll
            for option in poll_content["fields"]:

                # For every day that we'll play a movie
                for day in winning_choices:

                    # If the reaction in the value matches a winning choice reaction. . .
                    if option["name"] == winning_choices.get(day)["reaction"]:

                        # . . . map the option value to the winning choice value
                        winning_choices.get(day)["value"] = option["value"]

            # Compiling the message to send out the results of the poll
            winning_message = f"""
            **Movie Schedule For This Weekend**\nFriday -> {winning_choices.get("friday")["value"][:-4]}\nSaturday -> {winning_choices.get("saturday")["value"][:-4]}\nSunday -> {winning_choices.get("sunday")["value"][:-4]}\n\nAll movies will start at 10pm EST/EDT.
            """

            # Actually sending out the results
            await channel.send(winning_message)

            # Storing the results in our database
            movies = []
            for day in winning_choices:
                movies.append(winning_choices.get(day)["value"])
            MovieTheater.store_winning_choices(movies)

    @count_poll.before_loop
    async def count_poll_before(self):
        await self.client.wait_until_ready()

    @tasks.loop(hours=1)
    async def movie_notifier(self):

        # Grabbing the current time info
        dayOfWeek = datetime.today().isoweekday()
        hour = datetime.utcnow().hour

        guild = self.client.get_guild(645847490020638720)
        role = get(guild.roles, name='movie theater')

        # Getting the channel that we need to send the notifications in
        channel = self.client.get_channel(MovieTheater.lobbyChannelID) # Currently, this ID is for 🗣the-lobby🗣

        # If it's Wednesday at 12pm EST
        if dayOfWeek == 3 and hour == 16:

            message = f"<@&{role}> Don't forget to vote on the poll! It closes tonight at 12am EST! The poll is pinned if you need help finding it :)"

            channel.send(message)

        # If it's Friday, Saturday, or Sunday at 9pm
        if (dayOfWeek == 5 or dayOfWeek == 6 or dayOfWeek == 7) and hour == 1:

            message = f"<@&{role}> Don't forget! The movie will be playing at 10pm EST!"

            channel.send(message)

    @movie_notifier.before_loop
    async def movie_notifier_before(self):
        await self.client.wait_until_ready()


async def setup(client):
    await client.add_cog(MovieTheater(client))
