'''
Purpose: This file will contain several weather commands
$currentweather {city} {state} {country}: Get the current weather for the city specified
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
import requests

class Weather(commands.Cog):

    def __init__(self, client):
        self.client = client
        self.currentAPIKey = "2433c3ce0c6b61232c1bff153cf98cf0"
        self.forecastAPIKey = "0b8e3ebbcbb4885f5c6b733b5dd6ca9a"

    @commands.command()
    async def currentweather(self, ctx, city=None, state=None, country=None):

        url = f"http://api.openweathermap.org/data/2.5/weather?q={city},{state},{country}&appid={self.currentAPIKey}"

        r = requests.get(url)

        if "message" in r.json().keys():
            raise Exception("city not found")

        await ctx.channel.send(f"Currently, the weather in {city} is {r.json()['weather'][0]['description'].upper()}.")


    @currentweather.error
    async def currentweather_error(self, ctx, error):
        commandName = ctx.invoked_with
        error = str(error)

        if "city not found" in error:
            await ctx.channel.send("Hmmmmm couldn't find that city. Are you sure that it exists?")

        herupaErrorLogChannel = self.client.get_channel(configFile()["herupaErrorLogChannel"])
        await herupaErrorLogChannel.send(f"{commandName.upper()} error: {error}")

def setup(client):
    client.add_cog(Weather(client))

#api.openweathermap.org/data/2.5/weather?q=miami&appid=a0f3d0e12b1a25cb94e35c64d584e337