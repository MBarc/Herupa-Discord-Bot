
import pymongo

class HerupaMongo:

    def __init__(self):
        self.username = "admin" # change this to get from config or env variable
        self.password = "admin" # change this to get from config or env variable
        self.connection_string = f"mongodb://{self.username}:{self.password}@mongo:27017/"

    def doesCollectionExist(self, database_name: str, collection_name: str):

        client = pymongo.MongoClient(self.connection_string)

        db = client[database_name]

        collist = db.list_collection_names()
        
        if collection_name in collist:
            
            # The collection name exist
            client.close()
            return True

        # The collection does not exist
        client.close()
        return False
        

    def createCollection(self, database_name: str, collection_name: str):

        client = pymongo.MongoClient(self.connection_string)

        db = client[database_name]

        db[collection_name]

        client.close()

    def addCollectionEntry(self, database_name: str, collection_name: str, payload: dict):
        
        client = pymongo.MongoClient(self.connection_string)

        db = client[database_name]

        col = db[collection_name]

        col.insert_one(payload)
        
        client.close()

    def removeCollectionEntry(self, database_name: str, collection_name: str, payload: dict):
        
        client = pymongo.MongoClient(self.connection_string)

        db = client[database_name]

        col = db[collection_name]

        col.delete_many(payload)
        
        client.close()

    def returnCollectionEntries(self, database_name: str, collection_name: str):

        client = pymongo.MongoClient(self.connection_string)

        db = client[database_name]

        col = db[collection_name]

        all_documents = col.find()

        document_list = [doc for doc in all_documents]

        client.close()

        return document_list
    
    def findSpecificDocumentsByKey(self, database_name: str, collection_name: str, key: str):

        client = pymongo.MongoClient(self.connection_string)

        db = client[database_name]

        col = db[collection_name]

        # Search for documents matching the query
        matching_documents = col.find({key: {"$exists": True}})

        document_list = [doc for doc in matching_documents]
        
        client.close()

        return document_list
    
    def updateDocumentsByKey(self, database_name: str, collection_name: str, IDkey: str, IDvalue: str, key: str, value: str):

        client = pymongo.MongoClient(self.connection_string)

        db = client[database_name]

        col = db[collection_name]

        # Search for documents matching the query
        filter = {IDkey: IDvalue}

        new_value = {"$set": {key: value}}

        col.update_one(filter, new_value)

        client.close()
