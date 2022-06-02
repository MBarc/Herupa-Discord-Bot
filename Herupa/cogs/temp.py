# This is a temp command to do small, one-time tasks. This command can be deleted if needed.

import discord
from discord.ext import commands

class Temp(commands.Cog):

    def __init__(self, client):
        self.client = client

    @commands.command()
    async def temp(self, ctx):
        
        if ctx.message.author != ctx.message.guild.owner:
            await ctx.message.send("Only the server owner can run this command!")
            return

        target = await ctx.message.channel.fetch_message(727219710428708947)

        #await target.add_reaction('0️⃣')
        #await target.add_reaction('1️⃣')
        #await target.add_reaction('2️⃣')
        #await target.add_reaction('3️⃣')
        #await target.add_reaction('4️⃣')
        #await target.add_reaction('5️⃣')
        await target.add_reaction('6️⃣')
        #await target.add_reaction('7️⃣')
        #await target.add_reaction('8️⃣')
        #await target.add_reaction('9️⃣')
        #await target.add_reaction('🔟')

        #await target.add_reaction('❤') # red heart
        #await target.add_reaction('💙') # blue heart
        #await target.add_reaction('💚') # green heart
        #await target.add_reaction('💜') # purple heart
        #await target.add_reaction('💛') # yellow heart

        #await target.add_reaction('👨‍🦳') # yellow heart



def setup(client):
    client.add_cog(Temp(client))
