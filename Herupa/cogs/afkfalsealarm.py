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
import datetime
import json

class AFKFalseAlarm(commands.Cog):

    def __init__(self, client):
        self.client = client
        self.databasePath = 'C:\\Users\\micha\\Documents\\Chill Club Discord\\Herupa\\cogs\\databases\\afktracker.json'

    @commands.command()
    async def afkfalsealarm(self, ctx, *args):

        # if more than 1 argument, throw error
        if len(args) != 1:
            raise Exception('MORE OR LESS THAN ONE ARGUMENT GIVEN')

        # if argument is not INT, throw error
        hours = int(args[0]) # throws "ValueError: invalid literal for int() with base 10:"

        if hours == 0:
            raise Exception('ARGUMENT CANNOT BE 0 HOURS')

        #Args (hours) cannot be more than a week
        if hours > 168: # 24 hours * 7 days/week = 168 hours
            raise Exception('MORE THAN 168 HOURS')

        def write_json(data, filename=self.databasePath):
            with open(filename, 'w') as f:
                json.dump(data, f, indent=4)

        author = ctx.message.author.name

        # Getting the data from the favorites database
        with open(self.databasePath) as json_file:
            data = json.load(json_file)

            # Defining when the afktracker should start tracking the member again
            currentTime = datetime.datetime.now()
            hoursToAdd = datetime.timedelta(hours=hours)

            # Adding the author to the dictionary to keep track of
            data.update({author:{}})

            # Defining when the non-tracking should expire
            data[author]['tracking_time'] = str(currentTime + hoursToAdd)

            # Turning off tracking
            data[author]['tracking'] = 0

            # Writing the changes to the database
            write_json(data)

            # Sending out a gramatically correctly indicator back to the user
            if hours == 1:
                await ctx.message.channel.send("Okay! I won't keep track of you being AFK for the next hour.")
            else:
                await ctx.message.channel.send(f"Okay! I won't keep track of you being AFK for the next {hours} hours.")

    @afkfalsealarm.error
    async def afkfalsealarm_error(self, ctx, error):

        commandName = ctx.invoked_with
        error = str(error)

        if 'MORE OR LESS THAN ONE ARGUMENT GIVEN' in error:
            await ctx.channel.send("You can only input one value at a time for that command.")

        if 'ARGUMENT CANNOT BE 0 HOURS' in error:
            await ctx.channel.send("Hey, your input cannot be 0. I feel like you're wasting my time.")

        if 'MORE THAN 168 HOURS' in error:
            await ctx.channel.send("You can't put more than a week's worth of hours (168 hours).")

        herupaErrorLogChannel = self.client.get_channel(configFile()["herupaErrorLogChannel"])
        await herupaErrorLogChannel.send(f"{commandName.upper()} error: {error}")

async def setup(client):
    await client.add_cog(AFKFalseAlarm(client))
