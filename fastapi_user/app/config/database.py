import os
from motor.motor_asyncio import AsyncIOMotorClient
from motor.core import AgnosticCollection

async def get_users_collection() -> AgnosticCollection:
    try:
        mongo_client = AsyncIOMotorClient(
            f"mongodb://{os.getenv('MONGODB_USERNAME')}:{os.getenv('MONGODB_PASSWORD')}@{os.getenv('MONGODB_URL')}"
        )
        db = mongo_client["user_database"]
        users_collection = db.get_collection("users")
        print("MongoDB connection successful")
        return users_collection
    except Exception as e:
        print(f"MongoDB connection error: {e}")
        return None