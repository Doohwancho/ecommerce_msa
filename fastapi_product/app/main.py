from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncSession
from app.api.api import api_router
from app.config.database import Base, engine
from app.services.product_manager import ProductManager
from app.config.elasticsearch import elasticsearch_config
from contextlib import asynccontextmanager
from app.config.logging import logger
from sqlalchemy import text
import os
import asyncio
from app.grpc.product_server import serve as grpc_serve


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

# 전역 변수로 ProductManager 인스턴스 생성
product_manager = ProductManager()

@asynccontextmanager
async def lifespan(app: FastAPI):
    """애플리케이션 생명주기 관리"""
    # 시작 시 테이블 생성
    async with engine.begin() as conn:
        await safe_create_tables_if_not_exist(conn)
    
    # Elasticsearch 초기화
    try:
        await elasticsearch_config.get_client()
        logger.info("Elasticsearch initialized")
    except Exception as e:
        logger.error(f"Failed to initialize Elasticsearch: {e}")
        raise
    
    # Start gRPC server in background
    grpc_task = asyncio.create_task(grpc_serve())
    logger.info("gRPC server started on port 50051")

    # Kafka 초기화
    bootstrap_servers = os.getenv("KAFKA_BOOTSTRAP_SERVERS")
    group_id = "product-service-group"
    await product_manager.initialize_kafka(bootstrap_servers, group_id)
    logger.info("Kafka consumer initialized")
    
    yield
    
    # 종료 시 Kafka consumer 정리
    await product_manager.stop()
    logger.info("Kafka consumer stopped")

    # Elasticsearch 연결 종료
    await elasticsearch_config.close()
    logger.info("Elasticsearch connection closed")

    # Cancel gRPC task
    if grpc_task:
        grpc_task.cancel()
        try:
            await grpc_task
        except asyncio.CancelledError:
            logger.info("gRPC server stopped")

# FastAPI 애플리케이션 생성
app = FastAPI(
    title="Product Service API",
    description="상품 서비스 API",
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
        "message": "Welcome to Product Service API",
        "docs": "/docs",
        "redoc": "/redoc"
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host="0.0.0.0", port=8004, reload=True)