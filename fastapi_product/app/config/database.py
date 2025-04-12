import os
from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

# 동기 for mongodb
# from pymongo import MongoClient

# 비동기 for mongodb
from motor.motor_asyncio import AsyncIOMotorClient

# MySQL 설정
MYSQL_USER = os.getenv("MYSQL_USER", "root")
MYSQL_PASSWORD = os.getenv("MYSQL_PASSWORD", "password")
MYSQL_HOST = os.getenv("MYSQL_HOST", "mysql-service")
MYSQL_DATABASE = os.getenv("MYSQL_DATABASE", "product_category")
SQLALCHEMY_DATABASE_URL = f"mysql+pymysql://{MYSQL_USER}:{MYSQL_PASSWORD}@{MYSQL_HOST}/{MYSQL_DATABASE}?charset=utf8mb4"

engine = create_engine(SQLALCHEMY_DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

# # MongoDB "동기" 설정
# try:
#     mongo_client = MongoClient(
#         f"mongodb://{os.getenv('MONGODB_USERNAME')}:{os.getenv('MONGODB_PASSWORD')}@{os.getenv('MONGODB_URL')}"
#     )
#     mongo_db = mongo_client.my_db
#     user_collection = mongo_db.my_collection
#     product_collection = mongo_db.products
#     print("MongoDB connection successful")
# except Exception as e:
#     print(f"MongoDB connection error: {e}")

# MongoDB 비동기 설정
try:
    mongo_client = AsyncIOMotorClient(
        f"mongodb://{os.getenv('MONGODB_USERNAME')}:{os.getenv('MONGODB_PASSWORD')}@{os.getenv('MONGODB_URL')}"
    )
    mongo_db = mongo_client.my_db
    product_collection = mongo_db.products
    print("MongoDB connection successful")
except Exception as e:
    print(f"MongoDB connection error: {e}")


# MySQL 의존성
def get_mysql_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()