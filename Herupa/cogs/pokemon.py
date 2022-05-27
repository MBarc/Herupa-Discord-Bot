'''
Purpose: Return a picture of the pokemon specified
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
import json

class Pokemon(commands.Cog):

    def __init__(self, client):
        self.client = client

    @commands.command()
    async def pokemon(self, ctx, *args):

        # If the user didn't specify any or specified too many pokemon
        if len(args) != 1:
            raise Exception("incorrect amount of parameters")

        pokemon = args[0]

        url = f"https://pokeapi.co/api/v2/pokemon/{pokemon}"

        r = requests.get(url)

        # If the json doesn't return anything
        if r.status_code == 404:
            raise Exception("pokemon does not exist")

        # Where the picture url is located within the json response
        jsonLocation = json.dumps(r.json()["sprites"]["front_default"])

        # Getting rid of the quotes; reformatting
        picture = jsonLocation[1:len(jsonLocation)-1]

        # Actually sending the link to the channel ; (Discord will convert the link to a picture automatically)
        await ctx.channel.send(picture)


    @pokemon.error
    async def pokemon_error(self, ctx, error):
        commandName = ctx.invoked_with
        error = str(error)

        if "incorrect amount of parameters" in error:
            await ctx.channel.send("You either didn't specify or specified too many pokemon. Example -> $pokemon {pokemon name}")

        if "pokemon does not exist" in error:
            await ctx.channel.send("That pokemon doesn't exist! Feel free to try again.")

        herupaErrorLogChannel = self.client.get_channel(configFile()["herupaErrorLogChannel"])
        await herupaErrorLogChannel.send(f"{commandName.upper()} error: {error}")

def setup(client):
    client.add_cog(Pokemon(client))