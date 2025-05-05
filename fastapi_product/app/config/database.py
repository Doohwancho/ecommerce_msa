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
MYSQL_PRIMARY_HOST = os.getenv('MYSQL_PRIMARY_HOST', 'mysql-0.mysql-headless')
MYSQL_SECONDARY_HOST = os.getenv('MYSQL_SECONDARY_HOST', 'mysql-1.mysql-headless')
MYSQL_PORT = os.getenv('MYSQL_PORT', '3306')
MYSQL_DATABASE = os.getenv("MYSQL_DATABASE", "product_category")
# before replica set
# SQLALCHEMY_DATABASE_URL = f"mysql+aiomysql://{MYSQL_USER}:{MYSQL_PASSWORD}@{MYSQL_HOST}/{MYSQL_DATABASE}?charset=utf8mb4"
# after replica set
# 쓰기 작업용 엔진 (Primary)
PRIMARY_URL = f"mysql+aiomysql://{MYSQL_USER}:{MYSQL_PASSWORD}@{MYSQL_PRIMARY_HOST}:{MYSQL_PORT}/{MYSQL_DATABASE}"
write_engine = create_async_engine(
    PRIMARY_URL,
    pool_pre_ping=True,
    pool_recycle=3600,
    echo=True
)

# 읽기 작업용 엔진 (Secondary)
SECONDARY_URL = f"mysql+aiomysql://{MYSQL_USER}:{MYSQL_PASSWORD}@{MYSQL_SECONDARY_HOST}:{MYSQL_PORT}/{MYSQL_DATABASE}"
read_engine = create_async_engine(
    SECONDARY_URL,
    pool_pre_ping=True,
    pool_recycle=3600,
    echo=True
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

ReadSessionLocal = sessionmaker(
    bind=read_engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False
)

# 기존 호환성을 위한 기본 세션(쓰기 세션으로 설정)
AsyncSessionLocal = WriteSessionLocal

Base = declarative_base()


# 쓰기 작업용 세션 (CUD 작업)
async def get_write_db():
    async with WriteSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()

# 읽기 작업용 세션 (R 작업)
async def get_read_db():
    async with ReadSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()


# MySQL 비동기 설정 (호환성)
async def get_async_mysql_db() -> AsyncSession:
    async with WriteSessionLocal() as session:
        try:
            yield session
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
MONGODB_HOST = os.getenv("MONGODB_HOST", "mongodb-service")
MONGODB_REPLICA_SET = os.getenv("MONGODB_REPLICA_SET", "rs0")
MONGODB_AUTH_SOURCE = os.getenv("MONGODB_AUTH_SOURCE", "admin")
MONGODB_USERNAME = os.getenv("MONGODB_USERNAME", "username") # dXNlcm5hbWU=
MONGODB_PASSWORD = os.getenv("MONGODB_PASSWORD", "password") # cGFzc3dvcmQ=

# 공유 MongoDB 클라이언트
_mongo_client = None


def get_mongo_client():
    """
    MongoDB 클라이언트 객체를 반환
    """
    global _mongo_client
    
    if _mongo_client is None:
        connection_string = f"mongodb://{MONGODB_USERNAME}:{MONGODB_PASSWORD}@{MONGODB_HOST}:27017/?replicaSet={MONGODB_REPLICA_SET}&authSource={MONGODB_AUTH_SOURCE}"
        _mongo_client = AsyncIOMotorClient(connection_string)
        logger.info("MongoDB client initialized")
    
    return _mongo_client

# MongoDB 비동기 설정
async def get_product_collection() -> AgnosticCollection:
    try:
        # 공유 클라이언트 사용
        mongo_client = get_mongo_client()
        # 명시적으로 데이터베이스와 컬렉션 생성
        mongo_db = mongo_client.my_db
        
        # 컬렉션이 존재하는지 확인하고 없으면 생성
        collection_names = await mongo_db.list_collection_names()
        if "products" not in collection_names:
            await mongo_db.create_collection("products")
            logger.info("Created products collection")
        
        product_collection = mongo_db.products
        logger.info("MongoDB connection successful and collection verified")
        return product_collection
    except Exception as e:
        logger.error(f"MongoDB connection error: {e}")
        return None