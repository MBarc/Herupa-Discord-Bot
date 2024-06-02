import discord
from discord.ext import commands
from discord.utils import get
from datetime import datetime

class ErrorHandler(commands.Cog):

    def __init__(self, client):
        self.client = client
        self.errorLogChannel = "🚨herupa-error-log🚨"

    async def error_message_formatter(self, ctx, title: str, description: str, author: str):
        """
        Formats and sends an error message to a designated error log channel.

        Parameters:
        - ctx (commands.Context): The context in which the error occurred, providing access to the guild and author information.
        - title (str): The title of the error message.
        - description (str): A detailed description of the error.
        - author (str): The name of the author associated with the error message.
        """

        # Initializing the Discord embed message
        message = discord.Embed(title=title, description=description)
        
        # Setting the author and their profile picture
        message.set_author(name=author, icon_url=ctx.author.display_avatar)

        # Getting the date and time for logging purposes
        time = datetime.now().strftime("%m/%d/%Y %H:%M:%S")

        # Setting the footer with the time the error was generated
        message.set_footer(text=f"Generated on {time} EST")

        # Getting the channel we're sending the error to
        errorLogChannel = get(ctx.guild.channels, name=self.errorLogChannel)

        # Actually sending the error log to the error log channel
        await errorLogChannel.send(embed=message)


    @commands.Cog.listener()
    async def on_command_error(self, ctx, error):

        # Sending the error to the error log channel for review if needed
        await self.error_message_formatter(ctx=ctx, title=str(error).upper(), description=ctx.message.content, author=ctx.message.author)

        if isinstance(error, commands.CommandNotFound):
            """
            Note: This is being handled under the "CommandNameTypo.py" cog. So here we just return.
            """
            return
        
        if isinstance(error, commands.MissingRequiredArgument):
            await ctx.send("Missing required argument. Please check your command and try again.")
        elif isinstance(error, commands.CommandInvokeError):
            await ctx.send("There was an error while executing the command. Please try again.")
        else:
            await ctx.send("An unexpected error occurred. Please try again later. Please let Money Shark know.")


async def setup(client):
    await client.add_cog(ErrorHandler(client))
