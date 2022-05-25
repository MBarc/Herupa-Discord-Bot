# Importing custom config file and default libraries
from http import client
import sys
import os
from pathlib import Path
configPath = Path(Path(os.getcwd()))
sys.path.insert(0, configPath)
from config import configFile

import asyncio
from discord.ext import commands
from cogwatch import watch
import os
import discord

class ExampleBot(commands.Bot):
    def __init__(self):

        intents = discord.Intents.all()
        intents.members = True
        intents.presences = True

        super().__init__(command_prefix='$', intents=intents, help_command=None)

    @watch(path='cogs', preload=True)
    async def on_ready(self):

        await self.change_presence(activity=discord.Activity(type=discord.ActivityType.listening, name="$help"))

        print('Herupa is ready to go!')

async def main():
    client = ExampleBot()
    await client.start("NjQzNTYyODUyNzQxMDIxNzA3.XcnSnA.15haycC_onb1kRP6CSjy3ZtcswU")

if __name__ == '__main__':
    asyncio.run(main())