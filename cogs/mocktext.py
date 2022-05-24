"""
Purpose: Process the user's input text and send it back as mock text
"""
# Importing custom config file and default libraries
import sys
import os
from pathlib import Path
configPath = Path(os.path.abspath(os.path.dirname(__file__))).parent.absolute()
sys.path.insert(0, configPath)
from config import configFile
from discord.ext import commands

# Importing libraries specifically used for this command
import random

class MockText(commands.Cog):

    def __init__(self, client):
        self.client = client

    @commands.command()
    async def mocktext(self, ctx):

        # Grabbing the text that the user wants to convert into mock text
        message = ctx.message.content.split()[1:len(ctx.message.content.split())]  # removing the command
        message = ' '.join([str(word) for word in message])  # converting from array to string

        # Declaring the mock_text now so we can add to it later
        mock_text = ""

        # Iterating through each letter in our message
        for letter in message:

            # If {random percentage} is greater than 50%
            if random.random() > .50:  # 50% change of a letter because uppercase or lowercase
                mock_text += letter.upper()
            else:
                mock_text += letter.lower()

        # Actually send the mock text back
        await ctx.channel.send(mock_text)

        # Deleting the message that triggered this command to make it look like Herupa mocked randomly.
        await ctx.message.delete()

    @mocktext.error
    async def mocktext_error(self, ctx, error):
        commandName = ctx.invoked_with
        error = str(error)

        herupaErrorLogChannel = self.client.get_channel(configFile()["herupaErrorLogChannel"])
        await herupaErrorLogChannel.send(f"{commandName.upper()} error: {error}")

def setup(client):
    client.add_cog(MockText(client))