from fastapi import FastAPI, Depends, HTTPException
import logging
import asyncio
import uvicorn
from app.api.api import api_router
from app.grpc.user_server import serve as user_serve
from contextlib import asynccontextmanager
from app.config.grpc_config import set_grpc_task, get_grpc_task
from app.config.database import get_write_mongo_client, get_read_mongo_client
from app.config.otel import setup_telemetry
from motor.motor_asyncio import AsyncIOMotorClient
from fastapi.responses import JSONResponse

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Start gRPC server in background
    logger.info("Starting gRPC server in background")
    task = asyncio.create_task(user_serve())
    set_grpc_task(task)
    yield
    # Cleanup when FastAPI shuts down
    if task:
        logger.info("Shutting down gRPC server")
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            logger.info("gRPC server task cancelled")

# Create application with lifespan handler
app = FastAPI(title="User Service API", lifespan=lifespan)

# Initialize OpenTelemetry
setup_telemetry()

# API router registration
app.include_router(api_router, prefix="/api")

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
    
    try:
        # Write DB 연결 확인
        write_client = get_write_mongo_client()
        await write_client.admin.command('ping')
        status["mongodb_write"] = "connected"
    except Exception as e:
        logger.error(f"MongoDB write connection failed: {str(e)}")
        errors.append(f"MongoDB Write: {str(e)}")
        status["mongodb_write"] = "failed"
    
    try:
        # Read DB 연결 확인
        read_client = get_read_mongo_client()
        await read_client.admin.command('ping')
        status["mongodb_read"] = "connected"
    except Exception as e:
        logger.error(f"MongoDB read connection failed: {str(e)}")
        errors.append(f"MongoDB Read: {str(e)}")
        status["mongodb_read"] = "failed"
    
    # gRPC 서버 상태 확인
    try:
        grpc_task = get_grpc_task()
        if not grpc_task or grpc_task.done():
            errors.append("gRPC server is not running")
            status["grpc"] = "failed"
        else:
            status["grpc"] = "running"
    except Exception as e:
        logger.error(f"gRPC check failed: {str(e)}")
        errors.append(f"gRPC: {str(e)}")
        status["grpc"] = "failed"
    
    if errors:
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
    
    # MongoDB Write 연결 테스트
    try:
        write_client = get_write_mongo_client()
        await write_client.admin.command('ping')
        result["mongodb_write"] = {"connected": True}
    except Exception as e:
        result["mongodb_write"] = {"error": str(e)}
    
    # MongoDB Read 연결 테스트
    try:
        read_client = get_read_mongo_client()
        await read_client.admin.command('ping')
        result["mongodb_read"] = {"connected": True}
    except Exception as e:
        result["mongodb_read"] = {"error": str(e)}
    
    return result

@app.get("/")
def read_root():
    logger.info("Root endpoint called")
    return {"message": "Welcome to the User Service API"}

if __name__ == "__main__":
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, log_level="info")