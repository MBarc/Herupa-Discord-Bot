import asyncio
from discord.ext import commands
import os
import discord

from cogwatch import watch

class Herupa(commands.Bot):
    def __init__(self):

        # Intents.all() already enables every intent, including members and presences.
        intents = discord.Intents.all()

        super().__init__(command_prefix='$', intents=intents, help_command=None)

    @watch(path='cogs', preload=True)
    async def on_ready(self):

        await self.change_presence(activity=discord.Activity(type=discord.ActivityType.listening, name="$help"))

        print('Herupa is ready to go!')

async def main():
    token = os.environ.get("DISCORD_TOKEN")
    if not token:
        raise RuntimeError("DISCORD_TOKEN is not set in the environment.")
    client = Herupa()
    await client.start(token)

if __name__ == '__main__':
    asyncio.run(main())
