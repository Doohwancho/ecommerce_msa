import os
from motor.motor_asyncio import AsyncIOMotorClient
from motor.core import AgnosticCollection

# mongodb 연결 설정
MONGODB_HOST = os.getenv("MONGODB_HOST", "mongodb-service")
MONGODB_REPLICA_SET = os.getenv("MONGODB_REPLICA_SET", "rs0")
MONGODB_AUTH_SOURCE = os.getenv("MONGODB_AUTH_SOURCE", "admin")

async def get_users_collection() -> AgnosticCollection:
    try:
        mongo_client = AsyncIOMotorClient(
            # before replica set, standalone 
            # f"mongodb://{os.getenv('MONGODB_USERNAME')}:{os.getenv('MONGODB_PASSWORD')}@{os.getenv('MONGODB_URL')}"
            # replica set
            f"mongodb://{os.getenv('MONGODB_USERNAME')}:{os.getenv('MONGODB_PASSWORD')}@{MONGODB_HOST}:27017/?replicaSet={MONGODB_REPLICA_SET}&authSource={MONGODB_AUTH_SOURCE}"
        )
        db = mongo_client["user_database"]
        users_collection = db.get_collection("users")
        print("MongoDB connection successful")
        return users_collection
    except Exception as e:
        print(f"MongoDB connection error: {e}")
        return None