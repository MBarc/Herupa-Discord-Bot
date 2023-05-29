'''
This command ties in with the add2room  and createroom command.

Purpose: If someone is the last person to leave a voice channel under the Rooms category, the channel is destroyed.
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
import discord
import asyncio

class DestroyRoom(commands.Cog):

    def __init__(self, client):
        self.client = client

    @commands.Cog.listener()
    async def on_voice_state_update(self, member, before, after):
        # Grabbing the default category where all rooms are located/created
        category = discord.utils.get(self.client.guilds[0].categories, id=configFile()["all-categories"]["rooms"]).id

        #If the member left a voice channel within the default category
        try:
            if before.channel.category_id == category:

                #If the channel the member left is now empty
                if not before.channel.members:

                    # Deleting the voice channel
                    await before.channel.delete(reason=f'Last person ({member.name}#{member.discriminator})left the room so it was deleted.')

                    # Deleting things back to back without waiting causes weird behaviors
                    await asyncio.sleep(3)

                    # Grabbing the text channel
                    textChannel = discord.utils.get(self.client.get_all_channels(), name=f"{member.name.lower().replace(' ', '-')}-tc")

                    # Deleting the text channel
                    await textChannel.delete(reason=f'Last person ({member.name}#{member.discriminator}) left the connect voice chat so it was deleted.')
        except:
            pass

async def setup(client):
    await client.add_cog(DestroyRoom(client))
