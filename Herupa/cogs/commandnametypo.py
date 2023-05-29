"""
Purpose:  If a user incorrectly types a command name, this code will figure out with command they were
trying to run and execute it
"""

# Importing libraries specifically used for this command
from discord.ext import commands
from difflib import SequenceMatcher

class OnCommandError(commands.Cog):

    def __init__(self, client):
        self.client = client

    @commands.Cog.listener()
    async def on_command_error(self, ctx, error):

        # Traditional errors are handled within their respective cog
        if not isinstance(error, commands.CommandNotFound):
            return

        # Defining some variables that we'll need later on
        message = ctx.message
        used_prefix = ctx.prefix
        used_command = message.content.split()[0][len(used_prefix):]  # getting the command, `!foo a b c` -> `foo`

        available_commands = [cmd.name for cmd in self.client.commands]
        matches = {  # command name: ratio
            cmd: SequenceMatcher(None, cmd, used_command).ratio()
            for cmd in available_commands
        }

        # Keeping track of all matches that are >= 75% match
        possibleMatches = {}
        for item in matches.items():

            # Defining the command name the match ratio
            commandName = item[0]
            matchRatio = item[1]

            # If the match ratio is a 75% match, it is a possible match
            if matchRatio >= 0.75:

                # Actually adding it to possibleMatches to keep track of
                possibleMatches[commandName] = matchRatio

        # If there are no possible matches
        if len(possibleMatches) == 0:
            # Providing some feedback to the user
            await ctx.channel.send("I don't know that command!")
            return

        # picking the match that has the highest match ratio
        command = max(possibleMatches.items(), key=lambda item: item[1])[0]

        try:
            arguments = message.content.split(" ", 1)[1]
        except IndexError:
            arguments = ""  # command didn't take any arguments

        new_content = f"{used_prefix}{command} {arguments}".strip()
        message.content = new_content  # overwriting the "original" message

        await self.client.process_commands(message)  # processing commands with the new, updated message

async def setup(client):
    await client.add_cog(OnCommandError(client))
