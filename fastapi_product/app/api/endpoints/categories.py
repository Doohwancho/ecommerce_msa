from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List, Optional

from app.config.database import get_mysql_db
from app.models.category import Category
from app.schemas.category import CategoryCreate, CategoryResponse, ProductCategoryBase, ProductCategoryResponse
from app.services.category_service import CategoryManager
from app.config.logging import logger

router = APIRouter()

@router.post("/", response_model=CategoryResponse)
async def create_category(
    category: CategoryCreate, 
    db: AsyncSession = Depends(get_mysql_db)
):
    """새 카테고리 생성"""
    try:
        logger.info(f"Creating category: {category.name}")
        category_manager = CategoryManager(db)
        return await category_manager.create_category(
            name=category.name,
            parent_id=category.parent_id
        )
    except Exception as e:
        logger.error(f"Error creating category: {str(e)}")
        raise HTTPException(status_code=400, detail=str(e))

@router.get("/", response_model=List[CategoryResponse])
async def read_categories(db: AsyncSession = Depends(get_mysql_db)):
    """모든 카테고리 조회"""
    try:
        category_manager = CategoryManager(db)
        return await category_manager.get_categories()
    except Exception as e:
        logger.error(f"Error reading categories: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/{category_id}", response_model=CategoryResponse)
async def read_category(category_id: int, db: AsyncSession = Depends(get_mysql_db)):
    """카테고리 ID로 카테고리 조회"""
    try:
        category_manager = CategoryManager(db)
        return await category_manager.get_category(category_id)
    except ValueError as e:
        logger.error(f"Category not found: {str(e)}")
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"Error reading category: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/{category_id}/subcategories", response_model=List[CategoryResponse])
async def read_subcategories(category_id: int, db: AsyncSession = Depends(get_mysql_db)):
    """특정 카테고리의 모든 하위 카테고리 조회"""
    try:
        category_manager = CategoryManager(db)
        return await category_manager.get_subcategories(category_id)
    except ValueError as e:
        logger.error(f"Category not found: {str(e)}")
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"Error reading subcategories: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/product-association")
async def associate_product_with_category(
    association: ProductCategoryBase,
    db: AsyncSession = Depends(get_mysql_db)
):
    """상품을 카테고리와 연결"""
    try:
        category_manager = CategoryManager(db)
        await category_manager.associate_product_with_category(
            product_id=association.product_id,
            category_id=association.category_id,
            is_primary=association.is_primary
        )
        return {"message": "Product associated with category successfully"}
    except ValueError as e:
        logger.error(f"Category not found: {str(e)}")
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"Error associating product with category: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/{category_id}/products", response_model=List[str])
async def get_products_in_category(
    category_id: int, 
    include_subcategories: bool = False,
    db: AsyncSession = Depends(get_mysql_db)
):
    """카테고리에 속한 모든 상품 ID 목록 조회"""
    try:
        category_manager = CategoryManager(db)
        if include_subcategories:
            return await category_manager.get_products_in_category_with_subcategories(category_id)
        else:
            return await category_manager.get_products_in_category(category_id)
    except ValueError as e:
        logger.error(f"Category not found: {str(e)}")
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"Error getting products in category: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))