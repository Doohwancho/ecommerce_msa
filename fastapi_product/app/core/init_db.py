from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.services.category_service import CategoryManager
from app.config.logging import logger
from app.config.database import engine, Base, get_product_collection
from pymongo import IndexModel, ASCENDING

async def initialize_categories(db: AsyncSession):
    """기본 카테고리 초기화"""
    try:
        # 기존 카테고리가 있는지 확인
        from app.models.category import Category
        existing_categories = await db.execute(select(Category))
        if existing_categories.first():
            logger.info("Categories already initialized, skipping")
            return  # 이미 데이터가 있으면 초기화 건너뜀
            
        # 카테고리 매니저 인스턴스 생성
        manager = CategoryManager(db)
        
        # 최상위 카테고리 생성
        electronics = await manager.create_category("전자제품")
        
        # 하위 카테고리 생성
        computers = await manager.create_category("컴퓨터", electronics.category_id)
        smartphones = await manager.create_category("스마트폰", electronics.category_id)
        
        # 더 깊은 하위 카테고리
        laptops = await manager.create_category("노트북", computers.category_id)
        gaming_laptops = await manager.create_category("게이밍 노트북", laptops.category_id)
        
        # 기본 상품 연결 예시
        await manager.associate_product_with_category("P123456", smartphones.category_id, is_primary=True)
        await manager.associate_product_with_category("P123456", electronics.category_id, is_primary=False)
        
        logger.info("Categories initialized successfully")
    except Exception as e:
        logger.error(f"Error initializing categories: {str(e)}")
        await db.rollback()

async def create_mongodb_indexes():
    """MongoDB 인덱스 생성"""
    try:
        product_collection = await get_product_collection()
        if not product_collection:
            raise Exception("Failed to get MongoDB collection")
            
        # 이미 인덱스가 있는지 확인
        existing_indexes = await product_collection.index_information()
        if 'product_id_1' in existing_indexes:
            logger.info("MongoDB indexes already exist, skipping")
            return
        
        # 인덱스 생성
        await product_collection.create_index([("product_id", ASCENDING)], unique=True)
        await product_collection.create_index([("title", ASCENDING)])
        await product_collection.create_index([("category_ids", ASCENDING)])
        
        logger.info("MongoDB indexes created successfully")
    except Exception as e:
        logger.error(f"Error creating MongoDB indexes: {str(e)}")