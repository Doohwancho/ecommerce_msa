import os
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from motor.motor_asyncio import AsyncIOMotorClient
from motor.core import AgnosticCollection

# MySQL 비동기 설정
MYSQL_USER = os.getenv("MYSQL_USER", "root")
MYSQL_PASSWORD = os.getenv("MYSQL_PASSWORD", "root")
MYSQL_HOST = os.getenv("MYSQL_HOST", "mysql-service")
MYSQL_DATABASE = os.getenv("MYSQL_DATABASE", "product_category")
SQLALCHEMY_DATABASE_URL = f"mysql+aiomysql://{MYSQL_USER}:{MYSQL_PASSWORD}@{MYSQL_HOST}/{MYSQL_DATABASE}?charset=utf8mb4"

engine = create_async_engine(SQLALCHEMY_DATABASE_URL)
async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
Base = declarative_base()

# mongodb 연결 설정
MONGODB_HOST = os.getenv("MONGODB_HOST", "mongodb-service")
MONGODB_REPLICA_SET = os.getenv("MONGODB_REPLICA_SET", "rs0")
MONGODB_AUTH_SOURCE = os.getenv("MONGODB_AUTH_SOURCE", "admin")



# MongoDB 비동기 설정
async def get_product_collection() -> AgnosticCollection:
    try:
        # MongoDB 연결 설정
        mongo_client = AsyncIOMotorClient(
            # before replica set
            # f"mongodb://{os.getenv('MONGODB_USERNAME')}:{os.getenv('MONGODB_PASSWORD')}@{os.getenv('MONGODB_URL')}"
            # after replica set
            # f"mongodb://{os.getenv('MONGODB_USERNAME')}:{os.getenv('MONGODB_PASSWORD')}@mongodb-stateful-0.mongodb-service.default.svc.cluster.local:27017,mongodb-stateful-1.mongodb-service.default.svc.cluster.local:27017/?replicaSet=rs0&authSource=admin"
            f"mongodb://{os.getenv('MONGODB_USERNAME')}:{os.getenv('MONGODB_PASSWORD')}@{MONGODB_HOST}:27017/?replicaSet={MONGODB_REPLICA_SET}&authSource={MONGODB_AUTH_SOURCE}"
        )
        # 명시적으로 데이터베이스와 컬렉션 생성
        mongo_db = mongo_client.my_db
        # 컬렉션이 존재하는지 확인하고 없으면 생성
        if "products" not in await mongo_db.list_collection_names():
            await mongo_db.create_collection("products")
            print("Created products collection")
        
        product_collection = mongo_db.products
        print("MongoDB connection successful and collection verified")
        return product_collection
    except Exception as e:
        print(f"MongoDB connection error: {e}")
        return None

# MySQL 비동기 설정
async def get_async_mysql_db() -> AsyncSession:
    async with async_session() as session:
        try:
            yield session
        finally:
            await session.close()

async def get_mysql_db() -> AsyncSession:
    return async_session()