from fastapi import FastAPI
from fastapi.responses import JSONResponse
# from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.ext.asyncio import AsyncSession
from app.api.api import api_router
from app.config.payment_database import Base, write_engine, read_engine, WriteSessionLocal
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

# PaymentManager 인스턴스
payment_manager = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    """애플리케이션 생명주기 관리"""
    global payment_manager
    try:
        # 시작 시 Primary DB에 테이블 생성
        async with write_engine.begin() as conn:
            await safe_create_tables_if_not_exist(conn)
        
        # Secondary DB에도 테이블 생성
        async with read_engine.begin() as conn:
            await safe_create_tables_if_not_exist(conn)
        
        # PaymentManager 초기화
        payment_manager = PaymentManager()
        
        # Kafka 초기화
        bootstrap_servers = os.getenv("KAFKA_BOOTSTRAP_SERVERS")
        group_id = "payment-service-group"
        await payment_manager.initialize_kafka(bootstrap_servers, group_id)
        logger.info("Kafka consumer initialized")
        
        yield
        
    finally:
        # 종료 시 Kafka consumer 정리
        if payment_manager:
            await payment_manager.stop()
            logger.info("Kafka consumer stopped")

# FastAPI 애플리케이션 생성
app = FastAPI(
    title="Payment Service API",
    description="결제 서비스 API",
    version="1.0.0",
    lifespan=lifespan
)

# # CORS 설정
# app.add_middleware(
#     CORSMiddleware,
#     allow_origins=["*"],
#     allow_credentials=True,
#     allow_methods=["*"],
#     allow_headers=["*"],
# )

# API 라우터 등록
app.include_router(api_router, prefix="/api")

# 라이브니스 프로브
@app.get("/health/live")
async def liveness():
    """
    Liveness probe - 컨테이너가 살아있는지 확인
    """
    return {"status": "alive"}

# 레디니스 프로브
@app.get("/health/ready")
async def readiness():
    """
    Readiness probe - 서비스가 요청을 처리할 준비가 되었는지 확인
    """
    errors = []
    status = {}
    
    # 1. MySQL DB 연결 확인 (Write DB 사용)
    try:
        async with WriteSessionLocal() as session:
            result = await session.execute(text("SELECT 1"))
            status["mysql"] = "connected"
    except Exception as e:
        logger.error(f"MySQL connection failed: {str(e)}")
        errors.append(f"MySQL: {str(e)}")
        status["mysql"] = "failed"
    
    # 2. Kafka 연결 상태 확인
    try:
        if hasattr(payment_manager, 'kafka_consumer') and payment_manager.kafka_consumer is not None:
            status["kafka"] = "running"
        else:
            status["kafka"] = "initialized"
    except Exception as e:
        logger.error(f"Kafka status check failed: {str(e)}")
        status["kafka"] = "check_failed"
    
    # 결과 반환 - MySQL 오류만 심각한 오류로 처리
    if errors and any("mysql" in error for error in errors):
        return JSONResponse(
            status_code=503,
            content={"status": "not ready", "details": status, "errors": errors}
        )
    
    return {"status": "ready", "details": status}

# 테스트 연결 엔드포인트
@app.get("/test-connections")
async def test_connections():
    """
    모든 외부 연결을 테스트하는 엔드포인트 (디버깅용)
    """
    result = {}
    
    # MySQL 연결 테스트 (Write DB 사용)
    try:
        async with WriteSessionLocal() as session:
            query_result = await session.execute(text("SELECT 1"))
            row = query_result.fetchone()
            result["mysql"] = {"connected": True, "value": row[0] if row else None}
    except Exception as e:
        result["mysql"] = {"error": str(e)}
    
    # Kafka 상태 테스트
    try:
        if hasattr(payment_manager, 'kafka_consumer') and payment_manager.kafka_consumer is not None:
            kafka_consumer = payment_manager.kafka_consumer
            handlers = getattr(kafka_consumer, 'handlers', {})
            
            result["kafka"] = {
                "status": "running",
                "handlers": {
                    topic: list(event_handlers.keys()) if isinstance(event_handlers, dict) else "unknown"
                    for topic, event_handlers in handlers.items()
                } if isinstance(handlers, dict) else "unknown"
            }
        else:
            result["kafka"] = {"status": "not initialized"}
    except Exception as e:
        result["kafka"] = {"error": str(e)}
    
    return result

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