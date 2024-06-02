import asyncio
from discord.ext import commands
import os
import discord

from cogwatch import watch

class Herupa(commands.Bot):
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
    client = Herupa()
    print(os.environ.get("DISCORD_TOKEN"))
    await client.start(os.environ.get("DISCORD_TOKEN"))

if __name__ == '__main__':
    asyncio.run(main())
