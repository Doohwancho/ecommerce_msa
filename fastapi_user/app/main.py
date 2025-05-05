from fastapi import FastAPI, Depends
from app.api.api import api_router
import logging
import asyncio
import uvicorn
from app.grpc.user_server import serve as user_serve
from contextlib import asynccontextmanager
from app.config.grpc_config import set_grpc_task, get_grpc_task
from app.config.database import get_mongo_client
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
    try:
        # DB 연결 확인
        mongo_client = get_mongo_client()
        await mongo_client.admin.command('ping')
        
        # gRPC 서버 상태 확인
        grpc_task = get_grpc_task()
        if not grpc_task or grpc_task.done():
            raise Exception("gRPC server is not running")
            
        return {"status": "ready"}
    except Exception as e:
        logger.error(f"Readiness check failed: {str(e)}")
        return JSONResponse(
            status_code=503,
            content={"status": "not ready", "error": str(e)}
        )

@app.get("/test-db-connection")
async def test_db_connection():
    try:
        mongo_client = get_mongo_client()
        result = await mongo_client.admin.command('ping')
        return {"status": "connected", "result": str(result)}
    except Exception as e:
        return {"status": "error", "message": str(e)}

@app.get("/")
def read_root():
    logger.info("Root endpoint called")
    return {"message": "Welcome to the User Service API"}

if __name__ == "__main__":
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, log_level="info")