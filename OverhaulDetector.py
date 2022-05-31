#! /usr/bin/python3
"""
Purpose: This program will detect when Herupa has received an update to her Github and automatically update her code. This program does not update itself.

Note: This program is designed to be executed, via Crontab, once every minute.
"""

from datetime import datetime
import requests
import json
import os
import logging
from discord_webhook import DiscordWebhook, DiscordEmbed

class OverhaulDetector:

    def __init__(self, repoName = "Herupa-Discord-Bot", branch = "main"):
        self.githubUsername = "MBarc"
        self.repoName: str = repoName
        self.branch: str = branch
        self.herupaCogLocation: str = "./Herupa/cogs"
        self.githubPAT = os.environ.get("GITHUB_PAT")
        self.updateLogWebhook = "https://discordapp.com/api/webhooks/980949892434374736/bqQsDwSizpxMUYHsbaXRky7Tt6ZAXOew6hYdKU-g4Kx3-cV30CBtCSyzRZ96UC2tyVqZ"


    def ensure_queue_exists(self, filename = "./queue.json"):
        """
        Creates the queue file if it does not exist.
        """
        if not os.path.exists("./queue.json"):

            currentTime = datetime.utcnow()
            templateCreationTime = f"{currentTime.year}-{currentTime.month}-{currentTime.day}T{currentTime.hour}:{currentTime.minute}:{currentTime.second}Z"

            template = {"lastUpdated": templateCreationTime, "entries": {}}

            self.write_json_to_file(filename, template)
        

        with open("./queue.json", "r+") as queueFile:
            queue = json.load(queueFile)

            if not "lastUpdated" in queue:
                queue["lastUpdated"] = self.datetime_to_github_format(datetime.utcnow())

            if not "entries" in queue:
                queue["entries"] = {}

            self.write_json_to_file(filename="./queue.json", dict=queue)


    def datetime_to_github_format(self, datetimeObject):
        """
        Changes datetime's default format from %Y-%m-%d %H:%M:%S.%f to "%Y-%m-%dT%H:%M:%SZ"
        """
        githubFormat = f"{datetimeObject.year}-{datetimeObject.month}-{datetimeObject.day}T{datetimeObject.hour}:{datetimeObject.minute}:{datetimeObject.second}Z"

        return githubFormat
        

    def download_file(self, url, filename):
        """
        Downloads a file from the given url.
        """

        # Creating directory if it does not exist
        if not os.path.exists(os.path.dirname(filename)):
            #print("Path doesn't exist locally so creating it. . .")
            os.makedirs(os.path.dirname(filename))

        with requests.get(url, stream=True) as r:
            r.raise_for_status()
            with open(filename, 'wb+') as f:
                for chunk in r.iter_content(chunk_size=8192):  
                    f.write(chunk)


    def time_since_last_commit(self, github_time):
        """
        Returns (in minutes) how long it has been since the last commit was submitted.
        """

        utcTime = datetime.utcnow()
        githubTime = datetime.strptime(github_time, "%Y-%m-%dT%H:%M:%SZ")

        return int(((utcTime - githubTime).seconds / 60))


    def diff_between_times(self, olderTime, recentTime):
        """
        Returns the minute different between two datetime objects
        """

        return (recentTime - olderTime).seconds / 60


    def write_json_to_file(self, filename, dict):
        """
        Writes the dict object to the specified file
        """
        with open(filename, 'w') as f:
            json.dump(dict, f, indent=4)


    def process_queue(self):
        """
        Processing the queue. This involves downloading the files listed in the queue.
        """

        with open("./queue.json", "r+") as queueFile:
            
            # Actually loading the queue data into memory
            queue = json.load(queueFile)

            # Grabbing when the queue was last updated
            lastUpdated = datetime.strptime(queue["lastUpdated"], "%Y-%m-%dT%H:%M:%SZ")

            # If we have commits to process and the queue wasn't update within the same minute
            if len(queue["entries"].keys()) >= 1 and self.diff_between_times(lastUpdated, datetime.utcnow()) != 0:

                # Go through each key to process the paired values
                for key in list(queue["entries"].keys()):

                    #print("about to process this -> ", key)

                    queueURL = filename = queue["entries"].get(key)["url"]
                    filename = queue["entries"].get(key)["filename"]
                    dateQueued = datetime.strptime(queue["entries"].get(key)["date"], "%Y-%m-%dT%H:%M:%SZ")

                    #if 5 minutes have passed
                    if self.diff_between_times(dateQueued, datetime.utcnow()) >= 5:

                        # Note: We have to process the commit 5 minutes after we notice it because the Github Raw link updates after 5 minutes.

                        # Downloading the edited file locally
                        self.download_file(queueURL, filename)

                        # Removing the key from the json so we don't process it again
                        queue["entries"].pop(key)
                        queue["lastUpdated"] = self.datetime_to_github_format(datetimeObject=datetime.utcnow())
                        self.write_json_to_file(dict=queue, filename="./queue.json")


    def add_to_queue(self, queue, url, commitResponse, file):
        """
        Adding a file to the queue to be processed later.
        """
        
        logging.info(f"Adding {file} to queue. . .")
        
        if len(queue["entries"].keys()) == 0:

            webhook = DiscordWebhook(url=self.updateLogWebhook, content=f'0 entries found, adding new one -> {file}')
            webhook.execute()

            # Updating the queue with a new entry
            queue["entries"].update({"0": {"url": url, "filename": f"./Herupa/{file['filename']}", "date": f'{commitResponse["commit"]["author"]["date"]}'}})
            
            # Writing down when the queue was last updated
            queue["lastUpdated"] = self.datetime_to_github_format(datetimeObject=datetime.utcnow())
            
            # Actually writing the queue back to the queue file
            self.write_json_to_file(dict=queue, filename="./queue.json")
        else:
            
            # Grabbing the last key in the queue and casting it to an int
            lastKey = int(list(queue["entries"].keys())[-1])
            
            # Adding 1 to the last key to create a new entry
            newKey = str(lastKey + 1)

            # Updating the queue with a new entry
            queue["entries"].update({newKey: {"url": url, "localPath": f"./Herupa/{file['filename']}", "filename": f"{file['filename']}", "date": f'{commitResponse["commit"]["author"]["date"]}'}})

            # Writing down when the queue was last updated
            queue["lastUpdated"] = self.datetime_to_github_format(datetimeObject=datetime.utcnow())
            
            webhook = DiscordWebhook(url=self.updateLogWebhook, content=queue)
            webhook.execute()
            
            # Actually writing the queue back to the queue file
            self.write_json_to_file(dict=queue, filename="./queue.json")

    def updateLog(self, files):

        # Formatting the list of files names so we can put them in a message
        listFiles = ''.join([file["filename"] + "\n" for file in files])

        # Creating the webhook object
        webhook = DiscordWebhook(url=self.updateLogWebhook)

        # Getting the current time so that info can be added to the update message
        currentTime = datetime.now()

        # Adding the information to the webhook
        embed = DiscordEmbed(title=f"Updated Detected on {currentTime.month}-{currentTime.day}-{currentTime.year} at {currentTime.hour}:{currentTime.minute}", description=listFiles, color='ffb7c5')
        
        # Setting a disclaimer
        embed.set_footer(text='Updates are applied ~5 minutes after they are detected.')

        # Adding our embed object to the payload that we are going to sen 
        webhook.add_embed(embed)

        # Actually sending our payload to our webhook
        webhook.execute()

        return


    def main(self, behavior):

        logging.info("STARTING LOOP!")

        if behavior == "standard":

            logging.info("Standard behavior has been specified.")

            # Creating queue if it doesn't exist
            self.ensure_queue_exists()

            # Processing queue
            self.process_queue()

            # Creating headers to authentication
            headers = {"Accept": "application/vnd.github.v3+json", "Authorization": f"token {self.githubPAT}"}

            # Getting the latest SHA using Github trees
            shaURL = f"https://api.github.com/repos/{self.githubUsername}/{self.repoName}/git/trees/main?recursive=1"
            shaResponse = requests.get(shaURL, headers=headers).json()
            latestSHA = shaResponse["sha"]

            # Getting the date that latest commit was submitted (by using the SHA)
            commitURL = f"https://api.github.com/repos/{self.githubUsername}/{self.repoName}/commits/{latestSHA}"
            commitResponse = requests.get(commitURL, headers=headers).json()
            timeSinceLastCommit = self.time_since_last_commit(commitResponse["commit"]["author"]["date"])

            # If the last commit just occured
            if timeSinceLastCommit <= 0:

                logging.info("Recent commit detected! Commit was submitted less than a minute ago. . .")

                # Going through each file that is affected by the latest commit
                for file in commitResponse["files"]:

                    # If a cog was affected
                    if "cog" in file["filename"]:

                        logging.info("Cog file affected ->", file["filename"])

                        # Grabbing if the file was updated, added, or deleted.
                        status = file["status"].lower()

                        #print(file["status"].lower())

                        # if the file was removed from the repository
                        if "removed" in status:

                            logging.info("Deleting cog file locally!")

                            # delete the file locally
                            #print("File exists locally? -> ", os.path.exists(f"./Herupa/{file['filename']}"))
                            os.remove(f"./Herupa/{file['filename']}")

                        # if the file was updated or added to the repository
                        if "modified" in status or "added" in status:
                            
                            logging.info("Detected that the cog file was either added or modified! Continuing. . .")

                            # Opening up out queue file to read and write to
                            with open("./queue.json", "r+") as queueFile:
                                
                                # Actually loading the queue data into memory
                                queue = json.load(queueFile)

                                # Building the URL to download the file from
                                url = f"https://raw.githubusercontent.com/{self.githubUsername}/{self.repoName}/{self.branch}/{file['filename']}"

                                # Adding a process to the queue
                                logging.info("Added the file to be processed by the queue.")
                                self.add_to_queue(queue, url, commitResponse, file)

                # Sending an update notification to the discord server
                self.updateLog(commitResponse["files"])

if __name__ == "__main__":

    od = OverhaulDetector()
    od.main(behavior="standard")
