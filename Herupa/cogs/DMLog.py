# Keeps the web control room's DM section fed: every direct message Herupa
# sees (either direction, including her own replies sent by other cogs or the
# web portal) updates a per-person conversation index in Mongo. The portal
# reads the index for its sidebar and pulls the actual message history live
# from Discord, so this only needs to know WHO the conversations are with.

from datetime import datetime, timezone

from discord.ext import commands

from tools.HerupaMongo import HerupaMongo


class DMLog(commands.Cog):

    def __init__(self, client):
        self.client = client
        self.mongo = HerupaMongo()

    def _convos(self):
        return self.mongo.client["dms"]["conversations"]

    @commands.Cog.listener()
    async def on_message(self, message):
        if message.guild is not None:
            return
        if message.author.id == self.client.user.id:
            other = message.channel.recipient
        else:
            other = message.author
        if other is None or other.bot:
            return
        preview = message.content or ("[attachment]" if message.attachments
                                      else "[embed]" if message.embeds else "")
        self._convos().update_one(
            {"_id": str(other.id)},
            {"$set": {"name": other.display_name or other.name,
                      "last_ts": datetime.now(timezone.utc),
                      "preview": preview[:80]}},
            upsert=True)


async def setup(client):
    await client.add_cog(DMLog(client))
