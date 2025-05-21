from fastapi import APIRouter, HTTPException, Depends
from typing import List, Optional
from app.schemas.product import ProductCreate, ProductUpdate, ProductResponse, ProductsExistRequest, ProductsExistResponse
from app.services.product_service import ProductService
from app.config.logging import logger # Your custom logger

from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode
from opentelemetry.semconv.trace import SpanAttributes # For semantic conventions

router = APIRouter()
# Use a specific name for the tracer, e.g., module path
tracer = trace.get_tracer("app.api.product_router")

@router.post("/", response_model=ProductResponse, summary="Create a new product")
async def create_product(product: ProductCreate):
    """새 상품 생성"""
    with tracer.start_as_current_span("endpoint.create_product") as span:
        # Standard HTTP attributes
        span.set_attribute(SpanAttributes.HTTP_METHOD, "POST")
        span.set_attribute(SpanAttributes.HTTP_ROUTE, "/") # Or your specific route template

        # Application-specific attributes for the request
        span.set_attribute("app.product.request.title", product.title)
        span.set_attribute("app.product.request.brand", product.brand)
        # Only include SKU if it's not overly sensitive or high cardinality without aggregation
        span.set_attribute("app.product.request.sku", product.sku)
        span.set_attribute("app.product.request.price.amount", product.price.amount)
        span.set_attribute("app.product.request.stock", product.stock)

        # For lists/complex objects, consider logging counts or a summary, not the full content
        # if it can be large or sensitive.
        if product.category_ids:
            span.set_attribute("app.product.request.category_ids_count", len(product.category_ids))
        if product.primary_category_id:
            span.set_attribute("app.product.request.primary_category_id", product.primary_category_id)
        if product.variants:
            span.set_attribute("app.product.request.variants_count", len(product.variants))
        if product.images:
            span.set_attribute("app.product.request.images_count", len(product.images))

        try:
            service = ProductService() # Consider dependency injection for ProductService
            result = await service.create_product(product)

            span.set_attribute("app.product.response.id", result.product_id)
            span.set_status(Status(StatusCode.OK))
            return result
        except HTTPException as he:
            # If ProductService raises an HTTPException (e.g., validation error)
            span.set_attribute(SpanAttributes.HTTP_STATUS_CODE, he.status_code)
            span.set_status(Status(StatusCode.ERROR, description=f"HTTPException: {he.detail}"))
            span.record_exception(he)
            # Log the error with stack trace information if desired from here too
            # logger.error(f"HTTPException while creating product '{product.title}': {he.detail}", exc_info=True)
            raise
        except Exception as e:
            logger.error(f"Failed to create product '{product.title}': {str(e)}", exc_info=True)
            span.set_attribute(SpanAttributes.HTTP_STATUS_CODE, 500)
            span.set_status(Status(StatusCode.ERROR, description=f"Unhandled exception: {str(e)}"))
            span.record_exception(e)
            raise HTTPException(status_code=500, detail=f"An unexpected error occurred while creating the product: {str(e)}")

@router.get("/{product_id}", response_model=ProductResponse, summary="Get a specific product by ID")
async def get_product(product_id: str):
    """상품 조회"""
    with tracer.start_as_current_span("endpoint.get_product_by_id") as span:
        span.set_attribute(SpanAttributes.HTTP_METHOD, "GET")
        span.set_attribute(SpanAttributes.HTTP_ROUTE, "/{product_id}")
        span.set_attribute("app.product.request.id", product_id)

        try:
            service = ProductService()
            product_data = await service.get_product(product_id)

            if not product_data:
                not_found_detail = f"Product with ID '{product_id}' not found"
                span.set_attribute(SpanAttributes.HTTP_STATUS_CODE, 404)
                span.set_status(Status(StatusCode.ERROR, description=not_found_detail))
                not_found_exc = HTTPException(status_code=404, detail=not_found_detail)
                span.record_exception(not_found_exc) # Record the 404 exception
                raise not_found_exc

            span.set_status(Status(StatusCode.OK))
            return product_data
        except HTTPException as he:
            # This catches the 404 raised above or any HTTPException from the service
            if span.status.status_code == StatusCode.UNSET: # If status not already set by the 404 logic
                span.set_attribute(SpanAttributes.HTTP_STATUS_CODE, he.status_code)
                span.set_status(Status(StatusCode.ERROR, description=f"HTTPException: {he.detail}"))
            # Ensure exception is recorded if it wasn't the one created for the 404
            if not getattr(he, '_otel_recorded_for_404', False): # Simple flag to avoid double recording if already handled
                span.record_exception(he)
            raise
        except Exception as e:
            logger.error(f"Failed to get product '{product_id}': {str(e)}", exc_info=True)
            span.set_attribute(SpanAttributes.HTTP_STATUS_CODE, 500)
            span.set_status(Status(StatusCode.ERROR, description=f"Unhandled exception: {str(e)}"))
            span.record_exception(e)
            raise HTTPException(status_code=500, detail=f"An unexpected error occurred: {str(e)}")

