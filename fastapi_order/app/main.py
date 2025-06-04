# app/main.py
# Python Standard Libraries
import asyncio
from contextlib import asynccontextmanager
import os
import logging # 표준 로깅 임포트

# Third-party Libraries
from fastapi import FastAPI, Depends
from fastapi.responses import JSONResponse
from sqlalchemy import text
# from sqlalchemy.ext.asyncio import AsyncSession # Depends(get_db) 등으로 사용 시 필요

# Application-specific Modules
# 1. Logging and OpenTelemetry Core Initialization (가장 먼저 임포트 및 실행되도록)
from app.core.logging_config import initialize_logging_and_telemetry, get_configured_logger, get_global_logger_provider
# 2. OpenTelemetry Instrumentation Setup (로깅 초기화 후)
from app.config.otel import setup_non_logging_telemetry, instrument_fastapi_app

from app.api.api import api_router
from app.config.database import Base, write_engine, read_engine, WriteSessionLocal # DB 세션
from app.services.kafka_service import init_kafka_consumer, stop_kafka_consumer
from app.services.order_manager import OrderManager

# OrderManager 등에서 사용하는 모델 (테이블 생성 로직에 필요)
from app.models.order import Order, OrderItem, OrderStatus
from app.models.failed_event import FailedEvent
from app.models.outbox import Outbox

# --- 1. 로깅 및 OpenTelemetry 핵심 설정 초기화 ---
# 애플리케이션 시작 시 가장 먼저 호출되어야 함!
initialize_logging_and_telemetry()

# --- 2. 이 모듈(main.py)에서 사용할 로거 가져오기 ---
# 이제 initialize_logging_and_telemetry()가 호출되었으므로 안전하게 설정된 로거를 가져옴
logger = get_configured_logger(__name__) # 또는 get_configured_logger("app.main")

# --- 3. OpenTelemetry 추가 설정 (트레이싱, 주요 라이브러리 계측) ---
# 로깅 및 Provider 설정이 완료된 후 호출
setup_non_logging_telemetry()


# --- DB 테이블 생성 함수 ---
async def safe_create_tables_if_not_exist(engine, engine_name: str):
    # 이 함수 내부의 logger 호출은 이미 설정된 JSON 포맷 로거를 사용
    logger.info(f"Checking tables for {engine_name} engine...")
    try:
        async with engine.connect() as conn: # engine.begin() 대신 connect() 사용 후 명시적 트랜잭션
            # result = await conn.execute(text("SHOW TABLES")) # SHOW TABLES는 트랜잭션 불필요
            # existing_tables = [row[0] for row in result]
            # logger.info(f"Existing tables in {engine_name}: {existing_tables}")
            
            await conn.run_sync(Base.metadata.create_all, checkfirst=True)
            await conn.commit() # 테이블 생성은 DDL이므로 커밋 필요
            logger.info(f"Tables created or already exist for {engine_name} engine.")
            
            # result_after = await conn.execute(text("SHOW TABLES"))
            # tables_after = [row[0] for row in result_after]
            # logger.info(f"Tables after creation in {engine_name}: {tables_after}")
    except Exception as e:
        logger.error(f"Error during table check/creation for {engine_name} engine: {e}", exc_info=True)
        raise

