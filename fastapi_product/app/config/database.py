import os
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from motor.motor_asyncio import AsyncIOMotorClient
from motor.core import AgnosticCollection
import logging

logger = logging.getLogger(__name__)

#################################################
## . Mysql 
#################################################

# MySQL 비동기 설정
MYSQL_USER = os.getenv("MYSQL_USER", "root")
MYSQL_PASSWORD = os.getenv("MYSQL_PASSWORD", "root")
# before replica set
# MYSQL_HOST = os.getenv("MYSQL_HOST", "mysql-service")
# after replica set
# MySQL Router 
MYSQL_ROUTER_HOST = os.getenv('MYSQL_ROUTER_HOST', 'mycluster')
MYSQL_ROUTER_RW_PORT = os.getenv('MYSQL_ROUTER_RW_PORT', '6446')
MYSQL_ROUTER_RO_PORT = os.getenv('MYSQL_ROUTER_RO_PORT', '6447')

MYSQL_DATABASE = os.getenv("MYSQL_DATABASE", "product_category")
# before replica set
# SQLALCHEMY_DATABASE_URL = f"mysql+aiomysql://{MYSQL_USER}:{MYSQL_PASSWORD}@{MYSQL_HOST}/{MYSQL_DATABASE}?charset=utf8mb4"
# after replica set
# 쓰기 작업용 엔진 (Primary)
PRIMARY_URL = f"mysql+aiomysql://{MYSQL_USER}:{MYSQL_PASSWORD}@{MYSQL_ROUTER_HOST}:{MYSQL_ROUTER_RW_PORT}/{MYSQL_DATABASE}"
logger.info("MySQL Primary URL configured.", extra={"url_type": "primary", "host": MYSQL_ROUTER_HOST, "port": MYSQL_ROUTER_RW_PORT, "database": MYSQL_DATABASE})
write_engine = create_async_engine(
    PRIMARY_URL,
    pool_pre_ping=True,
    pool_recycle=3600,
    echo=False
)

# 읽기 작업용 엔진 (Secondary)
SECONDARY_URL = f"mysql+aiomysql://{MYSQL_USER}:{MYSQL_PASSWORD}@{MYSQL_ROUTER_HOST}:{MYSQL_ROUTER_RO_PORT}/{MYSQL_DATABASE}"
logger.info("MySQL Secondary URL configured.", extra={"url_type": "secondary", "host": MYSQL_ROUTER_HOST, "port": MYSQL_ROUTER_RO_PORT, "database": MYSQL_DATABASE})
read_engine = create_async_engine(
    SECONDARY_URL,
    pool_pre_ping=True,
    pool_recycle=3600,
    echo=False
)

engine = write_engine


# 세션 팩토리 생성
WriteSessionLocal = sessionmaker(
    bind=write_engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False
)
logger.info("MySQL WriteSessionLocal created.")

ReadSessionLocal = sessionmaker(
    bind=read_engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False
)
logger.info("MySQL ReadSessionLocal created.")

# 기존 호환성을 위한 기본 세션(쓰기 세션으로 설정)
AsyncSessionLocal = WriteSessionLocal

Base = declarative_base()


# 쓰기 작업용 세션 (CUD 작업)
async def get_write_db():
    async with WriteSessionLocal() as session:
        try:
            yield session
        except Exception as e:
            logger.error("Error in get_write_db session context.", extra={"error": str(e)}, exc_info=True)
            raise
        finally:
            await session.close()

# 읽기 작업용 세션 (R 작업)
async def get_read_db():
    async with ReadSessionLocal() as session:
        try:
            yield session
        except Exception as e:
            logger.error("Error in get_read_db session context.", extra={"error": str(e)}, exc_info=True)
            raise
        finally:
            await session.close()


# MySQL 비동기 설정 (호환성)
async def get_async_mysql_db() -> AsyncSession:
    async with WriteSessionLocal() as session:
        try:
            yield session
        except Exception as e:
            logger.error("Error in get_async_mysql_db session context.", extra={"error": str(e)}, exc_info=True)
            raise
        finally:
            await session.close()


# 직접 세션 객체 반환 함수
async def get_mysql_db():
    """
    MySQL 세션을 직접 반환 (쓰기 세션)
    """
    return WriteSessionLocal()

