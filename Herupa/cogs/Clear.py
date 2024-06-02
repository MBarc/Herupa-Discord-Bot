# Importing libraries specifically used for this command
import random
from discord.ext import commands

class Clear(commands.Cog):

    def __init__(self, client):
        self.client = client


    @commands.command(name='clear',
                    description = 'Allows user to delete messages in bulk.',
                    brief = 'Allows user to delete messages in bulk.',
                    pass_context = True,
                    aliases=['c'])
    async def clear(self, ctx, amount = 5):

        memberPermissionError = [
            "Oops! You do not have the permissions to manage messages.",
            "I got an error within my code saying something like 'User does not have permission to manage messages'. Know anything 'bout that?",
            "Sorry! You don't have permission to manage messages."
        ]

        herupaPermissionError = [
            "Uh oh! I can't manage messages.",
            "Sorry! I don't have permission to manage messages.",
            "Is it hot in here? Or do I no longer have permission to manage messages?",
            "I wasn't given permission to manage messages :cry:."
        ]

        try:
            if ctx.message.author.guild_permissions.manage_messages:
                await ctx.channel.purge(limit=amount + 1, check=lambda msg: not msg.pinned)  # +1 to delete the original command that triggered this function
            else:
                await ctx.channel.send(random.choice(memberPermissionError))

        except Exception as e:
            if e.code == 50013:  # Missing permissions error Code
                await ctx.channel.send(random.choice(herupaPermissionError))
            else:
                await ctx.channel.send(f"Please report this error as an issue on the Herupa Github page: {str(e)}")

async def setup(client):
    await client.add_cog(Clear(client))