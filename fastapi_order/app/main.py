from fastapi import FastAPI, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from app.api.api import api_router
from app.config.database import Base, write_engine, read_engine, WriteSessionLocal
# setup_telemetry와 instrument_fastapi_app 헬퍼 함수를 함께 임포트합니다.
from app.config.otel import setup_telemetry, instrument_fastapi_app
from app.services.kafka_service import init_kafka_consumer, stop_kafka_consumer # kafka_consumer는 직접 사용하지 않으면 제거 가능
import logging
import asyncio
import uvicorn
from contextlib import asynccontextmanager
from sqlalchemy import text # MetaData, select는 현재 main.py에서 직접 사용 안됨
from app.services.order_manager import OrderManager
import os

# OrderManager에서 사용하는 모델들이므로 여기에 있을 필요는 없지만, 테이블 생성 로직에 필요
from app.models.order import Order, OrderItem, OrderStatus
from app.models.failed_event import FailedEvent
from app.models.outbox import Outbox

from fastapi.responses import JSONResponse

# 로깅 설정 (애플리케이션 진입점에서 한 번 설정하는 것이 좋습니다)
# logging.basicConfig(level=logging.INFO) # 이미 설정되어 있다면 중복 호출 방지
logger = logging.getLogger(__name__)

# uvicorn access 로그만 WARNING 레벨로 설정
uvicorn_access_logger = logging.getLogger("uvicorn.access")
uvicorn_access_logger.setLevel(logging.WARNING)


# --- OpenTelemetry 초기화 ---
# 1. OpenTelemetry 기본 설정 실행 (다른 자동 계측기 포함, FastAPI 제외)
setup_telemetry()


# 테이블 생성 함수 (변경 없음)
async def safe_create_tables_if_not_exist(conn):
    try:
        result = await conn.execute(text("SHOW TABLES"))
        existing_tables = [row[0] for row in result]
        logger.info(f"Existing tables: {existing_tables}")
        
        await conn.run_sync(lambda sync_conn: Base.metadata.create_all(
            sync_conn,
            checkfirst=True
        ))
        logger.info("Tables created or already exist")
        
        result = await conn.execute(text("SHOW TABLES"))
        tables = [row[0] for row in result]
        logger.info(f"Tables after creation: {tables}")
    except Exception as e:
        logger.error(f"Error in safe_create_tables_if_not_exist: {e}")
        raise

# Lifespan 컨텍스트 매니저
@asynccontextmanager
async def lifespan(app: FastAPI):
    # 애플리케이션 시작 시 실행될 코드
    logger.info("Application startup: Initializing resources...")
    
    # DB 테이블 생성
    async with write_engine.begin() as conn:
        await safe_create_tables_if_not_exist(conn)
    async with read_engine.begin() as conn:
        await safe_create_tables_if_not_exist(conn)
    
    # Kafka 소비자 초기화
    # AIOKafkaInstrumentor는 setup_telemetry에서 이미 instrument() 되었으므로, 여기서 생성/시작되는 consumer는 자동 계측됩니다.
    await init_kafka_consumer()
    
    # OrderManager 초기화
    order_manager = OrderManager()
    app.state.order_manager = order_manager # FastAPI 앱 상태에 저장
    logger.info("OrderManager initialized and stored in app state.")
    
    yield # 애플리케이션 실행 구간
    
    # 애플리케이션 종료 시 실행될 코드 (리소스 정리)
    logger.info("Application shutdown: Cleaning up resources...")
    await stop_kafka_consumer()
    if hasattr(app.state, 'order_manager') and app.state.order_manager:
        await app.state.order_manager.close()
    logger.info("Resources cleaned up.")

# --- FastAPI 애플리케이션 생성 및 계측 ---
# 2. FastAPI 앱 인스턴스 생성
app = FastAPI(title="Order Service API", lifespan=lifespan)

# 3. 생성된 FastAPI 앱 인스턴스를 명시적으로 계측
instrument_fastapi_app(app)
logger.info("FastAPI application instrumented by OpenTelemetry.")


# API 라우터 등록
app.include_router(api_router, prefix="/api")

# OrderManager 의존성 주입 함수 (변경 없음)
async def get_order_manager() -> OrderManager:
    # lifespan에서 app.state.order_manager가 설정되었는지 확인하는 로직 추가 가능
    if not hasattr(app.state, 'order_manager') or not app.state.order_manager:
        # 이 경우는 lifespan이 제대로 실행되지 않았거나 문제가 있는 상황
        logger.error("OrderManager not found in app state during get_order_manager call.")
        raise RuntimeError("OrderManager not initialized. Check application lifespan.")
    return app.state.order_manager


@app.get("/health/live")
async def liveness():
    """
    Liveness probe - 컨테이너가 살아있는지 확인
    """
    return {"status": "alive"}

@app.get("/health/ready")
async def readiness():
    errors = []
    status_details = {} # status -> status_details 로 변수명 변경 (명확성)
    
    # DB 연결 확인
    try:
        async with WriteSessionLocal() as session:
            # SQLAlchemyInstrumentor가 이 DB 호출을 자동 계측 (setup_telemetry 이후 실행되므로)
            result = await session.execute(text("SELECT 1"))
            status_details["mysql"] = "connected"
    except Exception as e:
        logger.error(f"MySQL connection failed for readiness probe: {str(e)}")
        errors.append(f"MySQL: {str(e)}")
        status_details["mysql"] = "failed"
    
    # Kafka 연결 상태 확인
    try:
        from app.services.kafka_service import kafka_consumer # 여기서 다시 임포트
        if kafka_consumer and getattr(kafka_consumer, 'running', False): # .running 속성으로 실제 실행 여부 확인
            status_details["kafka"] = "running"
        elif kafka_consumer:
            status_details["kafka"] = "initialized_not_running"
        else:
            status_details["kafka"] = "not_initialized"
    except Exception as e:
        logger.error(f"Kafka status check failed for readiness probe: {str(e)}")
        # Kafka 연결 실패는 서비스 준비 상태에 영향을 줄 수 있음 (요구사항에 따라)
        errors.append(f"Kafka: {str(e)}") 
        status_details["kafka"] = "check_failed"
    
    # 모든 주요 의존성(여기서는 DB)이 준비되었는지 확인
    if "mysql" in status_details and status_details["mysql"] == "failed":
        logger.warning(f"Readiness probe failed: MySQL connection issue. Details: {status_details}, Errors: {errors}")
        return JSONResponse(
            status_code=503,
            content={"status": "not ready", "details": status_details, "errors": errors}
        )
    
    # Kafka도 준비 상태에 영향을 미치도록 하려면 아래 조건 추가
    # if "kafka" in status_details and status_details["kafka"] != "running":
    #     logger.warning(f"Readiness probe failed: Kafka not running. Details: {status_details}, Errors: {errors}")
    #     return JSONResponse(
    #         status_code=503,
    #         content={"status": "not ready", "details": status_details, "errors": errors}
    #     )

    logger.info(f"Readiness probe successful. Details: {status_details}")
    return {"status": "ready", "details": status_details}


@app.get("/test-connections")
async def test_connections():
    """
    모든 외부 연결을 테스트하는 엔드포인트 (디버깅용)
    """
    result = {}
    
    # MySQL 연결 테스트
    try:
        async with WriteSessionLocal() as session:
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