async def get_read_mysql_db():
    """
    MySQL 읽기 세션을 직접 반환
    """
    return ReadSessionLocal()

#################################################
## . Mongodb 
#################################################

# mongodb 연결 설정
MONGODB_HOST = os.getenv("MONGODB_HOST", "mongodb-stateful-0.mongodb-service,mongodb-stateful-1.mongodb-service,mongodb-stateful-2.mongodb-service")
MONGODB_REPLICA_SET = os.getenv("MONGODB_REPLICA_SET", "rs0")
MONGODB_AUTH_SOURCE = os.getenv("MONGODB_AUTH_SOURCE", "admin")
MONGODB_USERNAME = os.getenv("MONGODB_USERNAME", "username") # dXNlcm5hbWU=
MONGODB_PASSWORD = os.getenv("MONGODB_PASSWORD", "password") # cGFzc3dvcmQ=

# 공유 MongoDB 클라이언트
_write_mongo_client = None
_read_mongo_client = None

def get_write_mongo_client():
    """
    Primary MongoDB 클라이언트 객체를 반환 (쓰기 작업용)
    """
    global _write_mongo_client
    
    if _write_mongo_client is None:
        connection_string = f"mongodb://{MONGODB_USERNAME}:{MONGODB_PASSWORD}@{MONGODB_HOST}/my_db?replicaSet={MONGODB_REPLICA_SET}&authSource={MONGODB_AUTH_SOURCE}&readPreference=primary"
        try:
            _write_mongo_client = AsyncIOMotorClient(connection_string)
            logger.info("MongoDB write client initialized.", extra={"hosts": MONGODB_HOST, "replica_set": MONGODB_REPLICA_SET, "read_preference": "primary"})
        except Exception as e:
            logger.error("Failed to initialize MongoDB write client.", 
                         extra={"connection_string_partial_host": MONGODB_HOST, "error": str(e)}, exc_info=True)
            raise # Re-raise after logging
    
    return _write_mongo_client

def get_read_mongo_client():
    """
    Secondary MongoDB 클라이언트 객체를 반환 (읽기 작업용)
    """
    global _read_mongo_client
    
    if _read_mongo_client is None:
        connection_string = f"mongodb://{MONGODB_USERNAME}:{MONGODB_PASSWORD}@{MONGODB_HOST}/my_db?replicaSet={MONGODB_REPLICA_SET}&authSource={MONGODB_AUTH_SOURCE}&readPreference=secondary"
        try:
            _read_mongo_client = AsyncIOMotorClient(connection_string)
            logger.info("MongoDB read client initialized.", extra={"hosts": MONGODB_HOST, "replica_set": MONGODB_REPLICA_SET, "read_preference": "secondary"})
        except Exception as e:
            logger.error("Failed to initialize MongoDB read client.", 
                         extra={"connection_string_partial_host": MONGODB_HOST, "error": str(e)}, exc_info=True)
            raise # Re-raise after logging
    
    return _read_mongo_client

# MongoDB 비동기 설정
async def get_write_product_collection() -> AgnosticCollection:
    """
    쓰기 작업용 MongoDB 컬렉션 반환
    """
    try:
        mongo_client = get_write_mongo_client()
        mongo_db = mongo_client.my_db
        
        # 컬렉션이 존재하는지 확인하고 없으면 생성
        collection_names = await mongo_db.list_collection_names()
        if "products" not in collection_names:
            await mongo_db.create_collection("products")
            logger.info("Created MongoDB 'products' collection for write operations.")
        
        product_collection = mongo_db.products
        # Consider a lightweight ping or server_info call if connection verification is critical here
        # logger.info("MongoDB write connection successful and collection verified.") # This might be too verbose
        return product_collection
    except Exception as e:
        logger.error("Error getting MongoDB write product collection.", extra={"error": str(e)}, exc_info=True)
        return None

async def get_read_product_collection() -> AgnosticCollection:
    """
    읽기 작업용 MongoDB 컬렉션 반환
    """
    try:
        mongo_client = get_read_mongo_client()
        mongo_db = mongo_client.my_db
        product_collection = mongo_db.products
        # logger.info("MongoDB read connection successful.") # Potentially verbose
        return product_collection
    except Exception as e:
        logger.error("Error getting MongoDB read product collection.", extra={"error": str(e)}, exc_info=True)
        return None