from fastapi import FastAPI, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from app.api.api import api_router
from app.services.product_manager import ProductManager
from sqlalchemy import text
import os
import asyncio
from contextlib import asynccontextmanager

# OTel imports
from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode
from opentelemetry.semconv.trace import SpanAttributes # For semantic conventions

# import grpc config
from app.grpc.product_server import serve as grpc_serve

# import configs
from app.config.database import (
    Base, write_engine, read_engine, get_mysql_db,
    get_write_product_collection, get_read_product_collection
)
from app.config.elasticsearch import elasticsearch_config
import logging
from app.config.logging import initialize_logging_and_telemetry, get_configured_logger, get_global_logger_provider # Import setup_logging
from app.config.otel import setup_non_logging_telemetry, instrument_fastapi_app
from fastapi.responses import JSONResponse


# --- 1. 로깅 및 OpenTelemetry 핵심 설정 초기화 ---
# 애플리케이션 시작 시 가장 먼저 호출되어야 함!
initialize_logging_and_telemetry()

# --- 2. 이 모듈(main.py)에서 사용할 로거 가져오기 ---
# 이제 initialize_logging_and_telemetry()가 호출되었으므로 안전하게 설정된 로거를 가져옴
logger = get_configured_logger(__name__) # 또는 get_configured_logger("app.main")

# --- 3. OpenTelemetry 추가 설정 (트레이싱, 주요 라이브러리 계측) ---
# 로깅 및 Provider 설정이 완료된 후 호출
setup_non_logging_telemetry()


# Initialize OTel tracer for this module
tracer = trace.get_tracer("app.main")

_grpc_task = None

def set_grpc_task(task):
    global _grpc_task
    _grpc_task = task

def get_grpc_task():
    return _grpc_task

async def safe_create_tables_if_not_exist(conn, db_type: str): # Added db_type for span attribute
    """테이블이 존재하지 않는 경우에만 생성, OTel span 추가"""
    # This function is called within a parent span from lifespan.
    # SQLAlchemyInstrumentor will trace the actual DB calls (conn.execute, conn.run_sync).
    # This manual span groups the logic of this function.
    with tracer.start_as_current_span(f"db.schema_migration.{db_type}.safe_create_tables") as span:
        span.set_attribute("db.type", db_type)
        try:
            span.set_attribute(SpanAttributes.DB_OPERATION, "SHOW TABLES")
            result = await conn.execute(text("SHOW TABLES"))
            existing_tables = [row[0] for row in result]
            logger.info(f"Existing tables in {db_type}", extra={"db_type": db_type, "existing_tables": existing_tables})
            span.set_attribute("db.tables.existing_count", len(existing_tables))

            span.set_attribute(SpanAttributes.DB_OPERATION, "Base.metadata.create_all")
            await conn.run_sync(lambda sync_conn: Base.metadata.create_all(
                sync_conn,
                checkfirst=True
            ))
            logger.info(f"Tables created or already exist in {db_type}", extra={"db_type": db_type, "checkfirst": True})

            result_after = await conn.execute(text("SHOW TABLES"))
            tables_after = [row[0] for row in result_after]
            logger.info(f"Tables after creation attempt in {db_type}", extra={"db_type": db_type, "tables_after": tables_after})
            span.set_attribute("db.tables.after_creation_count", len(tables_after))
            span.set_status(Status(StatusCode.OK))
        except Exception as e:
            logger.error(f"Error in safe_create_tables_if_not_exist for {db_type}", extra={"db_type": db_type, "error": str(e)}, exc_info=True)
            span.record_exception(e)
            span.set_status(Status(StatusCode.ERROR, str(e)))
            raise

# 전역 변수로 ProductManager 인스턴스 생성
product_manager = ProductManager()

