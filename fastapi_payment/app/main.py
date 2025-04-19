from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncSession
from app.api.api import api_router
from app.config.payment_database import Base, async_engine
from app.services.payment_manager import PaymentManager
from contextlib import asynccontextmanager
from app.config.payment_logging import logger
from sqlalchemy import text
import os

async def safe_create_tables_if_not_exist(conn):
    """테이블이 존재하지 않는 경우에만 생성"""
    try:
        # 기존 테이블 확인
        result = await conn.execute(text("SHOW TABLES"))
        existing_tables = [row[0] for row in result]
        logger.info(f"Existing tables: {existing_tables}")
        
        # SQLAlchemy의 checkfirst 옵션 사용
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
        logger.error(f"Error creating tables: {e}")
        raise

# 전역 변수로 PaymentManager 인스턴스 생성
payment_manager = PaymentManager()

@asynccontextmanager
async def lifespan(app: FastAPI):
    """애플리케이션 생명주기 관리"""
    # 시작 시 테이블 생성
    async with async_engine.begin() as conn:
        await safe_create_tables_if_not_exist(conn)
    
    # Kafka 초기화
    bootstrap_servers = os.getenv("KAFKA_BOOTSTRAP_SERVERS")
    group_id = "payment-service-group"
    await payment_manager.initialize_kafka(bootstrap_servers, group_id)
    logger.info("Kafka consumer initialized")
    
    yield
    
    # 종료 시 Kafka consumer 정리
    await payment_manager.stop()
    logger.info("Kafka consumer stopped")

# FastAPI 애플리케이션 생성
app = FastAPI(
    title="Payment Service API",
    description="결제 서비스 API",
    version="1.0.0",
    lifespan=lifespan
)

# API 라우터 등록
app.include_router(api_router, prefix="/api")

# 헬스 체크 엔드포인트
@app.get("/health")
async def health_check():
    """서비스 상태 확인"""
    return {"status": "healthy"}

# 루트 엔드포인트
@app.get("/")
async def read_root():
    """API 루트 엔드포인트"""
    return {
        "message": "Welcome to Payment Service API",
        "docs": "/docs",
        "redoc": "/redoc"
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host="0.0.0.0", port=8004, reload=True)