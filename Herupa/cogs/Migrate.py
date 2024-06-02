import discord
from discord.ext import commands

class Migrate(commands.Cog):

    def __init__(self, client):
        self.client = client

    @commands.command(name='migrate',
                      description='Mass migrate people to another voice channel.',
                      brief='Move all members of your voice channel to another channel.',
                      aliases=["m"])
    async def migrate(self, ctx, target_channel_id: int):  # Now the channel ID is passed as a command argument

        # Get the target channel
        target_channel = self.client.get_channel(target_channel_id)

        # Check if the target channel exists
        if target_channel is None:
            await ctx.send("Invalid channel ID.")
            return

        # Check if the member invoking the command is in a voice channel
        if ctx.author.voice is None:
            await ctx.send("You are not in a voice channel.")
            return

        # Get the voice channel the member is currently in
        source_channel = ctx.author.voice.channel

        # Check if the bot has permission to move members
        if not source_channel.permissions_for(ctx.guild.me).move_members:
            await ctx.send("I don't have permission to move members.")
            return

        # Move all members from the source channel to the target channel
        for member in source_channel.members:
            await member.move_to(target_channel)

        await ctx.send(f"Moved all members from {source_channel.name} to {target_channel.name}.")


async def setup(client):
    await client.add_cog(Migrate(client))
