import os
from motor.motor_asyncio import AsyncIOMotorClient
from motor.core import AgnosticCollection
import logging

logger = logging.getLogger(__name__)

# mongodb 연결 설정
MONGODB_HOST = os.getenv("MONGODB_HOST", "mongodb-stateful-0.mongodb-service,mongodb-stateful-1.mongodb-service,mongodb-stateful-2.mongodb-service")
MONGODB_REPLICA_SET = os.getenv("MONGODB_REPLICA_SET", "rs0")
MONGODB_AUTH_SOURCE = os.getenv("MONGODB_AUTH_SOURCE", "admin")
MONGODB_USERNAME = os.getenv("MONGODB_USERNAME", "username")
MONGODB_PASSWORD = os.getenv("MONGODB_PASSWORD", "password")

# 공유 MongoDB 클라이언트
_write_mongo_client = None
_read_mongo_client = None

def get_write_mongo_client():
    """
    Primary MongoDB 클라이언트 객체를 반환 (쓰기 작업용)
    """
    global _write_mongo_client
    
    if _write_mongo_client is None:
        connection_string = f"mongodb://{MONGODB_USERNAME}:{MONGODB_PASSWORD}@{MONGODB_HOST}/user_database?replicaSet={MONGODB_REPLICA_SET}&authSource={MONGODB_AUTH_SOURCE}&readPreference=primary"
        _write_mongo_client = AsyncIOMotorClient(connection_string)
        logger.info("MongoDB write client initialized.", extra={"db_type": "mongodb", "client_type": "write", "connection_string": connection_string})
    
    return _write_mongo_client

def get_read_mongo_client():
    """
    Secondary MongoDB 클라이언트 객체를 반환 (읽기 작업용)
    """
    global _read_mongo_client
    
    if _read_mongo_client is None:
        connection_string = f"mongodb://{MONGODB_USERNAME}:{MONGODB_PASSWORD}@{MONGODB_HOST}/user_database?replicaSet={MONGODB_REPLICA_SET}&authSource={MONGODB_AUTH_SOURCE}&readPreference=secondary"
        _read_mongo_client = AsyncIOMotorClient(connection_string)
        logger.info("MongoDB read client initialized.", extra={"db_type": "mongodb", "client_type": "read", "connection_string": connection_string})
    
    return _read_mongo_client

async def get_write_users_collection() -> AgnosticCollection:
    """
    쓰기 작업용 MongoDB 컬렉션 반환
    """
    try:
        mongo_client = get_write_mongo_client()
        mongo_db = mongo_client.user_database
        
        # 컬렉션이 존재하는지 확인하고 없으면 생성
        collection_names = await mongo_db.list_collection_names()
        if "users" not in collection_names:
            await mongo_db.create_collection("users")
            logger.info("Created users collection in user_database.", extra={"db_name": "user_database", "collection_name": "users"})
        
        users_collection = mongo_db.users
        logger.info("MongoDB write connection successful and users collection verified.", extra={"db_name": "user_database", "collection_name": "users", "access_type": "write"})
        return users_collection
    except Exception as e:
        logger.error("MongoDB write connection error.", extra={"db_name": "user_database", "collection_name": "users", "access_type": "write", "error": str(e)}, exc_info=True)
        return None

async def get_read_users_collection() -> AgnosticCollection:
    """
    읽기 작업용 MongoDB 컬렉션 반환
    """
    try:
        mongo_client = get_read_mongo_client()
        mongo_db = mongo_client.user_database
        users_collection = mongo_db.users
        logger.info("MongoDB read connection successful for users collection.", extra={"db_name": "user_database", "collection_name": "users", "access_type": "read"})
        return users_collection
    except Exception as e:
        logger.error("MongoDB read connection error.", extra={"db_name": "user_database", "collection_name": "users", "access_type": "read", "error": str(e)}, exc_info=True)
        return None
