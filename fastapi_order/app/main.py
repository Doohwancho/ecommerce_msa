from fastapi import FastAPI
from app.api.api import api_router
from app.config.database import Base, engine
import logging

# 애플리케이션 생성
app = FastAPI(title="Order Service API", 
    # root_path="/orders"
)

# 로깅 설정
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# API 라우터 등록
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