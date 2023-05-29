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
from discord.ext import commands, tasks

class MemberCountTracker(commands.Cog):

    def __init__(self, client):
        self.client = client
        self.membercounttracker.start()

    @tasks.loop(seconds=60)
    async def membercounttracker(self):

        # Declaring the IDs that we're going to need
        chillClubID = 645847490020638720
        trackerChannelID = 995649638080184421
        
        # Using the IDs to define the server and channel
        guild = self.client.get_guild(chillClubID)
        trackerChannel = self.client.get_channel(trackerChannelID)

        # Actually getting the count of all the members
        member_count = len([m for m in guild.members if not m.bot]) # doesn't include bots

        await trackerChannel.edit(name=f"Total Members: {member_count}")

    @membercounttracker.before_loop
    async def membercounttracker_before(self):
        await self.client.wait_until_ready()

async def setup(client):
    await client.add_cog(MemberCountTracker(client))
