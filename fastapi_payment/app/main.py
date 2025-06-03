from fastapi import FastAPI
from fastapi.responses import JSONResponse
# from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.ext.asyncio import AsyncSession
from app.api.api import api_router
from app.config.payment_database import Base, write_engine, read_engine, WriteSessionLocal
from app.config.otel import setup_telemetry as setup_otel_telemetry
from app.services.payment_manager import PaymentManager
from contextlib import asynccontextmanager
from app.config.payment_logging import setup_logging
from sqlalchemy import text
import os
import logging

# Call setup_logging() to configure logging for the application
setup_logging() 

# Get the logger after setup
logger = logging.getLogger(__name__) 

# uvicorn access 로그만 WARNING 레벨로 설정
uvicorn_access_logger = logging.getLogger("uvicorn.access")
uvicorn_access_logger.setLevel(logging.WARNING)

async def safe_create_tables_if_not_exist(conn, db_type: str):
    """테이블이 존재하지 않는 경우에만 생성"""
    try:
        result = await conn.execute(text("SHOW TABLES"))
        existing_tables = [row[0] for row in result]
        logger.info("Existing tables check.", extra={"db_type": db_type, "tables": existing_tables})
        
        await conn.run_sync(lambda sync_conn: Base.metadata.create_all(
            sync_conn, 
            checkfirst=True
        ))
        
        logger.info("Tables created or already exist.", extra={"db_type": db_type})
        
        result_after = await conn.execute(text("SHOW TABLES"))
        tables_after = [row[0] for row in result_after]
        logger.info("Tables after creation attempt.", extra={"db_type": db_type, "tables": tables_after})
        
    except Exception as e:
        logger.error("Error creating tables.", extra={"db_type": db_type, "error": str(e)}, exc_info=True)
        raise

# PaymentManager 인스턴스
payment_manager = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    """애플리케이션 생명주기 관리"""
    global payment_manager
    logger.info("Application lifespan startup sequence initiated.")
    try:
        logger.info("Creating tables for Primary DB if not exist.")
        async with write_engine.begin() as conn:
            await safe_create_tables_if_not_exist(conn, "PrimaryDB")
        
        logger.info("Creating tables for Secondary DB if not exist.")
        async with read_engine.begin() as conn:
            await safe_create_tables_if_not_exist(conn, "SecondaryDB")
        
        payment_manager = PaymentManager()
        logger.info("PaymentManager initialized.")
        
        bootstrap_servers = os.getenv("KAFKA_BOOTSTRAP_SERVERS")
        group_id = "payment-service-group"
        logger.info("Initializing Kafka for PaymentManager.", extra={"bootstrap_servers": bootstrap_servers, "group_id": group_id})
        await payment_manager.initialize_kafka(bootstrap_servers, group_id)
        logger.info("Kafka consumer initialized for PaymentManager.")
        
        yield
        
    except Exception as e_lifespan:
        logger.critical("Critical error during application startup lifespan event.", 
                        extra={"error": str(e_lifespan)}, exc_info=True)
        raise
    finally:
        logger.info("Application lifespan shutdown sequence initiated.")
        if payment_manager:
            logger.info("Stopping PaymentManager Kafka consumer.")
            await payment_manager.stop()
            logger.info("PaymentManager Kafka consumer stopped.")
        else:
            logger.info("PaymentManager was not initialized, no Kafka consumer to stop.")
        logger.info("Application lifespan shutdown sequence completed.")

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

# Initialize OpenTelemetry
setup_otel_telemetry() 
logger.info("OpenTelemetry (otel.py) setup completed.")

# 라이브니스 프로브
@app.get("/health/live")
async def liveness():
    logger.debug("Liveness probe accessed.")
    return {"status": "alive"}

