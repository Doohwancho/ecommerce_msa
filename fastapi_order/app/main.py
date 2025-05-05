from fastapi import FastAPI, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from app.api.api import api_router
from app.config.database import Base, async_engine, AsyncSessionLocal
from app.services.kafka_service import init_kafka_consumer, stop_kafka_consumer, kafka_consumer
import logging
import asyncio
import uvicorn
from contextlib import asynccontextmanager
from sqlalchemy import text, MetaData, select
from app.services.order_manager import OrderManager
import os

from app.models.order import Order, OrderItem, OrderStatus
from app.models.failed_event import FailedEvent
from app.models.outbox import Outbox

from fastapi.responses import JSONResponse


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
        await safe_create_tables_if_not_exist(conn)
    
    # Initialize Kafka consumer for payment events
    await init_kafka_consumer()
    
    # Initialize OrderManager with a new session for application-level operations
    async with AsyncSessionLocal() as session:
        order_manager = OrderManager(session)
        
        # Store order_manager in app state
        app.state.order_manager = order_manager
        
        yield
        
        # Cleanup
        await stop_kafka_consumer()
        await order_manager.close()

# Dependency to get OrderManager
async def get_order_manager() -> OrderManager:
    return app.state.order_manager

# Create application with lifespan handler
app = FastAPI(title="Order Service API", lifespan=lifespan)

# API router registration
app.include_router(api_router, prefix="/api")

# @app.get("/health")
# def health_check():
#     logger.info("Health check endpoint called")
#     return {"status": "OK"}

@app.get("/health/live")
async def liveness():
    """
    Liveness probe - 컨테이너가 살아있는지 확인
    """
    return {"status": "alive"}

@app.get("/health/ready")
async def readiness():
    """
    Readiness probe - 서비스가 요청을 처리할 준비가 되었는지 확인
    """
    errors = []
    status = {}
    
    # 1. MySQL DB 연결 확인
    try:
        async with AsyncSessionLocal() as session:
            from sqlalchemy import text
            result = await session.execute(text("SELECT 1"))
            status["mysql"] = "connected"
    except Exception as e:
        logger.error(f"MySQL connection failed: {str(e)}")
        errors.append(f"MySQL: {str(e)}")
        status["mysql"] = "failed"
    
    # 2. Kafka 연결 상태 확인 - kafka_consumer 글로벌 변수 사용
    try:
        # app.services.kafka_service에서 가져온 글로벌 변수 사용
        from app.services.kafka_service import kafka_consumer
        
        # 연결 상태 확인 로직 개선 - 예시: 초기화 여부만 확인
        if kafka_consumer is not None:
            status["kafka"] = "running"
        else:
            status["kafka"] = "initialized"  # 여기에서는 초기화 여부만 확인하고 에러로 취급하지 않음
    except ImportError as e:
        logger.error(f"Kafka module import error: {str(e)}")
        status["kafka"] = "import_error"  # 에러 발생해도 ready로 간주
    except Exception as e:
        logger.error(f"Kafka status check failed: {str(e)}")
        status["kafka"] = "check_failed"  # 에러 발생해도 ready로 간주
    
    # 3. 결과 반환 - Kafka 오류가 있어도 준비 상태로 간주 (프로덕션에서는 요구사항에 따라 조정)
    if errors and all("mysql" in error for error in errors):  # MySQL 오류만 심각한 오류로 처리
        return JSONResponse(
            status_code=503,
            content={"status": "not ready", "details": status, "errors": errors}
        )
    
    return {"status": "ready", "details": status}

@app.get("/test-connections")
async def test_connections():
    """
    모든 외부 연결을 테스트하는 엔드포인트 (디버깅용)
    """
    result = {}
    
    # MySQL 연결 테스트
    try:
        async with AsyncSessionLocal() as session:
            from sqlalchemy import text
            query_result = await session.execute(text("SELECT 1"))
            row = query_result.fetchone()
            result["mysql"] = {"connected": True, "value": row[0] if row else None}
    except Exception as e:
        result["mysql"] = {"error": str(e)}
    
    # Kafka 상태 테스트 - 직접 모듈에서 가져오기
    try:
        # 모듈 직접 import
        from app.services.kafka_service import kafka_consumer
        
        if kafka_consumer is not None:
            # Kafka 내부 상태 로깅
            logger.info(f"Kafka consumer instance: {kafka_consumer}")
            logger.info(f"Kafka consumer attributes: {dir(kafka_consumer)}")
            
            # 상태 확인
            is_running = getattr(kafka_consumer, 'running', False)
            subscribed_topics = list(getattr(kafka_consumer, 'handlers', {}).keys())
            
            result["kafka"] = {
                "status": "running" if is_running else "initialized",
                "topics": subscribed_topics
            }
        else:
            result["kafka"] = {"status": "not initialized"}
    except ImportError as e:
        result["kafka"] = {"error": f"Import error: {str(e)}"}
    except Exception as e:
        result["kafka"] = {"error": f"Error checking Kafka status: {str(e)}"}
    
    return result

@app.get("/debug-kafka")
async def debug_kafka():
    """Kafka 상태 디버깅을 위한 엔드포인트"""
    result = {}
    
    # 1. 모듈 임포트 시도
    try:
        import sys
        import app.services.kafka_service
        
        # 모듈 정보
        result["module_info"] = {
            "path": str(app.services.kafka_service.__file__),
            "loaded": "kafka_service" in sys.modules
        }
        
        # 2. 모듈 내 변수 확인
        try:
            # 실행 시 임포트
            from app.services.kafka_service import kafka_consumer
            
            # Kafka 소비자 정보
            if kafka_consumer:
                result["kafka_consumer"] = {
                    "type": str(type(kafka_consumer)),
                    "dir": str(dir(kafka_consumer)),
                    "has_running": hasattr(kafka_consumer, "running"),
                    "running": getattr(kafka_consumer, "running", None)
                }
            else:
                result["kafka_consumer"] = None
                
        except Exception as e:
            result["import_error"] = str(e)
            
    except Exception as e:
        result["module_error"] = str(e)
        
    return result

@app.get("/")
def read_root():
    logger.info("Root endpoint called")
    return {"message": "Welcome to the Order Service API"}

if __name__ == "__main__":
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, log_level="info")