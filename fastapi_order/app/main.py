from fastapi import FastAPI, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from app.api.api import api_router
from app.config.database import Base, async_engine, get_async_mysql_db
from app.services.event_retry_service import start_event_retry_service
import logging
import asyncio
import uvicorn
from contextlib import asynccontextmanager
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text, MetaData, select

from app.models.order import Order, OrderItem, OrderStatus
from app.models.failed_event import FailedEvent

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def check_tables_async(conn):
    """테이블 존재 여부를 비동기적으로 확인"""
    result = await conn.execute(text("SHOW TABLES"))
    return [row[0] for row in result]

async def safe_create_tables(conn):
    """테이블을 안전하게 생성"""
    try:
        # 테이블 존재 여부 확인 (비동기적으로 실행)
        existing_tables = await check_tables_async(conn)
        required_tables = ['orders', 'order_items', 'failed_events']
        
        # 필요한 테이블이 모두 존재하는지 확인
        if all(table in existing_tables for table in required_tables):
            logger.info("All required tables already exist")
            return
        
        # 테이블이 일부만 존재하는 경우, 모두 삭제하고 다시 생성
        if any(table in existing_tables for table in required_tables):
            logger.warning("Some tables exist but not all. Dropping all tables...")
            for table in required_tables:
                if table in existing_tables:
                    await conn.execute(text(f"DROP TABLE {table}"))
                    logger.info(f"Dropped table {table}")
        
        # 테이블 생성
        async with async_engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        logger.info("Created all tables")
        
        # 생성 확인 (비동기적으로 실행)
        tables = await check_tables_async(conn)
        logger.info(f"Existing tables: {tables}")
        
        if not all(table in tables for table in required_tables):
            raise RuntimeError("Failed to create all required tables")
            
    except Exception as e:
        logger.error(f"Error creating tables: {e}")
        raise

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Create database tables
    async with async_engine.begin() as conn:
        await safe_create_tables(conn)
    
    # Start event retry service
    asyncio.create_task(start_event_retry_service())
    logger.info("Event retry service started")
    
    yield

# Create application with lifespan handler
app = FastAPI(title="Order Service API", lifespan=lifespan)

# CORS 설정
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# API router registration
app.include_router(api_router, prefix="/api")

@app.get("/health")
def health_check():
    logger.info("Health check endpoint called")
    return {"status": "OK"}

@app.get("/")
def read_root():
    logger.info("Root endpoint called")
    return {"message": "Welcome to the Order Service API"}

if __name__ == "__main__":
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, log_level="info")
