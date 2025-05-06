from app.models.user import UserCreate, UserResponse
from app.config.database import get_write_users_collection, get_read_users_collection
from motor.core import AgnosticCollection
from bson import ObjectId
import logging

logger = logging.getLogger(__name__)

class UserService:
    @staticmethod
    async def create_user(user: UserCreate) -> UserResponse:
        """
        새로운 사용자 생성 (Write DB 사용)
        """
        users_collection = await get_write_users_collection()
        if users_collection is None:
            raise Exception("Database write connection failed")
        
        user_dict = user.dict()
        result = await users_collection.insert_one(user_dict)
        user_id = result.inserted_id
        
        logger.info(f"User created with ID: {user_id}")
        return UserResponse(id=str(user_id), **user_dict)

    @staticmethod
    async def get_users() -> list[UserResponse]:
        """
        모든 사용자 조회 (Read DB 사용)
        """
        users_collection = await get_read_users_collection()
        if users_collection is None:
            raise Exception("Database read connection failed")
        
        users = []
        async for user in users_collection.find():
            users.append(UserResponse(id=str(user["_id"]), **user))
        
        logger.info(f"Retrieved {len(users)} users")
        return users

    @staticmethod
    async def get_user(username: str) -> UserResponse:
        """
        사용자 이름으로 사용자 조회 (Read DB 사용)
        """
        users_collection = await get_read_users_collection()
        if users_collection is None:
            raise Exception("Database read connection failed")
        
        user = await users_collection.find_one({"name": username})
        if user:
            logger.info(f"User found by username: {username}")
            return UserResponse(id=str(user["_id"]), **user)
        logger.warning(f"User not found by username: {username}")
        return None

    @staticmethod
    async def get_user_by_id(user_id: str) -> UserResponse:
        """
        사용자 ID로 사용자 조회 (Read DB 사용)
        """
        users_collection = await get_read_users_collection()
        if users_collection is None:
            raise Exception("Database read connection failed")
        
        try:
            user = await users_collection.find_one({"_id": ObjectId(user_id)})
            if user:
                logger.info(f"User found by ID: {user_id}")
                return UserResponse(id=str(user["_id"]), **user)
            logger.warning(f"User not found by ID: {user_id}")
            return None
        except Exception as e:
            logger.error(f"Error retrieving user by ID {user_id}: {str(e)}")
            raise Exception(f"Invalid user ID format: {str(e)}")