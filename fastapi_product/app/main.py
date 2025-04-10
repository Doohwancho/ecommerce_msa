from fastapi import FastAPI, Depends
from sqlalchemy.orm import Session
from app.api.api import api_router
from app.config.database import Base, engine, get_mysql_db
from app.core.init_db import initialize_categories, create_mongodb_indexes

# 애플리케이션 생성
app = FastAPI(title="Product Service API", 
    # root_path="/products"
)

# API 라우터 등록
app.include_router(api_router, prefix="/api")

# 테이블 생성
Base.metadata.create_all(bind=engine)

# 시작 시 초기화 작업
@app.on_event("startup")
async def startup_event():
    # MongoDB 인덱스 생성
    create_mongodb_indexes()

@app.get("/health")
def health_check():
    return {"status": "OK"}

@app.get("/")
def read_root():
    return {"message": "Welcome to the Product Service API"}

# 초기 데이터 생성 엔드포인트 (필요한 경우에만 호출)
@app.post("/init-data")
def initialize_data(db: Session = Depends(get_mysql_db)):
    initialize_categories(db)
    return {"message": "Data initialized successfully"}