'''
Purpose: To test is Herupa is up and running. Herupa will respond with "pong!"
'''
# Importing custom config file and default libraries
from discord.ext import commands

# Importing libraries specifically used for this command
import requests
import validators

class URLShortener(commands.Cog):

    def __init__(self, client):
        self.client = client

    @commands.command(name="urlshorter",
                      aliases=["url"])
    async def urlshortener(self, ctx, arg):

        # Checking to see if arg is a valid URL
        valid_url = validators.url(arg)
        if valid_url != True:
            raise Exception("url not valid")

        # All the stuff needed to make a request to bitly
        api_url = "https://api-ssl.bitly.com"
        access_token = "a41d0ce35a71bc4d65fd33b4a4d6502de5ef73cd"
        endpoint = f"/v4/shorten"

        headers = {"Authorization": f"Bearer {access_token}",
                   "Content-Type": "application/json"}

        payload = {"long_url": arg}

        # Actually sending the post request
        r = requests.post(api_url + endpoint, headers=headers, json=payload)

        await ctx.channel.send(f"Here's your shortened link: {r.json()['link']}")

async def setup(client):
    await client.add_cog(URLShortener(client))