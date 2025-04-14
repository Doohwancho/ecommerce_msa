from app.models.user import UserCreate, UserResponse
from app.config.database import get_users_collection
from motor.core import AgnosticCollection
from bson import ObjectId

class UserService:
    @staticmethod
    async def create_user(user: UserCreate) -> UserResponse:
        users_collection = await get_users_collection()
        if users_collection is None:
            raise Exception("Database connection failed")
        
        user_dict = user.dict()
        result = await users_collection.insert_one(user_dict)
        user_id = result.inserted_id
        
        return UserResponse(id=str(user_id), **user_dict)

    @staticmethod
    async def get_users() -> list[UserResponse]:
        users_collection = await get_users_collection()
        if users_collection is None:
            raise Exception("Database connection failed")
        
        users = []
        async for user in users_collection.find():
            users.append(UserResponse(id=str(user["_id"]), **user))
        
        return users

    @staticmethod
    async def get_user(username: str) -> UserResponse:
        users_collection = await get_users_collection()
        if users_collection is None:
            raise Exception("Database connection failed")
        
        user = await users_collection.find_one({"name": username})
        if user:
            return UserResponse(id=str(user["_id"]), **user)
        return None

    @staticmethod
    async def get_user_by_id(user_id: str) -> UserResponse:
        users_collection = await get_users_collection()
        if users_collection is None:
            raise Exception("Database connection failed")
        
        try:
            user = await users_collection.find_one({"_id": ObjectId(user_id)})
            if user:
                return UserResponse(id=str(user["_id"]), **user)
            return None
        except Exception as e:
            raise Exception(f"Invalid user ID format: {str(e)}")