@router.put("/{product_id}", response_model=ProductResponse, summary="Update an existing product")
async def update_product(product_id: str, product_update: ProductUpdate): # Changed param name
    """상품 업데이트"""
    with tracer.start_as_current_span("endpoint.update_product") as span:
        span.set_attribute(SpanAttributes.HTTP_METHOD, "PUT")
        span.set_attribute(SpanAttributes.HTTP_ROUTE, "/{product_id}")
        span.set_attribute("app.product.request.id", product_id)
        # Optionally log counts of fields being updated if ProductUpdate is complex
        # span.set_attribute("app.product.request.update_fields_count", len(product_update.dict(exclude_unset=True)))

        try:
            service = ProductService()
            updated_product_data = await service.update_product(product_id, product_update)

            if not updated_product_data:
                not_found_detail = f"Product with ID '{product_id}' not found for update"
                span.set_attribute(SpanAttributes.HTTP_STATUS_CODE, 404)
                span.set_status(Status(StatusCode.ERROR, description=not_found_detail))
                not_found_exc = HTTPException(status_code=404, detail=not_found_detail)
                span.record_exception(not_found_exc)
                raise not_found_exc

            span.set_status(Status(StatusCode.OK))
            return updated_product_data
        except HTTPException as he:
            if span.status.status_code == StatusCode.UNSET:
                span.set_attribute(SpanAttributes.HTTP_STATUS_CODE, he.status_code)
                span.set_status(Status(StatusCode.ERROR, description=f"HTTPException: {he.detail}"))
            if not getattr(he, '_otel_recorded_for_404', False):
                span.record_exception(he)
            raise
        except Exception as e:
            logger.error(f"Failed to update product '{product_id}': {str(e)}", exc_info=True)
            span.set_attribute(SpanAttributes.HTTP_STATUS_CODE, 500)
            span.set_status(Status(StatusCode.ERROR, description=f"Unhandled exception: {str(e)}"))
            span.record_exception(e)
            raise HTTPException(status_code=500, detail=f"An unexpected error occurred: {str(e)}")

@router.delete("/{product_id}", status_code=200, summary="Delete a product") # Explicit 200 for non-204 delete
async def delete_product(product_id: str):
    """상품 삭제"""
    with tracer.start_as_current_span("endpoint.delete_product") as span:
        span.set_attribute(SpanAttributes.HTTP_METHOD, "DELETE")
        span.set_attribute(SpanAttributes.HTTP_ROUTE, "/{product_id}")
        span.set_attribute("app.product.request.id", product_id)

        try:
            service = ProductService()
            success = await service.delete_product(product_id)

            if not success:
                not_found_detail = f"Product with ID '{product_id}' not found for deletion"
                span.set_attribute(SpanAttributes.HTTP_STATUS_CODE, 404)
                span.set_status(Status(StatusCode.ERROR, description=not_found_detail))
                not_found_exc = HTTPException(status_code=404, detail=not_found_detail)
                span.record_exception(not_found_exc)
                raise not_found_exc
            
            span.set_status(Status(StatusCode.OK))
            # For DELETE, often a 204 No Content is returned, or a 200/202 with a message.
            # If using 204, response_model should not be set or be None.
            # Current setup implies a JSON response.
            return {"message": "Product deleted successfully", "product_id": product_id}
        except HTTPException as he:
            if span.status.status_code == StatusCode.UNSET:
                span.set_attribute(SpanAttributes.HTTP_STATUS_CODE, he.status_code)
                span.set_status(Status(StatusCode.ERROR, description=f"HTTPException: {he.detail}"))
            if not getattr(he, '_otel_recorded_for_404', False):
                span.record_exception(he)
            raise
        except Exception as e:
            logger.error(f"Failed to delete product '{product_id}': {str(e)}", exc_info=True)
            span.set_attribute(SpanAttributes.HTTP_STATUS_CODE, 500)
            span.set_status(Status(StatusCode.ERROR, description=f"Unhandled exception: {str(e)}"))
            span.record_exception(e)
            raise HTTPException(status_code=500, detail=f"An unexpected error occurred: {str(e)}")

