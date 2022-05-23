# Importing custom config file and default libraries
import sys
import os
from pathlib import Path
configPath = Path(os.path.abspath(os.path.dirname(__file__))).parent.absolute()
sys.path.insert(0, configPath)
from config import configFile
from discord.ext import commands

# Importing libraries specifically used for this command
import requests
import json
from geopy.geocoders import Nominatim

class ISSLocation(commands.Cog):

    def __init__(self, client):
        self.client = client

    @commands.command()
    async def isslocation(self, ctx):

        issURL = 'http://api.open-notify.org/iss-now.json'
        issAPI = requests.get(issURL)
        jsonData = json.loads(issAPI.text)

        issLat = jsonData['iss_position']['latitude']
        issLong = jsonData['iss_position']['longitude']

        geolocator = Nominatim(user_agent="Chill Club Discord ISS Locator")

        try:
            zoom = 9
            openStreetMapURL = f'https://www.openstreetmap.org/?edit_help=1#map={zoom}/{issLat}/{issLong}'
            location = geolocator.reverse(f'{issLat},{issLong}')
            await ctx.channel.send(f"The I.S.S. is above {location}. If you want to see exactly where this is, here's a map: <{openStreetMapURL}>")
        except:
            zoom = 4
            openStreetMapURL = f'https://www.openstreetmap.org/?edit_help=1#map={zoom}/{issLat}/{issLong}'
            await ctx.channel.send(f"The ISS is above a place that doesn't have an address. It's currently located at ({issLat}, {issLong}). If you want to see exactly where this is, here's a map: <{openStreetMapURL}>")

    @isslocation.error
    async def isslocation_error(self, ctx, error):

        commandName = ctx.invoked_with
        error = str(error)

        herupaErrorLogChannel = self.client.get_channel(configFile()["herupaErrorLogChannel"])
        await herupaErrorLogChannel.send(f"{commandName.upper()} error: {error}")

def setup(client):
    client.add_cog(ISSLocation(client))