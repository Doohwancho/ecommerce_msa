from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List, Optional

from app.config.database import get_mysql_db
from app.models.category import Category
from app.schemas.category import CategoryCreate, CategoryResponse, ProductCategoryBase, ProductCategoryResponse
from app.services.category_manager import CategoryManager
from app.config.logging import logger

router = APIRouter()

@router.post("/", response_model=CategoryResponse)
def create_category(
    category: CategoryCreate, 
    db: Session = Depends(get_mysql_db)
):
    """새 카테고리 생성"""
    try:
        logger.info(f"Creating category: {category.name}")
        manager = CategoryManager(db)
        db_category = manager.create_category(category.name, category.parent_id)
        logger.info(f"Category created: {db_category.category_id}")
        return db_category
    except Exception as e:
        logger.error(f"Error creating category: {str(e)}")
        raise HTTPException(status_code=400, detail=str(e))

@router.get("/", response_model=List[CategoryResponse])
def read_categories(db: Session = Depends(get_mysql_db)):
    """모든 카테고리 목록 조회"""
    try:
        manager = CategoryManager(db)
        return manager.get_categories()
    except Exception as e:
        logger.error(f"Error reading categories: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/{category_id}", response_model=CategoryResponse)
def read_category(category_id: int, db: Session = Depends(get_mysql_db)):
    """특정 카테고리 조회"""
    try:
        manager = CategoryManager(db)
        category = manager.get_category(category_id)
        return category
    except Exception as e:
        logger.error(f"Error reading category {category_id}: {str(e)}")
        raise HTTPException(status_code=404, detail=f"Category {category_id} not found")

@router.get("/{category_id}/subcategories", response_model=List[CategoryResponse])
def read_subcategories(category_id: int, db: Session = Depends(get_mysql_db)):
    """하위 카테고리 조회"""
    try:
        manager = CategoryManager(db)
        return manager.get_subcategories(category_id)
    except Exception as e:
        logger.error(f"Error reading subcategories for {category_id}: {str(e)}")
        raise HTTPException(status_code=404, detail=f"Category {category_id} not found")

@router.post("/product-association")
def associate_product_with_category(
    association: ProductCategoryBase,
    db: Session = Depends(get_mysql_db)
):
    """상품과 카테고리 연결"""
    try:
        logger.info(f"Associating product {association.product_id} with category {association.category_id}")
        manager = CategoryManager(db)
        manager.associate_product_with_category(
            association.product_id, 
            association.category_id, 
            association.is_primary
        )
        return {"message": "Product associated with category successfully"}
    except Exception as e:
        logger.error(f"Error associating product with category: {str(e)}")
        raise HTTPException(status_code=400, detail=str(e))

@router.get("/{category_id}/products", response_model=List[str])
def get_products_in_category(
    category_id: int, 
    include_subcategories: bool = False,
    db: Session = Depends(get_mysql_db)
):
    """카테고리에 속한 상품 ID 목록 조회"""
    try:
        manager = CategoryManager(db)
        if include_subcategories:
            return manager.get_products_in_category_with_subcategories(category_id)
        else:
            return manager.get_products_in_category(category_id)
    except Exception as e:
        logger.error(f"Error getting products in category {category_id}: {str(e)}")
        raise HTTPException(status_code=404, detail=f"Category {category_id} not found")