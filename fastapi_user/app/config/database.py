import os
from motor.motor_asyncio import AsyncIOMotorClient
from motor.core import AgnosticCollection
import logging

logger = logging.getLogger(__name__)

# mongodb 연결 설정
MONGODB_HOST = os.getenv("MONGODB_HOST", "mongodb-service")
MONGODB_REPLICA_SET = os.getenv("MONGODB_REPLICA_SET", "rs0")
MONGODB_AUTH_SOURCE = os.getenv("MONGODB_AUTH_SOURCE", "admin")

# 공유 클라이언트 인스턴스 생성
_mongo_client = None

def get_mongo_client():
    """
    MongoDB 클라이언트 객체를 반환
    """
    global _mongo_client
    
    if _mongo_client is None:
        connection_string = f"mongodb://{os.getenv('MONGODB_USERNAME')}:{os.getenv('MONGODB_PASSWORD')}@{MONGODB_HOST}:27017/?replicaSet={MONGODB_REPLICA_SET}&authSource={MONGODB_AUTH_SOURCE}"
        _mongo_client = AsyncIOMotorClient(connection_string)
    
    return _mongo_client

async def get_users_collection() -> AgnosticCollection:
    try:
        mongo_client = get_mongo_client()
        db = mongo_client["user_database"]
        users_collection = db.get_collection("users")
        logger.info("MongoDB connection successful")
        return users_collection
    except Exception as e:
        logger.error(f"MongoDB connection error: {e}")
        return None

async def get_db():
    """
    FastAPI 의존성 주입을 위한 DB 연결 함수 (컬렉션 반환)
    """
    try:
        collection = await get_users_collection()
        if collection is None:
            raise Exception("Failed to connect to MongoDB")
        return collection
    except Exception as e:
        logger.error(f"Database connection failed: {str(e)}")
        raise
