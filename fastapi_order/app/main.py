from fastapi import FastAPI
from app.api.api import api_router
from app.config.database import Base, engine
import logging
import uvicorn
# import asyncio
# from app.grpc.user_server import serve as user_serve
# from contextlib import asynccontextmanager

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Global variable to store the gRPC server task
# grpc_task = None

# Use FastAPI's lifespan to manage the gRPC server
# @asynccontextmanager
# async def lifespan(app: FastAPI):
#     # Start gRPC server in background
#     global grpc_task
#     logger.info("Starting gRPC server in background")
#     grpc_task = asyncio.create_task(user_serve())
#     yield
#     # Cleanup when FastAPI shuts down
#     if grpc_task:
#         logger.info("Shutting down gRPC server")
#         grpc_task.cancel()
#         try:
#             await grpc_task
#         except asyncio.CancelledError:
#             logger.info("gRPC server task cancelled")

# Create application with lifespan handler
# app = FastAPI(title="Order Service API", lifespan=lifespan)
app = FastAPI(title="Order Service API")

# API router registration
app.include_router(api_router, prefix="/api")

# 테이블 생성
Base.metadata.create_all(bind=engine)


@app.get("/health")
def health_check():
    logger.info("Health check endpoint called")
    return {"status": "OK"}

@app.get("/")
def read_root():
    logger.info("Root endpoint called")
    return {"message": "Welcome to the Order Service API"}

if __name__ == "__main__":
    # Run only FastAPI - the gRPC server will be started by the lifespan handler
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, log_level="info")
# from fastapi import FastAPI
# from app.api.api import api_router
# from app.config.database import Base, engine
# import logging
# import uvicorn

# # 애플리케이션 생성
# app = FastAPI(title="Order Service API")

# # 로깅 설정
# logging.basicConfig(level=logging.INFO)
# logger = logging.getLogger(__name__)

# # API 라우터 등록
# app.include_router(api_router, prefix="/api")

# # 테이블 생성
# Base.metadata.create_all(bind=engine)

# @app.get("/health")
# def health_check():
#     logger.info("Health check endpoint called")
#     return {"status": "OK"}

# @app.get("/")
# def read_root():
#     logger.info("Root endpoint called")
#     return {"message": "Welcome to the Order Service API"}

# if __name__ == "__main__":
#     uvicorn.run("app.main:app", host="0.0.0.0", port=8000, log_level="info")
