'''
Purpose: Return a picture of the pokemon specified
'''
# Importing custom config file and default libraries

from discord.ext import commands

# Importing libraries specifically used for this command
import aiohttp

class Pokemon(commands.Cog):

    def __init__(self, client):
        self.client = client

    @commands.command(name="pokemon",
                      aliases=["pk"])
    async def pokemon(self, ctx, *args):

        # If the user didn't specify any or specified too many pokemon
        if len(args) != 1:
            raise Exception("incorrect amount of parameters")

        pokemon = args[0]

        url = f"https://pokeapi.co/api/v2/pokemon/{pokemon}"

        async with aiohttp.ClientSession() as session:
            async with session.get(url) as r:

                # If the json doesn't return anything
                if r.status == 404:
                    raise Exception("pokemon does not exist")

                data = await r.json()

        # Where the picture url is located within the json response
        picture = data["sprites"]["front_default"]

        # Actually sending the link to the channel ; (Discord will convert the link to a picture automatically)
        await ctx.channel.send(picture)


async def setup(client):
    await client.add_cog(Pokemon(client))
