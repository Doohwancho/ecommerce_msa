from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List, Optional

from app.config.database import get_mysql_db
from app.models.category import Category
from app.schemas.category import (
    CategoryCreate, 
    CategoryResponse, 
    ProductCategoryBase, 
    ProductCategoryResponse
)
from app.api.dependencies import get_category_manager
from app.services.category_manager import CategoryManager
from app.config.logging import logger

router = APIRouter()

@router.post("/", response_model=CategoryResponse)
def create_category(
    category: CategoryCreate, 
    manager: CategoryManager = Depends(get_category_manager)
):
    try:
        logger.info(f"Creating category: {category.name}")
        db_category = manager.create_category(category.name, category.parent_id)
        logger.info(f"Category created: {db_category.category_id}")
        return db_category
    except Exception as e:
        logger.error(f"Error creating category: {str(e)}")
        raise HTTPException(status_code=400, detail=str(e))

@router.get("/{category_id}", response_model=CategoryResponse)
def get_category(
    category_id: int, 
    db: Session = Depends(get_mysql_db)
):
    category = db.query(Category).filter(Category.category_id == category_id).first()
    if not category:
        raise HTTPException(status_code=404, detail="Category not found")
    return category

@router.get("/", response_model=List[CategoryResponse])
def list_categories(
    skip: int = 0, 
    limit: int = 100, 
    db: Session = Depends(get_mysql_db)
):
    categories = db.query(Category).offset(skip).limit(limit).all()
    return categories

@router.get("/{category_id}/subcategories", response_model=List[CategoryResponse])
def get_subcategories(
    category_id: int, 
    manager: CategoryManager = Depends(get_category_manager)
):
    try:
        subcategories = manager.get_subcategories(category_id)
        return subcategories
    except Exception as e:
        raise HTTPException(status_code=404, detail=str(e))

@router.get("/{category_id}/ancestors", response_model=List[CategoryResponse])
def get_ancestors(
    category_id: int, 
    manager: CategoryManager = Depends(get_category_manager)
):
    try:
        ancestors = manager.get_ancestors(category_id)
        return ancestors
    except Exception as e:
        raise HTTPException(status_code=404, detail=str(e))

@router.put("/{category_id}/move", response_model=dict)
def move_category(
    category_id: int, 
    new_parent_id: Optional[int] = None, 
    manager: CategoryManager = Depends(get_category_manager)
):
    try:
        success = manager.move_category(category_id, new_parent_id)
        return {"success": success, "message": "Category moved successfully"}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/product-association", response_model=dict)
def associate_product(
    product_category: ProductCategoryBase, 
    manager: CategoryManager = Depends(get_category_manager)
):
    try:
        success = manager.associate_product_with_category(
            product_category.product_id, 
            product_category.category_id, 
            product_category.is_primary
        )
        return {"success": success, "message": "Product associated with category successfully"}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.get("/{category_id}/products", response_model=List[ProductCategoryResponse])
def get_products_by_category(
    category_id: int, 
    include_subcategories: bool = False, 
    manager: CategoryManager = Depends(get_category_manager)
):
    try:
        products = manager.get_products_by_category(category_id, include_subcategories)
        return products
    except Exception as e:
        raise HTTPException(status_code=404, detail=str(e))