# 레디니스 프로브
@app.get("/health/ready")
async def readiness():
    logger.info("Readiness probe accessed.")
    errors = []
    status_details = {}
    
    try:
        async with WriteSessionLocal() as session:
            await session.execute(text("SELECT 1"))
            status_details["mysql_primary"] = "connected"
            logger.debug("Readiness probe: MySQL primary connection successful.")
    except Exception as e:
        logger.error("Readiness probe: MySQL primary connection failed.", extra={"error": str(e)}, exc_info=True)
        errors.append(f"MySQL_Primary: {str(e)}")
        status_details["mysql_primary"] = "failed"
    
    try:
        async with read_engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
            status_details["mysql_secondary"] = "connected"
            logger.debug("Readiness probe: MySQL secondary connection successful.")
    except Exception as e:
        logger.warning("Readiness probe: MySQL secondary connection failed.", extra={"error": str(e)}, exc_info=True)
        errors.append(f"MySQL_Secondary: {str(e)}")
        status_details["mysql_secondary"] = "failed"

    try:
        if payment_manager and hasattr(payment_manager, 'kafka_consumer') and payment_manager.kafka_consumer and payment_manager.kafka_consumer._running:
            status_details["kafka_consumer"] = "running"
            logger.debug("Readiness probe: Kafka consumer is running.")
        elif payment_manager and hasattr(payment_manager, 'kafka_consumer') and payment_manager.kafka_consumer:
            status_details["kafka_consumer"] = "initialized_not_running"
            logger.debug("Readiness probe: Kafka consumer is initialized but not confirmed running.")
        else:
            status_details["kafka_consumer"] = "not_initialized_or_payment_manager_missing"
            logger.warning("Readiness probe: Kafka consumer not initialized or PaymentManager missing.")
            errors.append("Kafka_Consumer: Not properly initialized or running")

    except Exception as e:
        logger.error("Readiness probe: Kafka status check failed.", extra={"error": str(e)}, exc_info=True)
        errors.append(f"Kafka_Check: {str(e)}")
        status_details["kafka_consumer"] = "check_failed"
    
    critical_services_failed = status_details.get("mysql_primary") == "failed" or \
                               status_details.get("kafka_consumer") not in ["running", "initialized_not_running"]
    
    if critical_services_failed:
        logger.warning("Readiness probe: Failed due to critical service issues.", extra={"details": status_details, "errors": errors})
        return JSONResponse(
            status_code=503,
            content={"status": "not_ready", "details": status_details, "errors": errors}
        )
    
    logger.info("Readiness probe: Successful.", extra={"details": status_details})
    return {"status": "ready", "details": status_details}

# 테스트 연결 엔드포인트
@app.get("/test-connections")
async def test_connections():
    logger.info("Accessing /test-connections endpoint.")
    result_info = {}
    
    try:
        async with WriteSessionLocal() as session:
            query_result = await session.execute(text("SELECT 1"))
            row = query_result.fetchone()
            result_info["mysql_primary"] = {"connected": True, "value": row[0] if row else None}
            logger.debug("Test connections: MySQL primary successful.")
    except Exception as e:
        logger.error("Test connections: MySQL primary failed.", extra={"error": str(e)}, exc_info=True)
        result_info["mysql_primary"] = {"error": str(e)}

    try:
        async with read_engine.connect() as conn:
            query_result = await conn.execute(text("SELECT 1"))
            row = query_result.fetchone()
            result_info["mysql_secondary"] = {"connected": True, "value": row[0] if row else None}
            logger.debug("Test connections: MySQL secondary successful.")
    except Exception as e:
        logger.warning("Test connections: MySQL secondary failed.", extra={"error": str(e)}, exc_info=True)
        result_info["mysql_secondary"] = {"error": str(e)}
    
    try:
        if payment_manager and hasattr(payment_manager, 'kafka_consumer') and payment_manager.kafka_consumer:
            kafka_consumer = payment_manager.kafka_consumer
            result_info["kafka_consumer"] = {
                "status": "running" if getattr(kafka_consumer, '_running', False) else "stopped_or_not_started",
                "group_id": getattr(kafka_consumer, 'group_id', 'N/A'),
                "subscribed_topics": getattr(kafka_consumer, 'topics_to_subscribe', [])
            }
            logger.debug("Test connections: Kafka consumer status retrieved.", extra=result_info["kafka_consumer"])
        else:
            result_info["kafka_consumer"] = {"status": "not_initialized_or_payment_manager_missing"}
            logger.warning("Test connections: Kafka consumer not available.")
    except Exception as e:
        logger.error("Test connections: Kafka status check failed.", extra={"error": str(e)}, exc_info=True)
        result_info["kafka_consumer"] = {"error": str(e)}
    
    return result_info

# 루트 엔드포인트
@app.get("/")
async def read_root():
    logger.debug("Root endpoint accessed.")
    return {
        "message": "Welcome to Payment Service API",
        "docs": "/docs",
        "redoc": "/redoc"
    }

if __name__ == "__main__":
    import uvicorn
    logger.info("Starting Payment Service with Uvicorn directly.")
    uvicorn.run("app.main:app", host="0.0.0.0", port=8004, reload=True)