@asynccontextmanager
async def lifespan(app_instance: FastAPI): # Renamed app to app_instance to avoid conflict
    """애플리케이션 생명주기 관리 with OTel Tracing"""
    with tracer.start_as_current_span("app.lifespan.startup") as startup_span:
        try:
            # 1. Database Table Creation
            with tracer.start_as_current_span("app.lifespan.startup.db_setup") as db_setup_span:
                try:
                    async with write_engine.begin() as conn:
                        await safe_create_tables_if_not_exist(conn, "write_db")
                    async with read_engine.begin() as conn:
                        await safe_create_tables_if_not_exist(conn, "read_db")
                    db_setup_span.set_status(Status(StatusCode.OK))
                except Exception as e:
                    logger.error("Lifespan: DB setup failed", extra={"error": str(e)}, exc_info=True)
                    db_setup_span.record_exception(e)
                    db_setup_span.set_status(Status(StatusCode.ERROR, "DB setup failed"))
                    # Depending on policy, you might raise e here to fail startup

            # 2. Elasticsearch 초기화
            with tracer.start_as_current_span("app.lifespan.startup.elasticsearch_init") as es_init_span:
                try:
                    # ElasticsearchInstrumentor will trace the .get_client() if it makes network calls
                    await elasticsearch_config.get_client()
                    logger.info("Elasticsearch initialized")
                    es_init_span.set_status(Status(StatusCode.OK))
                except Exception as e:
                    logger.error("Failed to initialize Elasticsearch", extra={"error": str(e)}, exc_info=True)
                    es_init_span.record_exception(e)
                    es_init_span.set_status(Status(StatusCode.ERROR, "Elasticsearch init failed"))
                    logger.warning("Continuing without Elasticsearch support")
                    # Not re-raising, app continues. Mark parent span if this is considered a partial success/failure.

            # 3. Start gRPC server in background
            with tracer.start_as_current_span("app.lifespan.startup.grpc_init") as grpc_init_span:
                grpc_task = asyncio.create_task(grpc_serve())
                set_grpc_task(grpc_task)
                logger.info("gRPC server startup task created", extra={"port": 50051})
                grpc_init_span.set_status(Status(StatusCode.OK))

            # 4. Kafka 초기화
            # KafkaPythonInstrumentor (or AIOKafkaInstrumentor) should trace operations within initialize_kafka
            with tracer.start_as_current_span("app.lifespan.startup.kafka_init") as kafka_init_span:
                try:
                    bootstrap_servers = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092") # Provide a default
                    group_id = os.getenv("KAFKA_CONSUMER_GROUP_ID", "product-service-group")
                    kafka_init_span.set_attribute("kafka.bootstrap_servers", bootstrap_servers)
                    kafka_init_span.set_attribute("kafka.group_id", group_id)
                    await product_manager.initialize_kafka(bootstrap_servers, group_id)
                    logger.info("Kafka consumer initialized", extra={"bootstrap_servers": bootstrap_servers, "group_id": group_id})
                    kafka_init_span.set_status(Status(StatusCode.OK))
                except Exception as e:
                    logger.error("Lifespan: Kafka consumer initialization failed", extra={"error": str(e)}, exc_info=True)
                    kafka_init_span.record_exception(e)
                    kafka_init_span.set_status(Status(StatusCode.ERROR, "Kafka init failed"))
                    # Decide if Kafka init failure is critical for startup

            startup_span.set_status(Status(StatusCode.OK)) # If all critical parts succeeded
            logger.info("Application startup sequence completed.")

        except Exception as e: # Catch any unhandled errors during critical startup phases
            logger.error("Critical error during application startup", extra={"error": str(e)}, exc_info=True)
            startup_span.record_exception(e)
            startup_span.set_status(Status(StatusCode.ERROR, "Critical startup failure"))
            raise # Re-raise to stop application if startup is entirely compromised

        yield # Application runs

        # Shutdown logic
        with tracer.start_as_current_span("app.lifespan.shutdown") as shutdown_span:
            logger.info("Starting application shutdown sequence...")
            try:
                # Kafka consumer 정리
                with tracer.start_as_current_span("app.lifespan.shutdown.kafka_stop") as kafka_stop_span:
                    await product_manager.stop()
                    logger.info("Kafka consumer stopped")
                    kafka_stop_span.set_status(Status(StatusCode.OK))

                # Elasticsearch 연결 종료
                with tracer.start_as_current_span("app.lifespan.shutdown.elasticsearch_close") as es_close_span:
                    try:
                        await elasticsearch_config.close()
                        logger.info("Elasticsearch connection closed")
                        es_close_span.set_status(Status(StatusCode.OK))
                    except Exception as e:
                        logger.error("Error closing Elasticsearch connection", extra={"error": str(e)}, exc_info=True)
                        es_close_span.record_exception(e)
                        es_close_span.set_status(Status(StatusCode.ERROR, str(e)))
                
                # Cancel gRPC task
                grpc_shutdown_task = get_grpc_task()
                if grpc_shutdown_task:
                    with tracer.start_as_current_span("app.lifespan.shutdown.grpc_stop") as grpc_stop_span:
                        logger.info("Shutting down product gRPC server")
                        grpc_shutdown_task.cancel()
                        try:
                            await grpc_shutdown_task
                        except asyncio.CancelledError:
                            logger.info("gRPC server stopped after cancellation")
                        except Exception as e: # Catch other potential errors during await
                            logger.error("Error during gRPC server shutdown", extra={"error": str(e)}, exc_info=True)
                            grpc_stop_span.record_exception(e)
                            grpc_stop_span.set_status(Status(StatusCode.ERROR, "gRPC shutdown error"))
                            raise # Or handle as non-critical
                        else: # If no exception during await (other than CancelledError)
                            grpc_stop_span.set_status(Status(StatusCode.OK))
                
                shutdown_span.set_status(Status(StatusCode.OK))
                logger.info("Application shutdown sequence completed.")
            except Exception as e:
                logger.error("Error during application shutdown", extra={"error": str(e)}, exc_info=True)
                shutdown_span.record_exception(e)
                shutdown_span.set_status(Status(StatusCode.ERROR, "Shutdown sequence error"))


