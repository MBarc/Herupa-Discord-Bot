# Importing custom config file and default libraries
import sys
import os
from pathlib import Path
configPath = Path(os.path.abspath(os.path.dirname(__file__))).parent.absolute()
sys.path.insert(0, configPath)
from config import configFile
from discord.ext import commands

# Importing libraries specifically used for this command
import json
import datetime

class OnMemberRemove(commands.Cog):

    def __init__(self, client):
        self.client = client
        self.databasePath = Path(configFile()["databases"]["favorites"]).absolute()

    @commands.Cog.listener()
    async def on_member_remove(self, member):

        checkList = ["Remove From All Databases", "Documentation"]  # list of things to do after someone has left the server

        for task in checkList:
            if task == "Remove From All Databases":

                # Function to add to JSON
                def write_json(data, filepath):
                    with open(filepath, 'w') as f:
                        json.dump(data, f, indent=4)

                # Removing {member}'s key/section in the database
                with open(self.databasePath) as json_file:
                    data = json.load(json_file)

                    try:
                        for name in data:
                            if name == str(member):
                                data.pop(name)  # error: dictionary changed size during iteration
                    except:
                        pass

                    write_json(data, self.databasePath)

                #Removing {member} from everyone's favorites list
                with open(self.databasePath) as json_file:
                    data = json.load(json_file)

                    for individual in data:
                        individualsFavorites = data[individual]
                        for favorite in individualsFavorites:
                            if favorite == str(member):
                                data[individual] = [favorite for favorite in individualsFavorites if favorite != str(member)]

                    write_json(data, self.databasePath)

            if task == "Documentation":

                # Declaring date for documentation channel
                currentDay = datetime.datetime.now()
                currentMonth = datetime.datetime.now()
                currentYear = datetime.datetime.now()

                documentationChat = self.client.get_channel(configFile()["onmemberjoin"]["documentation"])
                await documentationChat.sent(
                    f"{member.mention} has LEFT the server! The date is {currentMonth}/{currentDay}/{currentYear}.")



def setup(client):
    client.add_cog(OnMemberRemove(client))