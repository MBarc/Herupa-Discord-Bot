
import os

import pymongo

class HerupaMongo:

    def __init__(self):
        # Credentials come from the environment; fall back to the legacy admin/admin
        # so existing deployments keep working until the env vars are set.
        self.username = os.environ.get("MONGO_USERNAME", "admin")
        self.password = os.environ.get("MONGO_PASSWORD", "admin")
        self.host = os.environ.get("MONGO_HOST", "localhost:27017")
        self.connection_string = f"mongodb://{self.username}:{self.password}@{self.host}/"

        # A single MongoClient is created once and reused for every operation.
        # MongoClient maintains its own connection pool, so re-creating it on each
        # call (as the old code did) just wasted connections and added latency.
        self.client = pymongo.MongoClient(self.connection_string)

    def doesCollectionExist(self, database_name: str, collection_name: str):

        db = self.client[database_name]

        collist = db.list_collection_names()

        return collection_name in collist

    def createCollection(self, database_name: str, collection_name: str):

        db = self.client[database_name]

        db[collection_name]

    def addCollectionEntry(self, database_name: str, collection_name: str, payload: dict):

        db = self.client[database_name]

        col = db[collection_name]

        col.insert_one(payload)

    def removeCollectionEntry(self, database_name: str, collection_name: str, payload: dict):

        db = self.client[database_name]

        col = db[collection_name]

        col.delete_many(payload)

    def returnCollectionEntries(self, database_name: str, collection_name: str):

        db = self.client[database_name]

        col = db[collection_name]

        return list(col.find())

    def findSpecificDocumentsByKey(self, database_name: str, collection_name: str, key: str):

        db = self.client[database_name]

        col = db[collection_name]

        # Search for documents matching the query
        return list(col.find({key: {"$exists": True}}))

    def updateDocumentsByKey(self, database_name: str, collection_name: str, IDkey: str, IDvalue: str, key: str, value: str):

        db = self.client[database_name]

        col = db[collection_name]

        # Search for documents matching the query
        filter = {IDkey: IDvalue}

        new_value = {"$set": {key: value}}

        col.update_one(filter, new_value)