# FastAPI 애플리케이션 생성
app = FastAPI(
    title="Product Service API",
    description="상품 서비스 API",
    version="1.0.0",
    lifespan=lifespan # Use the enhanced lifespan manager
)

# API 라우터 등록
app.include_router(api_router, prefix="/api")

# Initialize OpenTelemetry after app creation, ensure instrumentors are applied.
# If FastAPIInstrumentor needs the app instance, it would be FastAPIInstrumentor().instrument_app(app)
# in setup_telemetry, or ensure setup_telemetry is called such that instrument() works globally.
# The current order (app = FastAPI, then setup_telemetry) should be fine if FastAPIInstrumentor.instrument()
# patches globally.
instrument_fastapi_app(app) 



@app.get("/health/live")
async def liveness():
    """Liveness probe - 컨테이너가 살아있는지 확인"""
    # FastAPIInstrumentor will trace this. Manual span is usually not needed.
    # logger.info will be correlated if LoggingInstrumentor is active.
    logger.debug("Liveness probe called") # Use debug for very frequent logs
    return {"status": "alive"}

@app.get("/health/ready")
async def readiness():
    """Readiness probe - 서비스가 요청을 처리할 준비가 되었는지 확인"""
    # FastAPIInstrumentor creates the main span. Auto-instrumentation for DB/ES/Kafka pings (if any) creates child spans.
    # Logs will be correlated. A manual span for the entire readiness check provides overall status.
    with tracer.start_as_current_span("app.health.readiness_check") as readiness_span:
        readiness_span.set_attribute(SpanAttributes.HTTP_METHOD, "GET")
        readiness_span.set_attribute(SpanAttributes.HTTP_ROUTE, "/health/ready")
        
        errors = []
        service_status_details = {} # Renamed from 'status'
        all_ok = True

        # 1. MySQL DB 연결 확인
        # SQLAlchemyInstrumentor traces db_session.execute
        try:
            db_session: AsyncSession = await get_mysql_db() # Ensure get_mysql_db is efficient
            async with db_session: # Ensures session is closed
                await db_session.execute(text("SELECT 1"))
            service_status_details["mysql"] = "connected"
        except Exception as e:
            logger.error("Readiness: MySQL connection failed", extra={"error": str(e)}, exc_info=True)
            errors.append(f"MySQL: {str(e)}")
            service_status_details["mysql"] = "failed"
            readiness_span.set_attribute("readiness.mysql.error", str(e))
            all_ok = False

        # 2. MongoDB 연결 확인 (Write & Read)
        # PymongoInstrumentor would trace actual DB ops like ping(), not just getting a collection object.
        try:
            write_collection = await get_write_product_collection()
            if write_collection is not None:
                # Example: await write_collection.database.command('ping') # This would be traced
                service_status_details["mongodb_write"] = "connected"
            else:
                errors.append("MongoDB Write: Failed to get collection")
                service_status_details["mongodb_write"] = "failed"
                readiness_span.set_attribute("readiness.mongodb_write.error", "Failed to get collection")
                all_ok = False
            
            read_collection = await get_read_product_collection()
            if read_collection is not None:
                service_status_details["mongodb_read"] = "connected"
            else:
                errors.append("MongoDB Read: Failed to get collection")
                service_status_details["mongodb_read"] = "failed"
                readiness_span.set_attribute("readiness.mongodb_read.error", "Failed to get collection")
                all_ok = False
        except Exception as e:
            logger.error("Readiness: MongoDB connection check failed", extra={"error": str(e)}, exc_info=True)
            errors.append(f"MongoDB: {str(e)}")
            service_status_details["mongodb_write"] = service_status_details.get("mongodb_write", "failed")
            service_status_details["mongodb_read"] = service_status_details.get("mongodb_read", "failed")
            readiness_span.set_attribute("readiness.mongodb.overall_error", str(e))
            all_ok = False
        
        # 3. Elasticsearch 연결 확인 (if uncommented in user's original code)
        # ElasticsearchInstrumentor would trace es_client.info()
        # try:
        #     es_client = await elasticsearch_config.get_client()
        #     await es_client.info()
        #     service_status_details["elasticsearch"] = "connected"
        # except Exception as e:
        #     logger.error(f"Readiness: Elasticsearch connection failed: {str(e)}", exc_info=True)
        #     errors.append(f"Elasticsearch: {str(e)}")
        #     service_status_details["elasticsearch"] = "failed"
        #     readiness_span.set_attribute("readiness.elasticsearch.error", str(e))
        #     all_ok = False
        
        # 4. gRPC 서버 상태 확인
        try:
            current_grpc_task = get_grpc_task()
            if not current_grpc_task or current_grpc_task.done():
                errors.append("gRPC server is not running or has completed")
                service_status_details["grpc"] = "failed"
                readiness_span.set_attribute("readiness.grpc.status", "Not running or done")
                all_ok = False
            else:
                service_status_details["grpc"] = "running"
        except Exception as e: # Should be unlikely if get_grpc_task is simple
            logger.error("Readiness: gRPC check logic failed", extra={"error": str(e)}, exc_info=True)
            errors.append(f"gRPC check error: {str(e)}")
            service_status_details["grpc"] = "error"
            readiness_span.set_attribute("readiness.grpc.check_error", str(e))
            all_ok = False
        
        if not all_ok:
            readiness_span.set_attribute("readiness.errors_count", len(errors))
            readiness_span.set_status(Status(StatusCode.ERROR, "Readiness checks failed"))
            if errors:
                readiness_span.set_attribute("readiness.first_error_detail", errors[0])
            return JSONResponse(
                status_code=503,
                content={"status": "not ready", "details": service_status_details, "errors": errors}
            )
        
        readiness_span.set_status(Status(StatusCode.OK))
        logger.info("Readiness probe successful.")
        return {"status": "ready", "details": service_status_details}


