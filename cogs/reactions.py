"""
We want Chill Club to have a little bit of everything for everyone while remaining, visually, clutter free.
React to this message with the appropriate emoji to unlock the respective category.
If you would like for us to include a category, feel free to let us know via :package:suggestions-box:package:.

:zero:  Animal Crossing
:one:  Call of Duty
:two:  Rocket League
:three:  Space! - a category for space lovers :star2:
:four:  Among Us
"""

from discord.ext import commands
from discord.utils import get

class Reactions(commands.Cog):

    def __init__(self, client):
        self.client = client
        self.message = 727219710428708947  # self assign setup message

    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload):

        channel = await self.client.fetch_channel(payload.channel_id)
        message = await channel.fetch_message(payload.message_id)
        member = payload.member
        emoji = payload.emoji

        if message.id == self.message:

            if str(emoji) == "0️⃣":
                animalCrossingRole = get(member.guild.roles, name='animal crossing')
                await member.add_roles(animalCrossingRole)

            if str(emoji) == "1️⃣":
                callOfDutyRole = get(member.guild.roles, name='call of duty')
                await member.add_roles(callOfDutyRole)

            if str(emoji) == "2️⃣":
                rocketLeagueRole = get(member.guild.roles, name='rocket league')
                await member.add_roles(rocketLeagueRole)

            if str(emoji) == "3️⃣":
                spaceBuddiesRole = get(member.guild.roles, name='space buddies')
                await member.add_roles(spaceBuddiesRole)

            if str(emoji) == "4️⃣":
                amongUsRole = get(member.guild.roles, name='among us')
                await member.add_roles(amongUsRole)

            # Gender Pronouns

            if str(emoji) == "❤":
                amongUsRole = get(member.guild.roles, name='she/her')
                await member.add_roles(amongUsRole)

            if str(emoji) == "💙":
                amongUsRole = get(member.guild.roles, name='he/him')
                await member.add_roles(amongUsRole)

            if str(emoji) == "💚":
                amongUsRole = get(member.guild.roles, name='they/them')
                await member.add_roles(amongUsRole)

            if str(emoji) == "💜":
                amongUsRole = get(member.guild.roles, name='any pronoun')
                await member.add_roles(amongUsRole)

            if str(emoji) == "💛":
                amongUsRole = get(member.guild.roles, name='other')
                await member.add_roles(amongUsRole)

            # Age

            if str(emoji) == "👨‍🦳":
                ofAgeRole = get(member.guild.roles, name='18+')
                await member.add_roles(ofAgeRole)

    @commands.Cog.listener()
    async def on_raw_reaction_remove(self, payload):

        guild = self.client.get_guild(payload.guild_id)
        channel = await self.client.fetch_channel(payload.channel_id)
        message = await channel.fetch_message(payload.message_id)
        member = guild.get_member(payload.user_id)
        emoji = payload.emoji

        if message.id == self.message:

            if str(emoji) == "0️⃣":
                animalCrossingRole = get(member.guild.roles, name='animal crossing')
                await member.remove_roles(animalCrossingRole)

            if str(emoji) == "1️⃣":
                callOfDutyRole = get(member.guild.roles, name='call of duty')
                await member.remove_roles(callOfDutyRole)

            if str(emoji) == "2️⃣":
                rocketLeagueRole = get(member.guild.roles, name='rocket league')
                await member.remove_roles(rocketLeagueRole)

            if str(emoji) == "3️⃣":
                spaceBuddiesRole = get(member.guild.roles, name='space buddies')
                await member.remove_roles(spaceBuddiesRole)

            if str(emoji) == "4️⃣":
                amongUsRole = get(member.guild.roles, name='among us')
                await member.remove_roles(amongUsRole)

            # Gender Pronouns

            if str(emoji) == "❤":
                amongUsRole = get(member.guild.roles, name='she/her')
                await member.remove_roles(amongUsRole)

            if str(emoji) == "💙":
                amongUsRole = get(member.guild.roles, name='he/him')
                await member.remove_roles(amongUsRole)

            if str(emoji) == "💚":
                amongUsRole = get(member.guild.roles, name='they/them')
                await member.remove_roles(amongUsRole)

            if str(emoji) == "💜":
                amongUsRole = get(member.guild.roles, name='any pronoun')
                await member.remove_roles(amongUsRole)

            if str(emoji) == "💛":
                amongUsRole = get(member.guild.roles, name='other')
                await member.remove_roles(amongUsRole)

            # Age

            if str(emoji) == "👨‍🦳":
                ofAgeRole = get(member.guild.roles, name='18+')
                await member.remove_roles(ofAgeRole)

def setup(client):
    client.add_cog(Reactions(client))