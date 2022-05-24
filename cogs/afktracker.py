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
import json
import datetime
from discord.ext import tasks

class AFKTracker(commands.Cog):

    def __init__(self, client):
        self.client = client
        self.databasePath = Path(configFile()["databases"]["afktracker"]).absolute()
        self.afktracker.start()

    @tasks.loop(seconds=60.0)
    async def afktracker(self):

        def write_json(data, filename=self.databasePath):
            with open(filename, 'w') as f:
                json.dump(data, f, indent=4)

        halfHourVoiceChannel = self.client.get_channel(configFile()["afk"]["thirty"])
        HourVoiceChannel = self.client.get_channel(configFile()["afk"]["sixty"])
        HourAndAHalfVoiceChannel = self.client.get_channel(configFile()["afk"]["ninety"])
        thatBitchDeadVoiceChannel = self.client.get_channel(configFile()["afk"]["dead"])
        afkNotes = self.client.get_channel(configFile()["afk"]["notes"])

        afkExceptionChannels = ["🍿Auditorium 1🍿"]

        # Getting the data from the afk database
        with open(self.databasePath) as json_file:
            data = json.load(json_file)

        for member in self.client.guilds[0].members:
            if member.status != discord.Status.idle:
                if data.get(member.name):
                    del data[member.name]
                    write_json(data)

            if member.status == discord.Status.idle and member.voice and not member.is_on_mobile():
                if member.voice.channel not in afkExceptionChannels:
                    if not data.get(member.name):
                        infoToAdd = {f"{member.name}":
                                        {
                                            "count": 0,
                                            "tracking": 1,
                                            "tracking_time": str(datetime.datetime.now())
                                        }
                                    }

                        data.update(infoToAdd)
                        write_json(data)
                        await afkNotes.send(f"Started keeping track of {member.mention}'s idleness.")

                    #Checking to see if the tracking time has expired so we can keep track of member's idleness or not
                    if data[member.name]['tracking'] == 0 and datetime.datetime.strptime(data[member.name]['tracking_time'], '%Y-%m-%d %H:%M:%S.%f') < datetime.datetime.now():
                        data[member.name]['tracking'] = 1
                        write_json(data)

                    #Only add to member's tracking if tracking is set to True
                    if data[member.name]['tracking'] == 1:
                        data[member.name]['count'] += 1
                        write_json(data)

                if data.get(member.name) and (data[member.name]['count'] >= 31 and data[member.name]['count'] < 61) and data[member.name]['tracking'] == 1:
                    if member.voice.channel != halfHourVoiceChannel:
                        await member.send(f"Hiya! Just wanted to let you know that I moved you to {halfHourVoiceChannel.name} because your status has been set to idle for over 30 minutes. " \
                                          "If you're not actually AFK you can either set your status back to \"online\" or use the \"$afkfalsealarm\" command in the 💘herupa💘 channel.")
                        await member.move_to(halfHourVoiceChannel)
                        await afkNotes.send(f'Moved {member.mention} to {member.voice.channel}.')

                if data.get(member.name) and (data[member.name]['count'] >= 61 and data[member.name]['count'] < 91) and data[member.name]['tracking'] == 1:
                    if member.voice.channel != HourVoiceChannel:
                        await member.move_to(HourVoiceChannel)
                        await afkNotes.send(f'Moved {member.mention} to {member.voice.channel}.')

                if data.get(member.name) and (data[member.name]['count'] >= 91 and data[member.name]['count'] < 121) and data[member.name]['tracking'] == 1:
                    if member.voice.channel != HourAndAHalfVoiceChannel: # id for 90 minutes voice channel
                        await member.move_to(HourAndAHalfVoiceChannel)
                        await afkNotes.send(f'Moved {member.mention} to {member.voice.channel}.')

                if data.get(member.name) and data[member.name]['count'] >= 121 and data[member.name]['tracking'] == 1:
                    if member.voice.channel != thatBitchDeadVoiceChannel:
                        await member.move_to(thatBitchDeadVoiceChannel)
                        await afkNotes.send(f'Moved {member.mention} to {member.voice.channel}.')

                #If the member is being tracked, send updates in the 'afk notes' channel
                if data[member.name]['tracking'] == 1:
                    await afkNotes.send(f'{member.name} is at {data[member.name]["count"]}')

    @afktracker.before_loop
    async def afktracker_before(self):
        await self.client.wait_until_ready()

    @afktracker.error
    async def afktracker_error(self, ctx, error):

        commandName = ctx.invoked_with
        error = str(error)

        herupaErrorLogChannel = self.client.get_channel(configFile()["herupaErrorLogChannel"])
        await herupaErrorLogChannel.send(f"{commandName.upper()} error: {error}")

def setup(client):
    client.add_cog(AFKTracker(client))