@app.get("/test-connections")
async def test_connections():
    """모든 외부 연결을 테스트하는 엔드포인트 (디버깅용)"""
    # FastAPIInstrumentor traces the request. Auto-instrumentors trace underlying I/O.
    with tracer.start_as_current_span("app.test_connections") as span:
        span.set_attribute(SpanAttributes.HTTP_METHOD, "GET")
        span.set_attribute(SpanAttributes.HTTP_ROUTE, "/test-connections")
        results = {}
        any_error = False

        # MySQL
        try:
            db_session: AsyncSession = await get_mysql_db()
            async with db_session:
                await db_session.execute(text("SELECT 1"))
            results["mysql"] = {"status": "connected"}
        except Exception as e:
            logger.error("TestConnections: MySQL failed", extra={"error": str(e)}, exc_info=True)
            results["mysql"] = {"status": "error", "detail": str(e)}
            span.set_attribute("test.mysql.error", str(e))
            any_error = True
        
        # MongoDB
        try:
            write_collection = await get_write_product_collection()
            if write_collection is not None:
                # Example: Perform an actual operation that would be traced
                # await write_collection.database.command('ping')
                count = await write_collection.count_documents({}) # This is traced by PymongoInstrumentor
                results["mongodb_write"] = {"status": "connected", "document_count": count}
            else:
                results["mongodb_write"] = {"status": "error", "detail": "Failed to get write collection"}
                span.set_attribute("test.mongodb_write.error", "Failed to get write collection")
                any_error = True

            read_collection = await get_read_product_collection()
            if read_collection is not None:
                count = await read_collection.count_documents({}) # Traced
                results["mongodb_read"] = {"status": "connected", "document_count": count}
            else:
                results["mongodb_read"] = {"status": "error", "detail": "Failed to get read collection"}
                span.set_attribute("test.mongodb_read.error", "Failed to get read collection")
                any_error = True
        except Exception as e:
            logger.error("TestConnections: MongoDB failed", extra={"error": str(e)}, exc_info=True)
            results["mongodb_overall"] = {"status": "error", "detail": str(e)} # More specific if possible
            span.set_attribute("test.mongodb.error", str(e))
            any_error = True

        # Elasticsearch
        try:
            es_client = await elasticsearch_config.get_client()
            info = await es_client.info() # Traced by ElasticsearchInstrumentor
            results["elasticsearch"] = {"status": "connected", "version": info.get("version", {}).get("number", "unknown")}
        except Exception as e:
            logger.error("TestConnections: Elasticsearch failed", extra={"error": str(e)}, exc_info=True)
            results["elasticsearch"] = {"status": "error", "detail": str(e)}
            span.set_attribute("test.elasticsearch.error", str(e))
            any_error = True
        
        if any_error:
            span.set_status(Status(StatusCode.ERROR, "One or more connection tests failed"))
        else:
            span.set_status(Status(StatusCode.OK))
        return results

@app.get("/")
async def read_root():
    """API 루트 엔드포인트"""
    # FastAPIInstrumentor traces this. For simple endpoints, manual span is optional.
    with tracer.start_as_current_span("app.root") as span:
        span.set_attribute(SpanAttributes.HTTP_METHOD, "GET")
        span.set_attribute(SpanAttributes.HTTP_ROUTE, "/")
        logger.info("Root endpoint called")
        span.set_status(Status(StatusCode.OK))
        return {
            "message": "Welcome to Product Service API",
            "docs": "/docs",
            "redoc": "/redoc"
        }

if __name__ == "__main__":
    import uvicorn
    # Note: Uvicorn's reload=True is for development.
    # OTel setup should ideally be robust to reloads, but complex state might have issues.
    uvicorn.run("app.main:app", host="0.0.0.0", port=8004, reload=True, log_level="info")