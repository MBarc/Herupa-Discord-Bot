# Importing custom config file and default libraries
import sys
import os
from pathlib import Path
configPath = Path(os.path.abspath(os.path.dirname(__file__))).parent.absolute()
sys.path.insert(0, configPath)
from config import configFile
from discord.ext import commands

# Importing libraries specifically used for this command
import datetime
import json
from discord.utils import get

class Kick(commands.Cog):

    def __init__(self, client):
        self.client = client
        self.databasePath = Path(configFile()["databases"]["adminkicked"]).absolute()

    @commands.command()
    async def kick(self, ctx):

        # function to add to JSON
        def write_json(data, filename=self.databasePath):
            with open(filename, 'w') as f:
                json.dump(data, f, indent=4)

        mentions = ctx.message.mentions
        if len(mentions) != 1:
            raise Exception('KICK Command Error: Incorrect amount of mentions used.')

        owner = ctx.message.author.guild.owner
        author = ctx.message.author
        authorID = f'{author.name}#{author.discriminator}'

        deputyRole = get(ctx.message.guild.roles, name='deputy')
        permissionGranted =  lambda member: True if deputyRole in member.roles else False

        if not permissionGranted:
            raise Exception('KICK Permission Denied: User does not have permission to kick members.')

        #If author is not the guild owner and they have the deputy role
        if author != owner and permissionGranted:

            # Getting the adminkicked database information
            with open(self.databasePath) as json_file:
                data = json.load(json_file)

            # If author does not have a key in the database
            if not authorID in data:
                data.update({authorID: str(datetime.datetime.now())})
                write_json(data)
                await mentions[0].kick(reason=f"Kicked by {author}. This is their first recorded kick.")
            else:
                lastKicked = datetime.datetime.strptime(data[authorID], '%Y-%m-%d %H:%M:%S.%f')
                currentKick = datetime.datetime.now()

                kickGranted = lambda previous, current: True if (current - previous).seconds > (60 * 60) else False #Allows for 1 kick per hour by the author

                if kickGranted(lastKicked, currentKick):
                    data.update({authorID: str(datetime.datetime.now())})
                    write_json(data)
                    await mentions[0].kick(reason=f"Kicked by {author}.")
                else:
                    await ctx.channel.send('Request could not be completed. You can only kick 1 person an hour. If you need to kick more people, contact another Deputy or the Head Chill.')
        else: # if the author is the owner
            await mentions[0].kick(reason=f"Kicked by {author}.")


    @kick.error
    async def kick_error(self, ctx, error):

        commandName = ctx.invoked_with
        error = str(error)

        if 'KICK Command Error' in error:
            await ctx.channel.send(f"You have to mention only 1 member in order to use this command.")
        if 'KICK Permission Denied' in error:
            await ctx.channel.send(f"You need to be deputy role or higher in order to use this command.")

        herupaErrorLogChannel = self.client.get_channel(configFile()["herupaErrorLogChannel"])
        await herupaErrorLogChannel.send(f"{commandName.upper()} error: {error}")


async def setup(client):
    await client.add_cog(Kick(client))
