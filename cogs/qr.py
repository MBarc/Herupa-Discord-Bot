'''
Purpose: This command allows users to enter any text data (including URLs) and have it output a QR code.
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
import random
import io
import qrcode

class QR(commands.Cog):

    def __init__(self, client):
        self.client = client

    @commands.command()
    async def qr(self, ctx, *args):

        # Grabbing the data the user wants converted to a QR code
        data = " ".join(args) # converting args from list to string

        # Making the QR code
        img = qrcode.make(data)

        # Turning the QR code into a PNG and saving to memory
        output_buffer = io.BytesIO()
        
        img.save(output_buffer, "PNG")
        
        output_buffer.seek(0)  # going back to the beginning of the binary stream

        # Generating a random number for the filename; this fixes filename collisions within Discord
        number = random.randint(1000, 99999)

        # Sending to the same channel prompted
        await ctx.channel.send(file=discord.File(fp=output_buffer, filename=f"qr-{number}.png"))

    @qr.error
    async def qr_error(self, ctx, error):

        commandName = ctx.invoked_with
        error = str(error)

        herupaErrorLogChannel = self.client.get_channel(configFile()["herupaErrorLogChannel"])
        await herupaErrorLogChannel.send(f"{commandName.upper()} error: {error}")

def setup(client):
    client.add_cog(QR(client))
