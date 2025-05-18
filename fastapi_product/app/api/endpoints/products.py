from fastapi import APIRouter, HTTPException, Depends
from typing import List, Optional
from app.schemas.product import ProductCreate, ProductUpdate, ProductResponse, ProductsExistRequest, ProductsExistResponse
from app.services.product_service import ProductService
from app.config.logging import logger
from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode

router = APIRouter()
tracer = trace.get_tracer(__name__)

@router.post("/", response_model=ProductResponse)
async def create_product(product: ProductCreate):
    """새 상품 생성"""
    with tracer.start_as_current_span("create_product") as span:
        try:
            # Basic product information
            span.set_attribute("product.title", product.title)
            span.set_attribute("product.brand", product.brand)
            span.set_attribute("product.model", product.model)
            span.set_attribute("product.sku", product.sku)
            
            # Category information
            # span.set_attribute("product.category_ids", str(product.category_ids))
            # span.set_attribute("product.primary_category_id", product.primary_category_id)
            # span.set_attribute("product.category_level", product.category_level)
            
            # Price and stock information
            span.set_attribute("product.price.amount", product.price.amount)
            # span.set_attribute("product.price.currency", product.price.currency)
            span.set_attribute("product.stock", product.stock)
            
            # Variants information
            # span.set_attribute("product.variants.count", len(product.variants))
            
            # Images information
            # span.set_attribute("product.images.count", len(product.images))
            
            service = ProductService()
            result = await service.create_product(product)
            span.set_status(Status(StatusCode.OK))
            return result
        except Exception as e:
            span.set_status(Status(StatusCode.ERROR, str(e)))
            logger.error(f"Failed to create product: {str(e)}")
            raise HTTPException(status_code=500, detail=str(e))

@router.get("/{product_id}", response_model=ProductResponse)
async def get_product(product_id: str):
    """상품 조회"""
    with tracer.start_as_current_span("get_product") as span:
        try:
            span.set_attribute("product.id", product_id)
            service = ProductService()
            product = await service.get_product(product_id)
            if not product:
                span.set_status(Status(StatusCode.ERROR, f"Product {product_id} not found"))
                raise HTTPException(status_code=404, detail=f"Product {product_id} not found")
            span.set_status(Status(StatusCode.OK))
            return product
        except HTTPException:
            raise
        except Exception as e:
            span.set_status(Status(StatusCode.ERROR, str(e)))
            logger.error(f"Failed to get product {product_id}: {str(e)}")
            raise HTTPException(status_code=500, detail=str(e))

@router.put("/{product_id}", response_model=ProductResponse)
async def update_product(product_id: str, product: ProductUpdate):
    """상품 업데이트"""
    with tracer.start_as_current_span("update_product") as span:
        try:
            span.set_attribute("product.id", product_id)
            service = ProductService()
            updated_product = await service.update_product(product_id, product)
            if not updated_product:
                span.set_status(Status(StatusCode.ERROR, f"Product {product_id} not found"))
                raise HTTPException(status_code=404, detail=f"Product {product_id} not found")
            span.set_status(Status(StatusCode.OK))
            return updated_product
        except HTTPException:
            raise
        except Exception as e:
            span.set_status(Status(StatusCode.ERROR, str(e)))
            logger.error(f"Failed to update product {product_id}: {str(e)}")
            raise HTTPException(status_code=500, detail=str(e))

@router.delete("/{product_id}")
async def delete_product(product_id: str):
    """상품 삭제"""
    with tracer.start_as_current_span("delete_product") as span:
        try:
            span.set_attribute("product.id", product_id)
            service = ProductService()
            success = await service.delete_product(product_id)
            if not success:
                span.set_status(Status(StatusCode.ERROR, f"Product {product_id} not found"))
                raise HTTPException(status_code=404, detail=f"Product {product_id} not found")
            span.set_status(Status(StatusCode.OK))
            return {"message": "Product deleted successfully"}
        except HTTPException:
            raise
        except Exception as e:
            span.set_status(Status(StatusCode.ERROR, str(e)))
            logger.error(f"Failed to delete product {product_id}: {str(e)}")
            raise HTTPException(status_code=500, detail=str(e))

@router.get("/", response_model=List[ProductResponse])
async def get_products(skip: int = 0, limit: int = 100):
    """상품 목록 조회"""
    with tracer.start_as_current_span("get_products") as span:
        try:
            span.set_attribute("pagination.skip", skip)
            span.set_attribute("pagination.limit", limit)
            service = ProductService()
            products = await service.get_products(skip, limit)
            span.set_attribute("products.count", len(products))
            span.set_status(Status(StatusCode.OK))
            return products
        except Exception as e:
            span.set_status(Status(StatusCode.ERROR, str(e)))
            logger.error(f"Failed to get products: {str(e)}")
            raise HTTPException(status_code=500, detail=str(e))

@router.post("/check-exist", response_model=ProductsExistResponse)
async def check_products_exist(request: ProductsExistRequest):
    """여러 상품이 존재하는지 확인"""
    with tracer.start_as_current_span("check_products_exist") as span:
        try:
            span.set_attribute("products.count", len(request.product_ids))
            service = ProductService()
            result = await service.check_products_exist(request.product_ids)
            span.set_status(Status(StatusCode.OK))
            return result
        except Exception as e:
            span.set_status(Status(StatusCode.ERROR, str(e)))
            logger.error(f"Failed to check products existence: {str(e)}")
            raise HTTPException(status_code=500, detail=str(e))

@router.get("/mongodb/{product_id}", response_model=ProductResponse)
async def get_product_mongodb_only(product_id: str):
    """MongoDB에서만 상품 조회 (benchmark test용)"""
    with tracer.start_as_current_span("get_product_mongodb_only") as span:
        try:
            span.set_attribute("product.id", product_id)
            service = ProductService()
            product = await service.get_product_mongodb_only(product_id)
            if not product:
                span.set_status(Status(StatusCode.ERROR, f"Product {product_id} not found in MongoDB"))
                raise HTTPException(status_code=404, detail=f"Product {product_id} not found in MongoDB")
            span.set_status(Status(StatusCode.OK))
            return product
        except HTTPException:
            raise
        except Exception as e:
            span.set_status(Status(StatusCode.ERROR, str(e)))
            logger.error(f"Failed to get product from MongoDB {product_id}: {str(e)}")
            raise HTTPException(status_code=500, detail=str(e))