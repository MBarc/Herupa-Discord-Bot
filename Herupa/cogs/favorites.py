# Importing custom config file and default libraries
import sys
import os
from pathlib import Path
configPath = Path(os.path.abspath(os.path.dirname(__file__))).parent.absolute()
sys.path.insert(0, configPath)
from config import configFile
from discord.ext import commands

# Importing libraries specifically used for this command
import json
import datetime
import random
from discord.utils import get

class Favorites(commands.Cog):

    def __init__(self, client):
        self.client = client
        self.databasePath = Path(configFile()["databases"]["favorites"]).absolute()

    @commands.Cog.listener()
    async def on_voice_state_update(self, member, before, after):

        # function to add to JSON
        def write_json(data, filename=self.databasePath):
            with open(filename, 'w') as f:
                json.dump(data, f, indent=4)

        if (after.channel is not None) and (before.self_mute is not True) and (before.channel is None):
            memberID = f'{member.name}#{member.discriminator}'
            # Getting the data from the favorites database
            with open(self.databasePath) as json_file:
                data = json.load(json_file)

            #List of all the persons favorites
            try:
                memberFavorites = data[memberID]['favorites']
            except Exception as e: #If member does not have a key in the database
                data.update({memberID: {"favorites": [], "buffer": f"{datetime.datetime.now()}"}})
                write_json(data)
                memberFavorites = data[memberID]['favorites']

            # Checking to see if member and their favorite(s) are in each others' lists.
            for favorite in memberFavorites:
                # If favorite does not have key in json database, add it
                if not data.get(favorite):
                    data.update({favorite: {"favorites": [], "buffer": f"{datetime.datetime.now()}"}})
                    write_json(data)

                # if member is also in their favorite's favorite list
                if memberID in data[favorite]['favorites']:

                    favoriteName = favorite[:-5]
                    favoriteTag = favorite[-4: len(favorite)]
                    favoriteMention = get(self.client.get_all_members(), name=favoriteName, discriminator=favoriteTag)

                    #Grabbing favorite's buffer time
                    memberBuffer = data[memberID]['buffer']
                    memberBufferDatetime = datetime.datetime.strptime(memberBuffer, '%Y-%m-%d %H:%M:%S.%f')

                    currentTime = datetime.datetime.now()

                    # Send PM to {favorite} letting them know that {member} is in {voice chat}
                    tenMinutes = 10 * 60

                    if (favoriteMention.voice is None) and ((currentTime - memberBufferDatetime).total_seconds() >= tenMinutes):  # No need to notify {favorite} if they are connected to a voice channel already.

                        # Updating member's buffer time
                        data[memberID]['buffer'] = f'{datetime.datetime.now()}'

                        prompts = [f"Hey, {memberID} is in {after.channel.name}.",
                                   f"Hey, {memberID} is in {after.channel.name}. I think they wanna talk to you!",
                                   f"Hey, {memberID} is in {after.channel.name}. They told me to tell you to join!",
                                   f"Word on the street is that {memberID} is in {after.channel.name}. You should hit them up :sunglasses: .",
                                   f"Hey, {memberID} is in {after.channel.name}. Go join and tell them how you really feel!",
                                   f"Hey, {memberID} is in {after.channel.name}. Go ask them what their favorite color is.",
                                   f"Hey {memberID} is in {after.channel.name}. Don't be shy! Go and talk to them :partying_face: .",
                                   f"Hey, {memberID} is in {after.channel.name}. Go chill with them!",
                                   f"Hey, {memberID} is in {after.channel.name}. You should join them so they can stop talking to themselves.",
                                   f"Just wanted to let you know that {memberID} is in {after.channel.name}! They might be talking smack about you :man_shrugging: .",
                                   f"Hey, {memberID} is in {after.channel.name}. Hurry before they leave!",
                                   f"Heads up! {memberID} is in {after.channel.name}. You should go see what's up :eyes: .",
                                   f"Hey, {memberID} is in {after.channel.name}. You should join, I think they miss you. :cry:",
                                   f"Hey, {memberID} is in {after.channel.name}. Go chat with them!",
                                   f"Hey, {memberID} is in {after.channel.name}. Let them know I sent you!",
                                   f"This just in! {memberID} just joined {after.channel.name}!",
                                   f"Hey, {memberID} is in {after.channel.name}. And that’s the tea!",
                                   f"Hey, {memberID} is in {after.channel.name} and they’re being sneaky about it. :eyes:",
                                   f"Wassup homie? You should go chill with {memberID}. They're in {after.channel.name} right now!",
                                   f"Hey, {memberID} is in {after.channel.name}. What do you think they’re talking about?",
                                   f"Hey, {memberID} is in {after.channel.name}. I heard from my sister’s hairdresser’s brother’s best friend’s niece-in-law that you should join!",
                                   f"Hey, {memberID} is in {after.channel.name}. What letter comes after T? Oh yeah! U should join!",
                                   f"Hey, {memberID} is in {after.channel.name}. It’s quiet in there, too quiet.",
                                   f"Hey, {memberID} is in {after.channel.name}. I eavesdropped on their convo and it was juicy!",
                                   f"I think {memberID} is in {after.channel.name} but I'm not sure. Can you check for me?",
                                   f"Hey, {memberID} is in {after.channel.name}. What are the odds that you join them?",
                                   f"Hey, {memberID} is in {after.channel.name}. Should I pull up a seat for you?",
                                   f"Hey, {memberID} is in {after.channel.name}. The channel is big enough for the both of you!",
                                   f"Hey, {memberID} is in {after.channel.name}. Join them at your own risk!",
                                   f"Hello, is it me you're looking for? Or is it {memberID}? Because they're in {after.channel.name} right now!",
                                   f"Hey, {memberID} is in {after.channel.name}. WOOOOOOOOO!",
                                   f"Hey, {memberID} is in {after.channel.name}. Get in there!",
                                   f"Hey, {memberID} is in {after.channel.name}. I dare you to join. :eyes:",
                                   f"I was programmed to tell you that {memberID} is in {after.channel.name} right now :man_shrugging: .",
                                   f"A little birdie told me that {memberID} is in {after.channel.name}. You should go see what they're doing!",
                                   f"Hey, {memberID} is in {after.channel.name}. Don’t just stand there, join!",
                                   f"Hey, {memberID} is in {after.channel.name}. This message is brought to you by Herupa ™.",
                                   f"Stop what you're doing! {memberID} is in {after.channel.name} right now!",
                                   f"Hey, {memberID} is in {after.channel.name}. Get in there and show them what you’re made of!",
                                   f"Hey, {memberID} is in {after.channel.name}. I think they’re in love with you. Go ask."
                                   ]

                        await favoriteMention.send(random.choice(prompts))

            #Actually writing the updated member's buffer time
            write_json(data)

    @commands.command()
    async def addfavorite(self, ctx):

        #Grabbing the message that triggered this instance
        channel = self.client.get_channel(ctx.message.channel.id)
        message = await channel.fetch_message(ctx.message.id)

        if not message.mentions: # if there is no @mention within the message
            raise Exception('NoMentionsMentioned')

        #Getting the person to add to the favorites list
        favoriteToAdd = str(message.mentions[0])

        #Getting the authors list to know which list to add the favorite person to
        member = str(ctx.message.author)
        memberName = favoriteToAdd[:-5]
        memberTag = favoriteToAdd[-4:len(favoriteToAdd)]
        memberMention = get(self.client.get_all_members(), name=memberName, discriminator=memberTag)

        # if member is trying to add themselves as a favorite
        if member == favoriteToAdd:
            raise Exception('FavAndMemberSame')


        # function to add to JSON
        def write_json(data, filename=self.databasePath):
            with open(filename, 'w') as f:
                json.dump(data, f, indent=4)

        with open(self.databasePath) as json_file:
            data = json.load(json_file)

            #if member doesn't have key in json
            if not data.get(member):
                data.update({member: {"favorites": [], "buffer": f'{datetime.datetime.now()}'}})
                write_json(data)

            temp = data[member]['favorites']

            tracker = False  # Keeps track if the favorite is already in the member's favorite list
            for favorite in temp:
                if favorite == favoriteToAdd:
                    tracker = True

            if tracker == False:
                await ctx.channel.send(f"Sucessfully added {favoriteToAdd} to your favorites! Remember, you won't get notifications about them until they have also added you to their favorites.")
                temp.append(favoriteToAdd)
                write_json(data)
            else:
                await ctx.channel.send("You already have this person added to your favorites.")

        await message.mentions[0].send(f'{member} has added you to their favorites.')
        #await ctx.message.delete()
        if len(message.mentions) > 1:
            raise Exception('TooManyMentions')

    @addfavorite.error
    async def addfavorite_error(self, ctx, error):

        commandName = ctx.invoked_with
        error = str(error)

        if 'NoMentionsMentioned' in error:
            await ctx.channel.send("You forgot to @mention someone for that command. Example use -> $addfavorite {@mention}.")

        if 'TooManyMentions' in error:
            await ctx.channel.send("Hey I can only add one person at a time so I have gone ahead and added the 1st person you mentioned that was not already in your favorites list, but not the rest. Please do one at a time.")

        if 'FavAndMemberSame' in error:
            await ctx.channel.send("Just an FYI, you can't add yourself as a favorite. I like the confidence though.")

        herupaErrorLogChannel = self.client.get_channel(configFile()["herupaErrorLogChannel"])
        await herupaErrorLogChannel.send(f"{commandName.upper()} error: {error}")


    @commands.command()
    async def removefavorite(self, ctx):

        # Grabbing the message that triggered this instance
        channel = self.client.get_channel(ctx.message.channel.id)
        message = await channel.fetch_message(ctx.message.id)

        # Grabbing the name and tag of the member (to add to the database) and the author

        if not message.mentions:  # if there is no @mention within the message
            raise Exception('NoMentionsMentioned')

        # Getting the person to add to the favorites list
        favoriteToRemove = str(message.mentions[0])

        # Getting the authors list to know which list to remove the (no longer) favorite person from
        member = str(ctx.message.author)
        memberName = favoriteToRemove[:-5]
        memberTag = favoriteToRemove[-4:len(favoriteToRemove)]
        memberMention = get(self.client.get_all_members(), name=memberName, discriminator=memberTag)

        # function to add to JSON
        def write_json(data, filename=self.databasePath):
            with open(filename, 'w') as f:
                json.dump(data, f, indent=4)

        with open(self.databasePath) as json_file:
            data = json.load(json_file)

            # if member doesn't have key in json
            if not data.get(member):
                raise Exception("MembersFavoritesListEmpty")

            temp = data[member]['favorites']

            tracker = False  # Keeps track if the favorite is already in the member's favorite list
            for favorite in temp:
                if favorite == favoriteToRemove:
                    tracker = True

            if tracker == True:
                data[member]['favorites'] = [name for name in temp if name != favoriteToRemove]
                write_json(data)
                await ctx.channel.send(f"Successfully removed {favoriteToRemove} from your favorites! You will no longer receive notifications about them.")
            else:
                await ctx.channel.send("This person was not in your friends list to begin with.")

        #await ctx.message.delete()
        if len(message.mentions) > 1:
            raise Exception('TooManyMentions')

    @removefavorite.error
    async def removefavorite_error(self, ctx, error):

        commandName = ctx.invoked_with
        error = str(error)

        if 'NoMentionsMentioned' in error:
            await ctx.channel.send(
                "You forgot to @mention someone for that command. Example use -> $removefavorite {@mention}.")

        if 'TooManyMentions' in error:
            await ctx.channel.send(
                "Hey I can only add one person at a time so I have gone ahead and added the 1st person you mentioned, but not the rest. Please do one at a time.")

        if 'MembersFavoritesListEmpty' in error:
            await ctx.channel.send(
                "I could not remove that member from your favorites list considering that your favorites list is empty.")

        herupaErrorLogChannel = self.client.get_channel(configFile()["herupaErrorLogChannel"])
        await herupaErrorLogChannel.send(f"{commandName.upper()} error: {error}")

    @commands.command()
    async def myfavorites(self, ctx):

        author = str(ctx.message.author)

        with open(self.databasePath) as json_file:
            data = json.load(json_file)

            message = 'Here is a list of all your favorites: \n'

            #For each of the author's favorites
            for favorite in data.get(author)['favorites']:
                message += f'•{favorite}\n' #change favorite to be a mention instead of string;

            await ctx.channel.send(message)

    @myfavorites.error
    async def myfavorites_error(self, ctx, error):

        commandName = ctx.invoked_with
        error = str(error)

        herupaErrorLogChannel = self.client.get_channel(configFile()["herupaErrorLogChannel"])
        await herupaErrorLogChannel.send(f"{commandName.upper()} error: {error}")

async def setup(client):
    await client.add_cog(Favorites(client))
