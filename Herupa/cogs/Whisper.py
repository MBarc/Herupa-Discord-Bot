from discord.ext import commands
from discord.utils import get
import discord

class Whisper(commands.Cog):

    def __init__(self, client):
        self.client = client
        self.default_admin_channel_name = "📜anonymous-reports📜"  # Default admin channel name

    @commands.Cog.listener()
    async def on_message(self, message):
        # Check if the message is a direct message (DM) to the bot and not sent by another bot
        if isinstance(message.channel, discord.DMChannel) and not message.author.bot:
            # Check if the message starts with the /whisper command
            if message.content.startswith("/whisper"):
                # Extract the whisper content by removing the command prefix
                whisper_content = message.content[len("/whisper "):].strip()

                # Check if the bot is part of any guilds (servers)
                if self.client.guilds:
                    # Get the first guild the bot is part of
                    guild = self.client.guilds[0]
                    # Find the admin channel by name in the guild
                    admin_channel = get(guild.text_channels, name=self.default_admin_channel_name)
                    # If the admin channel is found, send the whisper message to it
                    if admin_channel:
                        await admin_channel.send(f"An anonymous report has just come in:\n`{whisper_content}`")

                        await message.channel.send("Your report has been sent to the moderation team anonymously.")

async def setup(client):
    await client.add_cog(Whisper(client))
