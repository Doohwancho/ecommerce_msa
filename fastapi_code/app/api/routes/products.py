from fastapi import APIRouter, HTTPException, Depends, Query
from typing import List, Optional
from app.schemas.product import ProductCreate, ProductUpdate, ProductResponse
from app.services.product_service import ProductService
from app.config.database import product_collection
from app.config.logging import logger

router = APIRouter()

def get_product_service():
    return ProductService(product_collection)

@router.post("/", response_model=ProductResponse)
async def create_product(
    product: ProductCreate,
    product_service: ProductService = Depends(get_product_service)
):
    try:
        logger.info(f"Creating product: {product.title}")
        result = product_service.create_product(product)
        logger.info(f"Product created: {result.product_id}")
        return result
    except Exception as e:
        logger.error(f"Error creating product: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/{product_id}", response_model=ProductResponse)
async def get_product(
    product_id: str,
    product_service: ProductService = Depends(get_product_service)
):
    product = product_service.get_product(product_id)
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    return product

@router.put("/{product_id}", response_model=ProductResponse)
async def update_product(
    product_id: str,
    product: ProductUpdate,
    product_service: ProductService = Depends(get_product_service)
):
    updated_product = product_service.update_product(product_id, product)
    if not updated_product:
        raise HTTPException(status_code=404, detail="Product not found")
    return updated_product

@router.delete("/{product_id}")
async def delete_product(
    product_id: str,
    product_service: ProductService = Depends(get_product_service)
):
    success = product_service.delete_product(product_id)
    if not success:
        raise HTTPException(status_code=404, detail="Product not found")
    return {"message": "Product deleted successfully"}

@router.get("/", response_model=List[ProductResponse])
async def list_products(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    product_service: ProductService = Depends(get_product_service)
):
    products = product_service.list_products(skip, limit)
    return products

@router.get("/category/{category_id}", response_model=List[ProductResponse])
async def get_products_by_category(
    category_id: int,
    product_service: ProductService = Depends(get_product_service)
):
    products = product_service.find_products_by_category(category_id)
    return products

@router.get("/search/", response_model=List[ProductResponse])
async def search_products(
    q: str,
    product_service: ProductService = Depends(get_product_service)
):
    products = product_service.search_products(q)
    return products
