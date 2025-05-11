import os
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

#################################################
## . Mysql 
#################################################

# Database configuration
MYSQL_USER = os.getenv('MYSQL_USER', 'root')
MYSQL_PASSWORD = os.getenv('MYSQL_PASSWORD', 'root')
# before replica set
# MYSQL_HOST = os.getenv('MYSQL_HOST', 'mysql-service')

# MySQL Router 
MYSQL_ROUTER_HOST = os.getenv('MYSQL_ROUTER_HOST', 'mysql-router-access')
MYSQL_ROUTER_RW_PORT = os.getenv('MYSQL_ROUTER_RW_PORT', '6446')
MYSQL_ROUTER_RO_PORT = os.getenv('MYSQL_ROUTER_RO_PORT', '6447')

# after replica set
MYSQL_PORT = os.getenv('MYSQL_PORT', '3306')
MYSQL_DATABASE = os.getenv('MYSQL_DATABASE', 'product_category')

# before replica set
# SQLALCHEMY_DATABASE_URL = f"mysql+aiomysql://{MYSQL_USER}:{MYSQL_PASSWORD}@{MYSQL_HOST}:{MYSQL_PORT}/{MYSQL_DATABASE}"

# after replica set
PRIMARY_URL = f"mysql+aiomysql://{MYSQL_USER}:{MYSQL_PASSWORD}@{MYSQL_ROUTER_HOST}:{MYSQL_ROUTER_RW_PORT}/{MYSQL_DATABASE}"
write_engine = create_async_engine(
    PRIMARY_URL,
    pool_pre_ping=True,
    pool_recycle=3600,
    echo=True
)

# 읽기 작업용 엔진 (Secondary)
SECONDARY_URL = f"mysql+aiomysql://{MYSQL_USER}:{MYSQL_PASSWORD}@{MYSQL_ROUTER_HOST}:{MYSQL_ROUTER_RO_PORT}/{MYSQL_DATABASE}"
read_engine = create_async_engine(
    SECONDARY_URL,
    pool_pre_ping=True,
    pool_recycle=3600,
    echo=True
)

# # Create async engine
# async_engine = create_async_engine(
#     SQLALCHEMY_DATABASE_URL,
#     pool_pre_ping=True,
#     pool_recycle=3600,
#     echo=True
# )

async_engine = write_engine


# # Create async session factory
# AsyncSessionLocal = sessionmaker(
#     bind=async_engine,
#     class_=AsyncSession,
#     expire_on_commit=False,
#     autocommit=False,
#     autoflush=False
# )

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



# Create base class for models
Base = declarative_base()

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
