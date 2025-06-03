from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.services.category_service import CategoryManager
from app.config.logging import logger
from app.config.database import engine, Base, get_product_collection
from pymongo import IndexModel, ASCENDING

async def initialize_categories(db: AsyncSession):
    """기본 카테고리 초기화 (Note: CategoryManager service is DEPRECATED)"""
    try:
        from app.models.category import Category
        existing_categories = await db.execute(select(Category))
        if existing_categories.first():
            logger.info("Categories already initialized, skipping.")
            return
            
        manager = CategoryManager(db)
        
        electronics = await manager.create_category("전자제품")
        computers = await manager.create_category("컴퓨터", electronics.category_id)
        smartphones = await manager.create_category("스마트폰", electronics.category_id)
        laptops = await manager.create_category("노트북", computers.category_id)
        await manager.create_category("게이밍 노트북", laptops.category_id)
        
        # Example product association
        # This part might also be deprecated if product-category links are managed elsewhere
        await manager.associate_product_with_category("P123456", smartphones.category_id, is_primary=True)
        await manager.associate_product_with_category("P123456", electronics.category_id, is_primary=False)
        
        logger.info("Categories initialized successfully (using DEPRECATED CategoryManager).", 
                    extra={"service_used": "CategoryManager"})
    except Exception as e:
        logger.error("Error initializing categories.", extra={"error": str(e)}, exc_info=True)
        # Rollback might not be necessary if create_category handles its own transactions and rolls back.
        # However, if initialize_categories itself forms a larger transaction context, this is correct.
        # Assuming CategoryManager methods commit individually, so this rollback is a safety measure.
        try:
            await db.rollback()
        except Exception as rb_exc: # pylint: disable=broad-except
            logger.error("Error during rollback after category initialization failure.", 
                         extra={"rollback_error": str(rb_exc)}, exc_info=True)

async def create_mongodb_indexes():
    """MongoDB 인덱스 생성"""
    try:
        product_collection = await get_product_collection()
        if not product_collection:
            # This case should ideally not happen if get_product_collection raises an error or is always available.
            logger.error("Failed to get MongoDB product collection for index creation.")
            raise Exception("Failed to get MongoDB product collection for index creation.") # Or return/handle gracefully
            
        existing_indexes = await product_collection.index_information()
        
        # Check for a specific, uniquely named index to determine if setup has run.
        # Example: Using the unique index on 'product_id'
        if 'product_id_1' in existing_indexes:
            logger.info("MongoDB indexes already exist, skipping creation.")
            return
        
        # Define indexes to be created
        indexes_to_create = [
            IndexModel([("product_id", ASCENDING)], name="product_id_1", unique=True),
            IndexModel([("title", ASCENDING)], name="title_1"),
            IndexModel([("category_ids", ASCENDING)], name="category_ids_1")
        ]
        
        # Create indexes
        # The create_indexes method is generally preferred as it can create multiple indexes efficiently.
        await product_collection.create_indexes(indexes_to_create)
        
        logger.info("MongoDB indexes created successfully.", 
                    extra={"indexes_created": [idx.document.get('name') for idx in indexes_to_create]}) 
    except Exception as e:
        logger.error("Error creating MongoDB indexes.", extra={"error": str(e)}, exc_info=True)