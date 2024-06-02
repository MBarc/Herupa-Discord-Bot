'''
Purpose: This command allows users to enter any text data (including URLs) and have it output a QR code.
'''

# Importing libraries specifically used for this command
import discord
import random
import io
import qrcode

from discord.ext import commands

class QR(commands.Cog):

    def __init__(self, client):
        self.client = client

    @commands.command(name="qrcode",
                      aliases=["qr"])
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

async def setup(client):
    await client.add_cog(QR(client))