# --- Lifespan 컨텍스트 매니저 ---
@asynccontextmanager
async def lifespan(app_instance: FastAPI): # app_instance 이름 변경 (FastAPI와 구분)
    logger.info("Application startup: Initializing resources...")
    
    await safe_create_tables_if_not_exist(write_engine, "write_engine")
    # await safe_create_tables_if_not_exist(read_engine, "read_engine") # read_engine은 보통 DDL 실행 안 함

    await init_kafka_consumer()
    
    order_manager = OrderManager()
    app_instance.state.order_manager = order_manager
    logger.info("OrderManager initialized and stored in app state.")
    
    # --- !!! 최후의 로그 전송 테스트 (애플리케이션 시작 시) !!! ---
    startup_test_logger = get_configured_logger("app.main.barebones_test")
    startup_test_logger.error( # 에러 레벨로!
        "BAREBONES ES EXPORT TEST - ONLY TIMESTAMP AND MESSAGE SHOULD BE ESSENTIAL"
        # extra 인자 아예 빼버림!
    )
    logger.info("BAREBONES ES EXPORT TEST has been emitted.")

    # LoggerProvider의 force_flush 테스트 (선택적, 디버깅용)
    lp = get_global_logger_provider()
    if lp:
        logger.info("Attempting to force flush LoggerProvider on startup...")
        try:
            lp.force_flush(timeout_millis=10000) # 10초 타임아웃
            logger.info("LoggerProvider force_flush on startup completed.")
        except Exception as e_flush:
            logger.error(f"Error during LoggerProvider force_flush on startup: {e_flush}", exc_info=True)
    else:
        logger.warning("LoggerProvider instance is None at startup, cannot force_flush.")
    # --- 테스트 끝 ---

    yield 
    
    logger.info("Application shutdown: Cleaning up resources...")
    await stop_kafka_consumer()
    if hasattr(app_instance.state, 'order_manager') and app_instance.state.order_manager:
        await app_instance.state.order_manager.close()
    logger.info("Resources cleaned up.")

# --- FastAPI 애플리케이션 생성 ---
# lifespan 컨텍스트 매니저를 FastAPI 앱에 연결
app = FastAPI(title="Order Service API", lifespan=lifespan)

# --- FastAPI 앱 OpenTelemetry 계측 ---
# 로깅, Provider, 기타 계측 설정이 모두 완료된 후 마지막에 호출
instrument_fastapi_app(app) 

# --- API 라우터 등록 ---
app.include_router(api_router, prefix="/api")

# --- 의존성 주입 함수 ---
async def get_order_manager() -> OrderManager:
    if not hasattr(app.state, 'order_manager') or not app.state.order_manager:
        logger.error("OrderManager not found in app state during get_order_manager call.")
        raise RuntimeError("OrderManager not initialized. Check application lifespan.")
    return app.state.order_manager

# --- 기본 Health Check 엔드포인트 ---
@app.get("/health/live", tags=["Health"])
async def liveness():
    return {"status": "alive"}

@app.get("/health/ready", tags=["Health"])
async def readiness():
    # ... (기존 readiness 로직, logger 호출은 이미 설정된 로거 사용) ...
    # logger.info(...) / logger.error(...) 사용
    errors = []
    status_details = {}
    try:
        async with WriteSessionLocal() as session:
            await session.execute(text("SELECT 1"))
            status_details["mysql"] = "connected"
    except Exception as e:
        logger.error(f"MySQL connection failed for readiness probe: {str(e)}", exc_info=True) # 상세 에러
        errors.append(f"MySQL: {str(e)}")
        status_details["mysql"] = "failed"
    
    from app.services.kafka_service import kafka_consumer # 함수 내에서 임포트
    if kafka_consumer and getattr(kafka_consumer, '_running', False): # _running 내부 변수 참조 주의
         status_details["kafka"] = "running"
    elif kafka_consumer:
         status_details["kafka"] = "initialized_not_running"
    else:
         status_details["kafka"] = "not_initialized"

    if status_details.get("mysql") == "failed": # 또는 다른 주요 서비스 실패 시
        logger.warning(f"Readiness probe failed. Details: {status_details}, Errors: {errors}")
        return JSONResponse(
            status_code=503,
            content={"status": "not ready", "details": status_details, "errors": errors}
        )
    logger.debug(f"Readiness probe successful. Details: {status_details}") # 성공은 DEBUG 레벨로
    return {"status": "ready", "details": status_details}

@app.get("/", tags=["Root"])
def read_root():
    logger.info("Root endpoint / called")
    return {"message": "Welcome to the Order Service API"}

# --- uvicorn 실행 (보통 Dockerfile이나 Procfile에서 실행) ---
if __name__ == "__main__":
    # 이 부분은 로컬 개발 시 uvicorn을 직접 실행할 때만 사용됨
    # logging_config.py에서 uvicorn 로거 레벨을 이미 조정했으므로,
    # 여기서 log_level을 다시 설정하면 덮어쓸 수 있음.
    # 기본적으로는 코드 내 설정을 따르도록 log_level 인자 없이 실행하는 것이 좋음.
    uvicorn.run(app, host="0.0.0.0", port=8000)