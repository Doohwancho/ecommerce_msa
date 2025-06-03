from fastapi import FastAPI, Depends, HTTPException
import logging
import asyncio
import uvicorn
from app.api.api import api_router
from app.grpc.user_server import serve as user_serve
from contextlib import asynccontextmanager
from app.config.grpc_config import set_grpc_task, get_grpc_task
from app.config.database import get_write_mongo_client, get_read_mongo_client
from app.config.logging import setup_logging
from motor.motor_asyncio import AsyncIOMotorClient
from fastapi.responses import JSONResponse
from opentelemetry import trace
from app.config.otel import setup_telemetry

setup_telemetry()

setup_logging()

# Logger instance should be obtained after logging is configured
logger = logging.getLogger(__name__)

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Start gRPC server in background
    logger.info("Lifespan: Starting gRPC server.", extra={"event": "grpc_server_start"})
    task = asyncio.create_task(user_serve())
    set_grpc_task(task)
    yield
    # Cleanup when FastAPI shuts down
    if task:
        logger.info("Lifespan: Shutting down gRPC server.", extra={"event": "grpc_server_shutdown"})
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            logger.info("Lifespan: gRPC server task cancelled.", extra={"event": "grpc_server_cancelled"})
        except Exception as e:
            logger.error("Lifespan: Error during gRPC server shutdown.", extra={"error": str(e)}, exc_info=True)

# Create application with lifespan handler
app = FastAPI(title="User Service API", lifespan=lifespan)

# API router registration
app.include_router(api_router, prefix="/api")

@app.get("/health/live")
async def liveness():
    """
    Liveness probe - 컨테이너가 살아있는지 확인
    """
    logger.debug("Liveness probe accessed.", extra={"path": "/health/live"})
    return {"status": "alive"}

@app.get("/health/ready")
async def readiness():
    """
    Readiness probe - 서비스가 요청을 처리할 준비가 되었는지 확인
    """
    logger.debug("Readiness probe accessed.", extra={"path": "/health/ready"})
    errors = []
    status_details = {}
    
    try:
        # Write DB 연결 확인
        write_client = get_write_mongo_client()
        await write_client.admin.command('ping')
        status_details["mongodb_write"] = "connected"
        logger.debug("Readiness: MongoDB write connection successful.", extra={"db_type": "mongodb_write"})
    except Exception as e:
        logger.error("Readiness: MongoDB write connection failed.", extra={"db_type": "mongodb_write", "error": str(e)}, exc_info=True)
        errors.append(f"MongoDB Write: {str(e)}")
        status_details["mongodb_write"] = "failed"
    
    try:
        # Read DB 연결 확인
        read_client = get_read_mongo_client()
        await read_client.admin.command('ping')
        status_details["mongodb_read"] = "connected"
        logger.debug("Readiness: MongoDB read connection successful.", extra={"db_type": "mongodb_read"})
    except Exception as e:
        logger.error("Readiness: MongoDB read connection failed.", extra={"db_type": "mongodb_read", "error": str(e)}, exc_info=True)
        errors.append(f"MongoDB Read: {str(e)}")
        status_details["mongodb_read"] = "failed"
    
    # gRPC 서버 상태 확인
    try:
        grpc_task = get_grpc_task()
        if not grpc_task or grpc_task.done():
            errors.append("gRPC server is not running")
            status_details["grpc"] = "failed"
            logger.warning("Readiness: gRPC server is not running.", extra={"grpc_status": "failed"})
        else:
            status_details["grpc"] = "running"
            logger.debug("Readiness: gRPC server is running.", extra={"grpc_status": "running"})
    except Exception as e:
        logger.error("Readiness: gRPC check failed.", extra={"error": str(e)}, exc_info=True)
        errors.append(f"gRPC: {str(e)}")
        status_details["grpc"] = "failed"
    
    if errors:
        logger.warning("Readiness probe failed.", extra={"status_details": status_details, "errors_count": len(errors)})
        return JSONResponse(
            status_code=503,
            content={"status": "not ready", "details": status_details, "errors": errors}
        )
    
    logger.info("Readiness probe successful.", extra={"status_details": status_details})
    return {"status": "ready", "details": status_details}

@app.get("/test-connections")
async def test_connections():
    """
    모든 외부 연결을 테스트하는 엔드포인트 (디버깅용)
    """
    logger.info("Accessing /test-connections endpoint.", extra={"path": "/test-connections"})
    result = {}
    
    # MongoDB Write 연결 테스트
    try:
        write_client = get_write_mongo_client()
        await write_client.admin.command('ping')
        result["mongodb_write"] = {"connected": True}
        logger.debug("Test Connections: MongoDB write successful.", extra={"db_type": "mongodb_write"})
    except Exception as e:
        result["mongodb_write"] = {"error": str(e), "connected": False}
        logger.error("Test Connections: MongoDB write failed.", extra={"db_type": "mongodb_write", "error": str(e)}, exc_info=True)
        
    # MongoDB Read 연결 테스트
    try:
        read_client = get_read_mongo_client()
        await read_client.admin.command('ping')
        result["mongodb_read"] = {"connected": True}
        logger.debug("Test Connections: MongoDB read successful.", extra={"db_type": "mongodb_read"})
    except Exception as e:
        result["mongodb_read"] = {"error": str(e), "connected": False}
        logger.error("Test Connections: MongoDB read failed.", extra={"db_type": "mongodb_read", "error": str(e)}, exc_info=True)
        
    return result


@app.get("/")
def read_root():
    # tracer should be available from opentelemetry.trace if OTel is set up
    tracer = trace.get_tracer(__name__)
    with tracer.start_as_current_span("endpoint.read_root"):
        logger.info("Root endpoint called.", extra={"path": "/", "endpoint_type": "read_root"})
        return {"message": "Welcome to the User Service API"}

if __name__ == "__main__":
    # Uvicorn's log_level will use the logging configuration set by setup_logging()
    # The uvicorn.access logger level is already handled in logging.py's dictConfig
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, log_config=None) # log_config=None to use our setup