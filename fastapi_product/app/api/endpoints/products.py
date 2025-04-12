from fastapi import APIRouter, HTTPException, Depends
from typing import List, Optional
from app.schemas.product import ProductCreate, ProductUpdate, ProductResponse, ProductsExistRequest, ProductsExistResponse
from app.services.product_service import ProductService
from app.config.logging import logger

router = APIRouter()

@router.post("/", response_model=ProductResponse)
async def create_product(product: ProductCreate):
    """새 상품 생성"""
    try:
        service = ProductService()
        return await service.create_product(product)
    except Exception as e:
        logger.error(f"Failed to create product: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/{product_id}", response_model=ProductResponse)
async def get_product(product_id: str):
    """상품 조회"""
    try:
        service = ProductService()
        product = await service.get_product(product_id)
        if not product:
            raise HTTPException(status_code=404, detail=f"Product {product_id} not found")
        return product
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get product {product_id}: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@router.put("/{product_id}", response_model=ProductResponse)
async def update_product(product_id: str, product: ProductUpdate):
    """상품 업데이트"""
    try:
        service = ProductService()
        updated_product = await service.update_product(product_id, product)
        if not updated_product:
            raise HTTPException(status_code=404, detail=f"Product {product_id} not found")
        return updated_product
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to update product {product_id}: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@router.delete("/{product_id}")
async def delete_product(product_id: str):
    """상품 삭제"""
    try:
        service = ProductService()
        success = await service.delete_product(product_id)
        if not success:
            raise HTTPException(status_code=404, detail=f"Product {product_id} not found")
        return {"message": "Product deleted successfully"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to delete product {product_id}: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/", response_model=List[ProductResponse])
async def get_products(skip: int = 0, limit: int = 100):
    """상품 목록 조회"""
    try:
        service = ProductService()
        return await service.get_products(skip, limit)
    except Exception as e:
        logger.error(f"Failed to get products: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/check-exist", response_model=ProductsExistResponse)
async def check_products_exist(request: ProductsExistRequest):
    """여러 상품이 존재하는지 확인"""
    try:
        service = ProductService()
        return await service.check_products_exist(request.product_ids)
    except Exception as e:
        logger.error(f"Failed to check products existence: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))