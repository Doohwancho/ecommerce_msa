from sqlalchemy.orm import Session
from app.services.category_manager import CategoryManager
from app.config.logging import logger
from app.config.database import product_collection, engine, Base
from pymongo import IndexModel, ASCENDING

def initialize_categories(db: Session):
    """기본 카테고리 초기화"""
    try:
        # 기존 카테고리가 있는지 확인
        from app.models.category import Category
        existing_categories = db.query(Category).first()
        if existing_categories:
            logger.info("Categories already initialized, skipping")
            return  # 이미 데이터가 있으면 초기화 건너뜀
            
        # 카테고리 매니저 인스턴스 생성
        manager = CategoryManager(db)
        
        # 최상위 카테고리 생성
        electronics = manager.create_category("전자제품")
        
        # 하위 카테고리 생성
        computers = manager.create_category("컴퓨터", electronics.category_id)
        smartphones = manager.create_category("스마트폰", electronics.category_id)
        
        # 더 깊은 하위 카테고리
        laptops = manager.create_category("노트북", computers.category_id)
        gaming_laptops = manager.create_category("게이밍 노트북", laptops.category_id)
        
        # 기본 상품 연결 예시
        manager.associate_product_with_category("P123456", smartphones.category_id, is_primary=True)
        manager.associate_product_with_category("P123456", electronics.category_id, is_primary=False)
        
        logger.info("Categories initialized successfully")
    except Exception as e:
        logger.error(f"Error initializing categories: {str(e)}")
        db.rollback()

def create_mongodb_indexes():
    """MongoDB 인덱스 생성"""
    try:
        # 이미 인덱스가 있는지 확인
        existing_indexes = product_collection.index_information()
        if 'product_id_1' in existing_indexes:
            logger.info("MongoDB indexes already exist, skipping")
            return
        
        # 인덱스 생성
        product_collection.create_index([("product_id", ASCENDING)], unique=True)
        product_collection.create_index([("title", ASCENDING)])
        product_collection.create_index([("category_ids", ASCENDING)])
        
        logger.info("MongoDB indexes created successfully")
    except Exception as e:
        logger.error(f"Error creating MongoDB indexes: {str(e)}")