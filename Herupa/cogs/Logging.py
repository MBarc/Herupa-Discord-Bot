'''
Purpose: Expose specific logs to Deputies which are restricted admins.
'''

from discord.ext import commands
from discord.utils import get

class Logging(commands.Cog):

    def __init__(self, client):
        self.client = client
        self.vc_leave_or_join_channel = "🔍vc-leave-or-join🔍"
        self.message_delete_channel = "❌message-delete❌"

    @commands.Cog.listener()
    async def on_voice_state_update(self, member, before, after):

        vc_leave_or_join_channel = get(member.guild.channels, name=self.vc_leave_or_join_channel)

        # Joined voice channel
        if before.channel is None and after.channel is not None:
            await vc_leave_or_join_channel.send(f"{member} joined {after.channel.name}")

        # Left voice channel
        elif before.channel is not None and after.channel is None:
            await vc_leave_or_join_channel.send(f"{member} left {before.channel.name}")

        # Switched voice channel
        elif before.channel is not None and after.channel is not None and before.channel != after.channel:
            await vc_leave_or_join_channel.send(f"{member} switched from {before.channel.name} to {after.channel.name}")

    @commands.Cog.listener()
    async def on_message_delete(self, message):

        message_delete_channel = get(message.guild.channels, name=self.message_delete_channel)

        # Check if the deleted message author is not a bot and it's not from a DM channel
        if not message.author.bot and message.guild:
            await message_delete_channel.send(f"{message.author}'s message was deleted: \"{message.content}\"")


async def setup(client):
    await client.add_cog(Logging(client))