@router.get("/", response_model=List[ProductResponse], summary="Get a list of products with pagination")
async def get_products(skip: int = 0, limit: int = 100):
    """상품 목록 조회"""
    with tracer.start_as_current_span("endpoint.get_products_list") as span: # More specific name
        span.set_attribute(SpanAttributes.HTTP_METHOD, "GET")
        span.set_attribute(SpanAttributes.HTTP_ROUTE, "/") # Assuming this is the root for product listing
        span.set_attribute("app.pagination.request.skip", skip)
        span.set_attribute("app.pagination.request.limit", limit)

        try:
            service = ProductService()
            products_data = await service.get_products(skip=skip, limit=limit)
            span.set_attribute("app.products.response.count", len(products_data))
            span.set_status(Status(StatusCode.OK))
            return products_data
        except HTTPException as he: # If service layer raises an HTTPException
            span.set_attribute(SpanAttributes.HTTP_STATUS_CODE, he.status_code)
            span.set_status(Status(StatusCode.ERROR, description=f"HTTPException: {he.detail}"))
            span.record_exception(he)
            raise
        except Exception as e:
            logger.error(f"Failed to get products list (skip={skip}, limit={limit}): {str(e)}", exc_info=True)
            span.set_attribute(SpanAttributes.HTTP_STATUS_CODE, 500)
            span.set_status(Status(StatusCode.ERROR, description=f"Unhandled exception: {str(e)}"))
            span.record_exception(e)
            raise HTTPException(status_code=500, detail=f"An unexpected error occurred: {str(e)}")

@router.post("/check-exist", response_model=ProductsExistResponse, summary="Check if multiple products exist by IDs")
async def check_products_exist(request: ProductsExistRequest):
    """여러 상품이 존재하는지 확인"""
    with tracer.start_as_current_span("endpoint.check_products_exist") as span:
        span.set_attribute(SpanAttributes.HTTP_METHOD, "POST")
        span.set_attribute(SpanAttributes.HTTP_ROUTE, "/check-exist")
        span.set_attribute("app.products.request.ids_count", len(request.product_ids))
        # Avoid logging all IDs if the list can be very long
        # if request.product_ids: span.set_attribute("app.products.request.example_ids", str(request.product_ids[:3]))


        try:
            service = ProductService()
            result = await service.check_products_exist(request.product_ids)
            # Add some response attributes if useful, e.g., count of existing ones from result
            # span.set_attribute("app.products.response.existing_map_size", len(result.exists_map))
            span.set_status(Status(StatusCode.OK))
            return result
        except HTTPException as he:
            span.set_attribute(SpanAttributes.HTTP_STATUS_CODE, he.status_code)
            span.set_status(Status(StatusCode.ERROR, description=f"HTTPException: {he.detail}"))
            span.record_exception(he)
            raise
        except Exception as e:
            logger.error(f"Failed to check products existence for {len(request.product_ids)} IDs: {str(e)}", exc_info=True)
            span.set_attribute(SpanAttributes.HTTP_STATUS_CODE, 500)
            span.set_status(Status(StatusCode.ERROR, description=f"Unhandled exception: {str(e)}"))
            span.record_exception(e)
            raise HTTPException(status_code=500, detail=f"An unexpected error occurred: {str(e)}")

@router.get("/mongodb/{product_id}", response_model=ProductResponse, summary="Get product from MongoDB (benchmark test)")
async def get_product_mongodb_only(product_id: str):
    """MongoDB에서만 상품 조회 (benchmark test용)"""
    with tracer.start_as_current_span("endpoint.get_product_mongodb_only") as span:
        span.set_attribute(SpanAttributes.HTTP_METHOD, "GET")
        span.set_attribute(SpanAttributes.HTTP_ROUTE, "/mongodb/{product_id}")
        span.set_attribute("app.product.request.id", product_id)
        span.set_attribute("app.product.request.source", "mongodb_only") # Custom attribute for context

        try:
            service = ProductService()
            product_data = await service.get_product_mongodb_only(product_id)

            if not product_data:
                not_found_detail = f"Product with ID '{product_id}' not found in MongoDB"
                span.set_attribute(SpanAttributes.HTTP_STATUS_CODE, 404)
                span.set_status(Status(StatusCode.ERROR, description=not_found_detail))
                not_found_exc = HTTPException(status_code=404, detail=not_found_detail)
                span.record_exception(not_found_exc)
                # Add a flag to the exception to indicate it was recorded for OTel, to potentially avoid double recording
                # setattr(not_found_exc, '_otel_recorded_for_404', True)
                raise not_found_exc

            span.set_status(Status(StatusCode.OK))
            return product_data
        except HTTPException as he:
            if span.status.status_code == StatusCode.UNSET:
                span.set_attribute(SpanAttributes.HTTP_STATUS_CODE, he.status_code)
                span.set_status(Status(StatusCode.ERROR, description=f"HTTPException: {he.detail}"))
            if not getattr(he, '_otel_recorded_for_404', False):
                span.record_exception(he)
            raise
        except Exception as e:
            logger.error(f"Failed to get product from MongoDB '{product_id}': {str(e)}", exc_info=True)
            span.set_attribute(SpanAttributes.HTTP_STATUS_CODE, 500)
            span.set_status(Status(StatusCode.ERROR, description=f"Unhandled exception: {str(e)}"))
            span.record_exception(e)
            raise HTTPException(status_code=500, detail=f"An unexpected error occurred: {str(e)}")