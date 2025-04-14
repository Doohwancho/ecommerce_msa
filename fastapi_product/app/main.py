from fastapi import FastAPI, Depends
from sqlalchemy.orm import Session
from sqlalchemy.ext.asyncio import AsyncSession
from app.api.api import api_router
from app.config.database import Base, engine, get_mysql_db, get_async_mysql_db
from app.core.init_db import initialize_categories, create_mongodb_indexes
import logging
import asyncio
import uvicorn
# gRPC server import
from app.grpc.product_server import serve as grpc_serve
from contextlib import asynccontextmanager

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Global variable to store the gRPC server task
grpc_task = None

# Use FastAPI's lifespan to manage the gRPC server
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Start gRPC server in background
    global grpc_task
    logger.info("Starting gRPC server in background")
    grpc_task = asyncio.create_task(grpc_serve())
    
    # Create database tables
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    
    yield
    
    # Cleanup when FastAPI shuts down
    if grpc_task:
        logger.info("Shutting down gRPC server")
        grpc_task.cancel()
        try:
            await grpc_task
        except asyncio.CancelledError:
            logger.info("gRPC server task cancelled")

# Create application with lifespan handler
app = FastAPI(title="Product Service API", lifespan=lifespan)

# API router registration
app.include_router(api_router, prefix="/api")

@app.get("/health")
def health_check():
    logger.info("Health check endpoint called")
    return {"status": "OK"}

@app.get("/")
def read_root():
    logger.info("Root endpoint called")
    return {"message": "Welcome to the Product Service API"}

# Initialize during startup
@app.on_event("startup")
async def startup_event():
    # Create MongoDB indexes
    await create_mongodb_indexes()
    
    # Initialize categories
    async_session = await get_async_mysql_db()
    await initialize_categories(async_session)

# Initialize data endpoint (call only when needed)
@app.post("/init-data")
async def initialize_data(db: AsyncSession = Depends(get_async_mysql_db)):
    await initialize_categories(db)
    return {"message": "Data initialized successfully"}

if __name__ == "__main__":
    # Run only FastAPI - the gRPC server will be started by the lifespan handler
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, log_level="info")