from fastapi import FastAPI, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from app.api.api import api_router
from app.services.product_manager import ProductManager
from sqlalchemy import text
import os
import asyncio
# import grpc config
from app.grpc.product_server import serve as grpc_serve
from contextlib import asynccontextmanager
# import configs
from app.config.logging import logger
from app.config.database import Base, write_engine, read_engine, get_mysql_db, get_product_collection
from app.config.elasticsearch import elasticsearch_config
from fastapi.responses import JSONResponse
import os


_grpc_task = None

def set_grpc_task(task):
    global _grpc_task
    _grpc_task = task

def get_grpc_task():
    return _grpc_task

async def safe_create_tables_if_not_exist(conn):
    """테이블이 존재하지 않는 경우에만 생성"""
    try:
        # 기존 테이블 확인
        result = await conn.execute(text("SHOW TABLES"))
        existing_tables = [row[0] for row in result]
        logger.info(f"Existing tables: {existing_tables}")
        
        # SQLAlchemy의 checkfirst 옵션 사용
        await conn.run_sync(lambda sync_conn: Base.metadata.create_all(
            sync_conn, 
            checkfirst=True  # 테이블이 이미 존재하면 건너뛰기
        ))
        
        logger.info("Tables created or already exist")
        
        # 생성 후 테이블 확인
        result = await conn.execute(text("SHOW TABLES"))
        tables = [row[0] for row in result]
        logger.info(f"Tables after creation: {tables}")
        
    except Exception as e:
        logger.error(f"Error creating tables: {e}")
        raise

# 전역 변수로 ProductManager 인스턴스 생성
product_manager = ProductManager()

@asynccontextmanager
async def lifespan(app: FastAPI):
    """애플리케이션 생명주기 관리"""
    # 시작 시 Primary DB에 테이블 생성
    async with write_engine.begin() as conn:
        await safe_create_tables_if_not_exist(conn)
    
    # Secondary DB에도 테이블 생성
    async with read_engine.begin() as conn:
        await safe_create_tables_if_not_exist(conn)
    
    # Elasticsearch 초기화
    try:
        await elasticsearch_config.get_client()
        logger.info("Elasticsearch initialized")
    except Exception as e:
        logger.error(f"Failed to initialize Elasticsearch: {e}")
        raise
    
    # Start gRPC server in background
    grpc_task = asyncio.create_task(grpc_serve())
    set_grpc_task(grpc_task)
    logger.info("gRPC server started on port 50051")

    # Kafka 초기화
    bootstrap_servers = os.getenv("KAFKA_BOOTSTRAP_SERVERS")
    group_id = "product-service-group"
    await product_manager.initialize_kafka(bootstrap_servers, group_id)
    logger.info("Kafka consumer initialized")
    
    yield
    
    # 종료 시 Kafka consumer 정리
    await product_manager.stop()
    logger.info("Kafka consumer stopped")

    # Elasticsearch 연결 종료
    await elasticsearch_config.close()
    logger.info("Elasticsearch connection closed")

    # Cancel gRPC task
    if grpc_task:
        logger.info("Shutting down product gRPC server")
        grpc_task.cancel()
        try:
            await grpc_task
        except asyncio.CancelledError:
            logger.info("gRPC server stopped")

# FastAPI 애플리케이션 생성
app = FastAPI(
    title="Product Service API",
    description="상품 서비스 API",
    version="1.0.0",
    lifespan=lifespan
)

# API 라우터 등록
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
    
    # 1. MySQL DB 연결 확인
    try:
        db_session = await get_mysql_db()
        async with db_session.begin():
            # text()로 SQL 쿼리 래핑
            from sqlalchemy import text
            result = await db_session.execute(text("SELECT 1"))
            status["mysql"] = "connected"
        await db_session.close()
    except Exception as e:
        logger.error(f"MySQL connection failed: {str(e)}")
        errors.append(f"MySQL: {str(e)}")
        status["mysql"] = "failed"

    # 2. MongoDB 연결 확인
    try:
        product_collection = await get_product_collection()
        # None과 비교하는 대신 컬렉션이 있는지 확인
        if product_collection is not None:
            # 간단한 쿼리 실행 (count 같은 간단한 작업)
            count = await product_collection.count_documents({})
            status["mongodb"] = "connected"
        else:
            errors.append("MongoDB: Failed to get collection")
            status["mongodb"] = "failed"
    except Exception as e:
        logger.error(f"MongoDB connection failed: {str(e)}")
        errors.append(f"MongoDB: {str(e)}")
        status["mongodb"] = "failed"
    
    # 3. Elasticsearch 연결 확인
    try:
        es_client = await elasticsearch_config.get_client()
        info = await es_client.info()
        status["elasticsearch"] = "connected"
    except Exception as e:
        logger.error(f"Elasticsearch connection failed: {str(e)}")
        errors.append(f"Elasticsearch: {str(e)}")
        status["elasticsearch"] = "failed"
    
    # 4. gRPC 서버 상태 확인 (필요한 경우)
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
    
    # 결과 반환
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
    
    # MySQL 연결 테스트
    try:
        db_session = await get_mysql_db()
        async with db_session.begin():
            from sqlalchemy import text
            query_result = await db_session.execute(text("SELECT 1"))
            result["mysql"] = "connected"
        await db_session.close()
    except Exception as e:
        result["mysql"] = {"error": str(e)}
    
    # MongoDB 연결 테스트
    try:
        product_collection = await get_product_collection()
        if product_collection is not None:
            count = await product_collection.count_documents({})
            result["mongodb"] = {"connected": True, "document_count": count}
        else:
            result["mongodb"] = {"error": "Failed to get collection"}
    except Exception as e:
        result["mongodb"] = {"error": str(e)}
    
    # Elasticsearch 연결 테스트
    try:
        es_client = await elasticsearch_config.get_client()
        info = await es_client.info()
        result["elasticsearch"] = {"connected": True, "version": info.get("version", {}).get("number", "unknown")}
    except Exception as e:
        result["elasticsearch"] = {"error": str(e)}
    
    return result


# 루트 엔드포인트
@app.get("/")
async def read_root():
    """API 루트 엔드포인트"""
    return {
        "message": "Welcome to Product Service API",
        "docs": "/docs",
        "redoc": "/redoc"
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host="0.0.0.0", port=8004, reload=True)