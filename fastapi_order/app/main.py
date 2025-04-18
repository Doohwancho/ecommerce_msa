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
# from app.models.outbox import Outbox

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# create table if not exist
async def safe_create_tables_if_not_exist(conn):
    try:
        # 테이블 존재 여부 확인
        result = await conn.execute(text("SHOW TABLES"))
        existing_tables = [row[0] for row in result]
        logger.info(f"Existing tables: {existing_tables}")
        
        # SQLAlchemy의 checkfirst 옵션 사용 (create_all 내부적으로 IF NOT EXISTS 사용)
        await conn.run_sync(lambda sync_conn: Base.metadata.create_all(
            sync_conn, 
            checkfirst=True  # 테이블이 이미 존재하면 건너뛰기
        ))
        
        logger.info("Tables created or already exist")
        
        # 생성 후 테이블 확인
        result = await conn.execute(text("SHOW TABLES"))
        tables = [row[0] for row in result]
        logger.info(f"Tables after creation: {tables}")
        
    except Exception as e:
        logger.error(f"Error in safe_create_tables_if_not_exist: {e}")
        raise

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Create database tables
    async with async_engine.begin() as conn:
        # await safe_create_tables(conn)
        await safe_create_tables_if_not_exist(conn)
    
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
