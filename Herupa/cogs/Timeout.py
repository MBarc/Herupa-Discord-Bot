from discord.ext import commands
from discord.utils import get
import discord
from datetime import timedelta

class Timeout(commands.Cog):

    def __init__(self, client):
        self.client = client
        # NOTE: the role is "deputy" (singular). The old "deputies" value meant
        # deputies could never actually use this command.
        self.allowed_roles = ["deputy", "sheriff", "head chill"]
        self.unrestricted_roles = ["sheriff", "head chill"]   # no duration cap
        self.deputy_timeout_cap_minutes = 60
        self.log_channel_name = "👮law-chat👮"

    @commands.command(name="timeout", aliases=["to"])
    async def timeout(self, ctx, member: discord.Member, duration: int, *, reason: str):
        """
        Timeout a member for a specified duration with a reason.
        """

        # Check if the author has one of the allowed roles
        if not any(role.name.lower() in self.allowed_roles for role in ctx.author.roles):
            await ctx.send("You do not have the required role to use this command.")
            return

        # Deputies are capped; sheriff / head chill are not.
        is_unrestricted = any(role.name.lower() in self.unrestricted_roles for role in ctx.author.roles)
        if not is_unrestricted and duration > self.deputy_timeout_cap_minutes:
            await ctx.send(
                f"Deputies can time a member out for at most {self.deputy_timeout_cap_minutes} "
                "minutes. A Sheriff must apply a longer timeout."
            )
            return

        try:
            # Ensure a reason is provided
            if not reason:
                await ctx.send("You must provide a reason for the timeout.")
                return

            # Calculate the duration for the timeout
            timeout_duration = timedelta(minutes=duration)

            # Apply the timeout
            await member.timeout(timeout_duration, reason=reason)

            # Send a confirmation message
            await ctx.send(f"{member} has been timed out for {duration} minutes. Reason: {reason}", delete_after=10)

            # Log the timeout action
            log_channel = get(ctx.guild.text_channels, name=self.log_channel_name)
            if log_channel:
                await log_channel.send(f"{member} was timed out by {ctx.author} for {duration} minutes. Reason: {reason}")
        except discord.Forbidden:
            await ctx.send("I do not have permission to timeout this member.")
        except discord.HTTPException as e:
            await ctx.send(f"Failed to timeout the member. Error: {e}")

    @timeout.error
    async def timeout_error(self, ctx, error):
        if isinstance(error, commands.MissingRequiredArgument):
            await ctx.send("Usage: $timeout <member> <duration (in minutes)> <reason>")
        elif isinstance(error, commands.BadArgument):
            await ctx.send("Invalid argument type.")

async def setup(client):
    await client.add_cog(Timeout(client))
