from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List, Optional

from app.config.database import get_mysql_db
from app.models.product import Category
from app.schemas.category import CategoryCreate, CategoryResponse, ProductCategoryBase, ProductCategoryResponse
from app.services.category_service import CategoryManager
import logging

logger = logging.getLogger(__name__)

router = APIRouter()

@router.post("/", response_model=CategoryResponse)
async def create_category(
    category: CategoryCreate, 
    db: AsyncSession = Depends(get_mysql_db)
):
    """새 카테고리 생성 (DEPRECATED SERVICE)"""
    try:
        logger.info("Attempting to create category.", extra={"category_name": category.name, "parent_id": category.parent_id})
        category_manager = CategoryManager(db)
        created_category = await category_manager.create_category(
            name=category.name,
            parent_id=category.parent_id
        )
        logger.info("Successfully created category.", extra={"category_id": created_category.category_id, "category_name": created_category.name})
        return created_category
    except ValueError as ve:
        logger.warning("ValueError while creating category.", 
                       extra={"category_name": category.name, "parent_id": category.parent_id, "error": str(ve)})
        raise HTTPException(status_code=400, detail=str(ve))
    except Exception as e:
        logger.error("Error creating category.", 
                     extra={"category_name": category.name, "parent_id": category.parent_id, "error": str(e)}, 
                     exc_info=True)
        raise HTTPException(status_code=500, detail=f"An unexpected error occurred: {str(e)}")

@router.get("/", response_model=List[CategoryResponse])
async def read_categories(db: AsyncSession = Depends(get_mysql_db)):
    """모든 카테고리 조회 (DEPRECATED SERVICE)"""
    try:
        logger.info("Attempting to read all categories.")
        category_manager = CategoryManager(db)
        categories = await category_manager.get_categories()
        logger.info("Successfully read categories.", extra={"count": len(categories)})
        return categories
    except Exception as e:
        logger.error("Error reading categories.", extra={"error": str(e)}, exc_info=True)
        raise HTTPException(status_code=500, detail=f"An unexpected error occurred: {str(e)}")

@router.get("/{category_id}", response_model=CategoryResponse)
async def read_category(category_id: int, db: AsyncSession = Depends(get_mysql_db)):
    """카테고리 ID로 카테고리 조회 (DEPRECATED SERVICE)"""
    try:
        logger.info("Attempting to read category by ID.", extra={"category_id": category_id})
        category_manager = CategoryManager(db)
        category = await category_manager.get_category(category_id)
        logger.info("Successfully read category by ID.", extra={"category_id": category_id, "category_name": category.name})
        return category
    except ValueError as e:
        logger.warning("Category not found by ID.", extra={"category_id": category_id, "error": str(e)})
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error("Error reading category by ID.", extra={"category_id": category_id, "error": str(e)}, exc_info=True)
        raise HTTPException(status_code=500, detail=f"An unexpected error occurred: {str(e)}")

@router.get("/{category_id}/subcategories", response_model=List[CategoryResponse])
async def read_subcategories(category_id: int, db: AsyncSession = Depends(get_mysql_db)):
    """특정 카테고리의 모든 하위 카테고리 조회 (DEPRECATED SERVICE)"""
    try:
        logger.info("Attempting to read subcategories.", extra={"parent_category_id": category_id})
        category_manager = CategoryManager(db)
        subcategories = await category_manager.get_subcategories(category_id)
        logger.info("Successfully read subcategories.", extra={"parent_category_id": category_id, "count": len(subcategories)})
        return subcategories
    except ValueError as e:
        logger.warning("Parent category not found for subcategories.", extra={"parent_category_id": category_id, "error": str(e)})
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error("Error reading subcategories.", extra={"parent_category_id": category_id, "error": str(e)}, exc_info=True)
        raise HTTPException(status_code=500, detail=f"An unexpected error occurred: {str(e)}")

@router.post("/product-association")
async def associate_product_with_category(
    association: ProductCategoryBase,
    db: AsyncSession = Depends(get_mysql_db)
):
    """상품을 카테고리와 연결 (DEPRECATED SERVICE)"""
    try:
        logger.info("Attempting to associate product with category.", 
                    extra={
                        "product_id": association.product_id, 
                        "category_id": association.category_id, 
                        "is_primary": association.is_primary
                    })
        category_manager = CategoryManager(db)
        await category_manager.associate_product_with_category(
            product_id=association.product_id,
            category_id=association.category_id,
            is_primary=association.is_primary
        )
        logger.info("Successfully associated product with category.", 
                    extra={
                        "product_id": association.product_id, 
                        "category_id": association.category_id
                    })
        return {"message": "Product associated with category successfully"}
    except ValueError as e:
        logger.warning("ValueError during product-category association.", 
                       extra={
                           "product_id": association.product_id, 
                           "category_id": association.category_id, 
                           "error": str(e)
                        })
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error("Error associating product with category.", 
                     extra={
                         "product_id": association.product_id, 
                         "category_id": association.category_id, 
                         "error": str(e)
                        }, 
                     exc_info=True)
        raise HTTPException(status_code=500, detail=f"An unexpected error occurred: {str(e)}")

@router.get("/{category_id}/products", response_model=List[str])
async def get_products_in_category(
    category_id: int, 
    include_subcategories: bool = False,
    db: AsyncSession = Depends(get_mysql_db)
):
    """카테고리에 속한 모든 상품 ID 목록 조회 (DEPRECATED SERVICE)"""
    try:
        logger.info("Attempting to get products in category.", 
                    extra={"category_id": category_id, "include_subcategories": include_subcategories})
        category_manager = CategoryManager(db)
        if include_subcategories:
            product_ids = await category_manager.get_products_in_category_with_subcategories(category_id)
        else:
            product_ids = await category_manager.get_products_in_category(category_id)
        logger.info("Successfully retrieved products in category.", 
                    extra={
                        "category_id": category_id, 
                        "include_subcategories": include_subcategories, 
                        "count": len(product_ids)
                    })
        return product_ids
    except ValueError as e:
        logger.warning("Category not found when getting products.", 
                       extra={"category_id": category_id, "error": str(e)})
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error("Error getting products in category.", 
                     extra={"category_id": category_id, "error": str(e)}, 
                     exc_info=True)
        raise HTTPException(status_code=500, detail=f"An unexpected error occurred: {str(e)}")