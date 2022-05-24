# Importing custom config file and default libraries
import sys
import os
from pathlib import Path
configPath = Path(os.path.abspath(os.path.dirname(__file__))).parent.absolute()
sys.path.insert(0, configPath)
from config import configFile
from discord.ext import commands

# Importing libraries specifically used for this command
import discord
import random
import datetime

class OnMemberJoin(commands.Cog):

    def __init__(self, client):
        self.client = client

    @commands.Cog.listener()
    async def on_member_join(self, member):

        # Assigning the appropriate role to the member
        chilliesRole = discord.utils.get(member.guild.roles, name="chillies")
        servantsRole = discord.utils.get(member.guild.roles, name="servants")

        if member.bot:
            await member.add_roles(servantsRole)
        else:
            await member.add_roles(chilliesRole)

        # Sending a custom welcome message in general chat
        messages = [
            f'Welcome {member.mention} to the Chill Club! If you were my kid, I would raise you right.',
            f'Welcome {member.mention} to the Chill Club! Please sanitize your hands on the way in.',
            f'Welcome {member.mention} to the Chill Club! Please sanitize your hands on the way in.',
            f"Welcome {member.mention} to the Chill Club! Sorry for the smell, it's @Twinkie.",
            f"Welcome {member.mention} to the Chill Club! If you need me, I'll be over there.",
            f'Welcome {member.mention} to the Chill Club! Please find your seat, the show is about to begin!',
            f"Welcome {member.mention} to the Chill Club! I love what you've done with your hair!",
            f"Welcome {member.mention} to the Chill Club! We've been waiting for you...",
            f'Hi {member.mention}, welcome to the Chill Club! Remember to rate us 5 stars on Yelp!',
            f"Welcome {member.mention} to the Chill Club! Please take a look at the menu and let me know when you're ready to order.",
            f"Hi {member.mention}, welcome to the Chill Club! Please stop looking at me like that, I'm taken...",
            f"Hi {member.mention}, welcome to the Chill Club! My mom wants to know if your mom can pick us up from the mall on Friday.",
            f"Welcome {member.mention} to the Chill Club! As the great Ghandi probably once said, Hi!",
            f"Hi {member.mention}, welcome to the Chill Club! My mom always said not to talk to strangers, but for you I'll make an exception!",
            f"Hi {member.mention}, welcome to the Chill Club! The way you just joined this server was so hot. :stuck_out_tongue_closed_eyes:",
            f"Welcome {member.mention} to the Kill Club! Oops hehe, typo :wink:  Welcome to the Chill Club!",
            f"Hi {member.mention}, Welcome to Chill Club! I like your vibe.",
            f"Hi {member.mention}! Thanks for joining the Care Bears Fan Club! Oh, sorry, wrong server. Welcome to Chill Club!",
            f"Welcome {member.mention} to the Chill Club! Let me know if you get lost! I can't help cause I'm a bot but you can let me know.",
            f"Welcome {member.mention}! Chill Club is very exclusive, Brad Pitt got his start here.",
            f"Welcome {member.mention} to the Chill Club! Just met them but they're kinda cute :kissing_closed_eyes:",
            f"Welcome {member.mention} to the Chill Club! Bathrooms are to the left.",
            f"Welcome {member.mention} to the Chill Club! We love you already! Not a joke, we love you. Please call us back.",
            f"Everyone, welcome {member.mention} to the Chill Club! They’re a really good kisser...or so I’ve been told.",
            f"Welcome {member.mention} to the Chill Club! I don’t usually like fedoras but you’re rocking it.",
            f'Welcome {member.mention} to the Chill Club! If you were my kid, I would raise you right.',
            f"Hey {member.mention}, welcome to the Chill Club! Someone said you had a gift for me so I’ll take that now, thanks!",
            f'Welcome {member.mention}, to the Chill Club! We’ve been told you are “chill” so hopefully you meet those expectations :)',
            f"Hey {member.mention}, welcome to the Chill Club! This server looks good on you!",
            f"Welcome to the Chill Club, {member.mention}! The bathroom is down the hall, first door on your left.",
            f"Hey {member.mention}, welcome to the Chill Club! I had a dream last night and you were in it.",
            f"Welcome to the Chill Club, {member.mention}! You got the stuff?",
            f"Welcome {member.mention}, to the Chill Club! They’ve prepared a really good knock knock joke! Go ahead, {member.mention}.",
            f'Welcome {member.mention}, to the Chill Club! Studies show they are really flipping cool.',
            f'Hi {member.mention}! I think I matched with you on tinder?',
            f'Wait a minute. . .I think {member.mention} is my mom? Welcome mommy!']

        if not member.bot:
            generalChat = self.client.get_channel(configFile()["onmemberjoin"]["general-chat"])
            await generalChat.send(random.choice(messages))

            # Declaring date for documentation channel
            currentDay = datetime.datetime.now()
            currentMonth = datetime.datetime.now()
            currentYear = datetime.datetime.now()

            documentationChat = self.client.get_channel(configFile()["onmemberjoin"]["documentation"])
            await documentationChat.sent(f"{member.mention} has JOINED the server! The date is {currentMonth}/{currentDay}/{currentYear}.")

def setup(client):
    client.add_cog(OnMemberJoin(client))
