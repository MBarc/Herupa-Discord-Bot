'''
Purpose: Send Herupa's logs to a dedicated logging server.

Resolves the log guild + a channel BY NAME (so no channel IDs to wire up —
just create the channels below in the logging server). Every send is a no-op
if the guild or channel isn't available yet, so this is safe to run before
Herupa has been added to the logging server.
'''

import discord
from discord.utils import get

# The dedicated logging server.
LOG_GUILD_ID = 1249872743520931870

# Log type -> channel name to create in the logging server.
CHANNELS = {
    "error": "error-log",
    "mod": "mod-log",
    "activity": "activity-log",
    "ops": "ops-log",
    "ticket": "ticket-logs",
}


class HerupaLogger:

    def __init__(self, client):
        self.client = client

    def _channel(self, kind):
        guild = self.client.get_guild(LOG_GUILD_ID)
        if guild is None:
            return None
        return get(guild.text_channels, name=CHANNELS.get(kind))

    async def send(self, kind, *, content=None, embed=None, file=None):
        channel = self._channel(kind)
        if channel is None:
            return  # logging server / channel not available yet — no-op
        try:
            await channel.send(content=content, embed=embed, file=file,
                               allowed_mentions=discord.AllowedMentions.none())
        except discord.HTTPException:
            pass
