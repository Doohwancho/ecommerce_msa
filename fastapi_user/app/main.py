from fastapi import FastAPI
from app.api.api import api_router

# 애플리케이션 생성
app = FastAPI(title="User Service API", 
    # root_path="/users"
)

# API 라우터 등록
app.include_router(api_router, prefix="/api")

@app.get("/health")
def health_check():
    return {"status": "OK"}

@app.get("/")
def read_root():
    return {"message": "Welcome to the User Service API"}