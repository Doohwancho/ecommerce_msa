from fastapi import APIRouter, Depends, HTTPException, Query, Body
from typing import Dict, Any, Optional, List
from elasticsearch import AsyncElasticsearch # Keep for type hinting if service exposes client
from app.services.elasticsearch_service import ElasticsearchService
from app.config.elasticsearch import elasticsearch_config # Assuming this provides get_client()
from app.config.logging import logger # Assuming this is your configured logger
from datetime import datetime, timezone

from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode
from opentelemetry.semconv.trace import SpanAttributes # For semantic conventions

router = APIRouter()
# Use a specific name for the tracer, e.g., module path
tracer = trace.get_tracer("app.api.elasticsearch_router")

async def get_elasticsearch_service() -> ElasticsearchService:
    """
    Dependency to get ElasticsearchService instance.
    ElasticsearchInstrumentor should trace calls made by es_client if they are network-bound.
    This dependency function itself can be traced if it becomes more complex.
    """
    # If get_client() itself is a significant operation you want to trace separately:
    # with tracer.start_as_current_span("dep.get_elasticsearch_client") as client_span:
    # try:
    # es_client = await elasticsearch_config.get_client()
    # client_span.set_status(Status(StatusCode.OK))
    # return ElasticsearchService(es_client)
    #     except Exception as e:
    # logger.error(f"Failed to get Elasticsearch client for dependency: {e}", exc_info=True)
    #         client_span.record_exception(e)
    #         client_span.set_status(Status(StatusCode.ERROR, "Failed to get ES client"))
    # raise HTTPException(status_code=503, detail="Search service unavailable: client acquisition failed")
    es_client = await elasticsearch_config.get_client()
    return ElasticsearchService(es_client)

# --- Admin endpoints for index management ---
@router.post("/admin/create-index", summary="Create a new product search index")
async def create_index(
    es_service: ElasticsearchService = Depends(get_elasticsearch_service)
) -> Dict[str, Any]:
    """Create a new optimized product index"""
    with tracer.start_as_current_span("endpoint.admin.create_search_index") as span:
        span.set_attribute(SpanAttributes.HTTP_METHOD, "POST")
        span.set_attribute(SpanAttributes.HTTP_ROUTE, "/admin/create-index")
        # ElasticsearchInstrumentor will trace the actual es_service.create_product_index() call

        try:
            success = await es_service.create_product_index() # This calls ES client methods
            if not success:
                error_detail = "Failed to create Elasticsearch index via service"
                span.set_attribute(SpanAttributes.HTTP_STATUS_CODE, 500)
                span.set_status(Status(StatusCode.ERROR, error_detail))
                # Log this specific failure condition from the service
                logger.error(f"{error_detail} - service returned False.")
                # Create an HTTPException to be recorded and raised
                service_exc = HTTPException(status_code=500, detail=error_detail)
                span.record_exception(service_exc)
                setattr(service_exc, '_otel_recorded', True) # Mark as recorded
                raise service_exc
            
            span.set_status(Status(StatusCode.OK))
            return {"message": "Index created successfully"}
        except HTTPException as he:
            if not getattr(he, '_otel_recorded', False):
                if span.status.status_code == StatusCode.UNSET: # If not set by specific logic
                    span.set_attribute(SpanAttributes.HTTP_STATUS_CODE, he.status_code)
                    span.set_status(Status(StatusCode.ERROR, description=f"HTTPException: {he.detail}"))
                span.record_exception(he)
            raise
        except Exception as e:
            error_msg = f"Unhandled error creating index: {str(e)}"
            logger.error(error_msg, exc_info=True)
            span.set_attribute(SpanAttributes.HTTP_STATUS_CODE, 500)
            span.set_status(Status(StatusCode.ERROR, description=error_msg))
            span.record_exception(e)
            raise HTTPException(status_code=500, detail="An unexpected error occurred while creating the index.")

@router.post("/admin/reindex", summary="Perform full reindexing of all products")
async def reindex(
    es_service: ElasticsearchService = Depends(get_elasticsearch_service)
) -> Dict[str, Any]:
    """Perform full reindexing of all products"""
    with tracer.start_as_current_span("endpoint.admin.reindex_all_products") as span:
        span.set_attribute(SpanAttributes.HTTP_METHOD, "POST")
        span.set_attribute(SpanAttributes.HTTP_ROUTE, "/admin/reindex")

        try:
            result = await es_service.reindex_products()
            if result.get("error"): # Check for specific error key from service
                error_detail = f"Reindex service error: {result['error']}"
                span.set_attribute(SpanAttributes.HTTP_STATUS_CODE, 500) # Or map from result if available
                span.set_status(Status(StatusCode.ERROR, error_detail))
                logger.error(error_detail) # Log the specific error from service
                service_exc = HTTPException(status_code=500, detail=error_detail)
                span.record_exception(service_exc) # Record custom error context
                setattr(service_exc, '_otel_recorded', True)
                raise service_exc
            
            # Add attributes from result if useful, e.g., number of items reindexed
            span.set_attribute("app.reindex.documents_processed", result.get("processed_count", "N/A"))
            span.set_status(Status(StatusCode.OK))
            return result
        except HTTPException as he:
            if not getattr(he, '_otel_recorded', False):
                if span.status.status_code == StatusCode.UNSET:
                    span.set_attribute(SpanAttributes.HTTP_STATUS_CODE, he.status_code)
                    span.set_status(Status(StatusCode.ERROR, description=f"HTTPException: {he.detail}"))
                span.record_exception(he)
            raise
        except Exception as e:
            error_msg = f"Unhandled error during full reindex: {str(e)}"
            logger.error(error_msg, exc_info=True)
            span.set_attribute(SpanAttributes.HTTP_STATUS_CODE, 500)
            span.set_status(Status(StatusCode.ERROR, description=error_msg))
            span.record_exception(e)
            raise HTTPException(status_code=500, detail="An unexpected error occurred during reindexing.")

# Apply similar enhancements to other admin endpoints:
# incremental_reindex, reindex_specific_products, get_reindex_status, debug_dates

@router.post("/admin/incremental-reindex", summary="Perform incremental reindexing")
async def incremental_reindex(
    es_service: ElasticsearchService = Depends(get_elasticsearch_service)
) -> Dict[str, Any]:
    with tracer.start_as_current_span("endpoint.admin.incremental_reindex") as span:
        span.set_attribute(SpanAttributes.HTTP_METHOD, "POST")
        span.set_attribute(SpanAttributes.HTTP_ROUTE, "/admin/incremental-reindex")
        try:
            result = await es_service.incremental_reindex()
            if result.get("error"):
                error_detail = f"Incremental reindex service error: {result['error']}"
                span.set_attribute(SpanAttributes.HTTP_STATUS_CODE, 500)
                span.set_status(Status(StatusCode.ERROR, error_detail))
                logger.error(error_detail)
                service_exc = HTTPException(status_code=500, detail=error_detail)
                span.record_exception(service_exc)
                setattr(service_exc, '_otel_recorded', True)
                raise service_exc
            span.set_attribute("app.reindex.documents_processed", result.get("processed_count", "N/A"))
            span.set_status(Status(StatusCode.OK))
            return result
        except HTTPException as he:
            if not getattr(he, '_otel_recorded', False):
                if span.status.status_code == StatusCode.UNSET:
                    span.set_attribute(SpanAttributes.HTTP_STATUS_CODE, he.status_code)
                    span.set_status(Status(StatusCode.ERROR, f"HTTPException: {he.detail}"))
                span.record_exception(he)
            raise
        except Exception as e:
            error_msg = f"Unhandled error during incremental reindex: {str(e)}"
            logger.error(error_msg, exc_info=True)
            span.set_attribute(SpanAttributes.HTTP_STATUS_CODE, 500)
            span.set_status(Status(StatusCode.ERROR, error_msg))
            span.record_exception(e)
            raise HTTPException(status_code=500, detail="Unexpected error during incremental reindex.")

@router.post("/admin/reindex-specific", summary="Reindex specific products")
async def reindex_specific_products(
    product_ids: List[str] = Body(..., description="List of product IDs to reindex"),
    es_service: ElasticsearchService = Depends(get_elasticsearch_service)
) -> Dict[str, Any]:
    with tracer.start_as_current_span("endpoint.admin.reindex_specific_products") as span:
        span.set_attribute(SpanAttributes.HTTP_METHOD, "POST")
        span.set_attribute(SpanAttributes.HTTP_ROUTE, "/admin/reindex-specific")
        span.set_attribute("app.request.product_ids_count", len(product_ids))
        if product_ids: # Log a few example IDs, not all if potentially very long
             span.set_attribute("app.request.example_product_ids", str(product_ids[:min(3, len(product_ids))]))
        try:
            result = await es_service.reindex_specific_products(product_ids)
            if result.get("error"):
                error_detail = f"Specific reindex service error: {result['error']}"
                span.set_attribute(SpanAttributes.HTTP_STATUS_CODE, 500)
                span.set_status(Status(StatusCode.ERROR, error_detail))
                logger.error(f"{error_detail} for IDs: {product_ids}")
                service_exc = HTTPException(status_code=500, detail=error_detail)
                span.record_exception(service_exc)
                setattr(service_exc, '_otel_recorded', True)
                raise service_exc
            span.set_attribute("app.reindex.documents_processed", result.get("processed_count", len(product_ids))) # Assuming service might return count
            span.set_status(Status(StatusCode.OK))
            return result
        except HTTPException as he:
            if not getattr(he, '_otel_recorded', False):
                if span.status.status_code == StatusCode.UNSET:
                    span.set_attribute(SpanAttributes.HTTP_STATUS_CODE, he.status_code)
                    span.set_status(Status(StatusCode.ERROR, f"HTTPException: {he.detail}"))
                span.record_exception(he)
            raise
        except Exception as e:
            error_msg = f"Unhandled error during specific reindex for {len(product_ids)} products: {str(e)}"
            logger.error(error_msg, exc_info=True)
            span.set_attribute(SpanAttributes.HTTP_STATUS_CODE, 500)
            span.set_status(Status(StatusCode.ERROR, error_msg))
            span.record_exception(e)
            raise HTTPException(status_code=500, detail="Unexpected error during specific product reindex.")


@router.get("/admin/reindex-status", summary="Get status of the last reindexing operation")
async def get_reindex_status(
    es_service: ElasticsearchService = Depends(get_elasticsearch_service)
) -> Dict[str, Any]:
    with tracer.start_as_current_span("endpoint.admin.get_reindex_status") as span:
        span.set_attribute(SpanAttributes.HTTP_METHOD, "GET")
        span.set_attribute(SpanAttributes.HTTP_ROUTE, "/admin/reindex-status")
        try:
            last_reindex_time_str = await es_service.get_last_reindex_time() # Expecting ISO string
            # Initialize with a sensible default or handle None case
            if last_reindex_time_str is None:
                logger.warning("Last reindex time is not available from service.")
                span.set_attribute("app.reindex.status.last_time", "Not available")
                span.set_status(Status(StatusCode.OK)) # Or ERROR if this is unexpected
                return {
                    "message": "Last reindex time not available.",
                    "last_reindex_time": None,
                }

            last_reindex_datetime = datetime.fromisoformat(last_reindex_time_str)
            if last_reindex_datetime.tzinfo is None: # Ensure tz-aware
                last_reindex_datetime = last_reindex_datetime.replace(tzinfo=timezone.utc)
            
            current_time = datetime.now(timezone.utc)
            time_since_last_reindex = current_time - last_reindex_datetime

            span.set_attribute("app.reindex.status.last_time", last_reindex_datetime.isoformat())
            span.set_attribute("app.reindex.status.time_since_last_reindex_seconds", time_since_last_reindex.total_seconds())
            
            span.set_status(Status(StatusCode.OK))
            return {
                "last_reindex_time": last_reindex_datetime.isoformat(),
                "current_server_time": current_time.isoformat(),
                "time_since_last_reindex": str(time_since_last_reindex)
            }
        except ValueError as ve: # Catch specific error for fromisoformat
            error_msg = f"Invalid date format for last reindex time: {str(ve)}"
            logger.error(error_msg, exc_info=True)
            span.set_attribute(SpanAttributes.HTTP_STATUS_CODE, 500)
            span.set_status(Status(StatusCode.ERROR, error_msg))
            span.record_exception(ve)
            raise HTTPException(status_code=500, detail="Invalid date format for reindex status.")
        except Exception as e:
            error_msg = f"Error getting reindex status: {str(e)}"
            logger.error(error_msg, exc_info=True)
            span.set_attribute(SpanAttributes.HTTP_STATUS_CODE, 500)
            span.set_status(Status(StatusCode.ERROR, description=error_msg))
            span.record_exception(e)
            raise HTTPException(status_code=500, detail="Unexpected error getting reindex status.")

@router.get("/admin/debug-dates", summary="Debug date formats used in Elasticsearch service")
async def debug_dates(
    es_service: ElasticsearchService = Depends(get_elasticsearch_service)
):
    with tracer.start_as_current_span("endpoint.admin.debug_dates") as span:
        span.set_attribute(SpanAttributes.HTTP_METHOD, "GET")
        span.set_attribute(SpanAttributes.HTTP_ROUTE, "/admin/debug-dates")
        try:
            result = await es_service.debug_date_formats()
            # Potentially add attributes from result if it contains useful summary data
            span.set_status(Status(StatusCode.OK))
            return result
        except Exception as e:
            error_msg = f"Error debugging date formats: {str(e)}"
            logger.error(error_msg, exc_info=True)
            span.set_attribute(SpanAttributes.HTTP_STATUS_CODE, 500)
            span.set_status(Status(StatusCode.ERROR, description=error_msg))
            span.record_exception(e)
            raise HTTPException(status_code=500, detail="Unexpected error during date format debugging.")


# --- Search endpoints ---
# Apply a consistent pattern for all search endpoints

async def _handle_search_request(
    span_name: str,
    http_route: str,
    search_callable, # e.g., es_service.basic_search
    query_params: Dict[str, Any]
):
    with tracer.start_as_current_span(span_name) as span:
        span.set_attribute(SpanAttributes.HTTP_METHOD, "GET") # Assuming all searches are GET
        span.set_attribute(SpanAttributes.HTTP_ROUTE, http_route)
        for key, value in query_params.items():
            if value is not None: # Only set attribute if param is provided
                span.set_attribute(f"app.search.request.{key}", str(value)) # Convert all to str for safety
        
        try:
            result = await search_callable() # Call the specific search method
            
            hits = result.get("hits", {}).get("hits", []) # Safely access nested hits
            span.set_attribute("app.search.response.results_count", len(hits))
            # You could add total hits if available: result.get("hits", {}).get("total", {}).get("value")
            
            span.set_status(Status(StatusCode.OK))
            return result
        except HTTPException as he: # If service layer raises an HTTPException (e.g., bad query)
            if span.status.status_code == StatusCode.UNSET:
                span.set_attribute(SpanAttributes.HTTP_STATUS_CODE, he.status_code)
                span.set_status(Status(StatusCode.ERROR, description=f"HTTPException: {he.detail}"))
            span.record_exception(he)
            raise
        except Exception as e:
            query_str = query_params.get("query") or query_params.get("prefix") or "N/A"
            error_msg = f"Unhandled error in {span_name} for query '{query_str}': {str(e)}"
            logger.error(error_msg, exc_info=True)
            span.set_attribute(SpanAttributes.HTTP_STATUS_CODE, 500)
            span.set_status(Status(StatusCode.ERROR, description=error_msg))
            span.record_exception(e)
            # Be careful not to reflect raw query in error detail if it can contain sensitive info
            raise HTTPException(status_code=500, detail="An error occurred during your search.")

@router.get("/basic", summary="Basic search using all_text field")
async def basic_search(
    query: str = Query(..., description="Search query"),
    es_service: ElasticsearchService = Depends(get_elasticsearch_service)
) -> Dict[str, Any]:
    return await _handle_search_request(
        span_name="endpoint.search.basic",
        http_route="/basic",
        search_callable=lambda: es_service.basic_search(query),
        query_params={"query": query}
    )

@router.get("/weighted", summary="Search with field-specific weights")
async def weighted_search(
    query: str = Query(..., description="Search query"),
    es_service: ElasticsearchService = Depends(get_elasticsearch_service)
) -> Dict[str, Any]:
    return await _handle_search_request(
        span_name="endpoint.search.weighted",
        http_route="/weighted",
        search_callable=lambda: es_service.weighted_search(query),
        query_params={"query": query}
    )

@router.get("/autocomplete", summary="Autocomplete search")
async def autocomplete_search(
    prefix: str = Query(..., description="Search prefix for autocomplete"),
    es_service: ElasticsearchService = Depends(get_elasticsearch_service)
) -> Dict[str, Any]:
    return await _handle_search_request(
        span_name="endpoint.search.autocomplete",
        http_route="/autocomplete",
        search_callable=lambda: es_service.autocomplete_search(prefix),
        query_params={"prefix": prefix}
    )

@router.get("/fuzzy", summary="Fuzzy search with typo tolerance")
async def fuzzy_search(
    query: str = Query(..., description="Search query with typo tolerance"),
    es_service: ElasticsearchService = Depends(get_elasticsearch_service)
) -> Dict[str, Any]:
    return await _handle_search_request(
        span_name="endpoint.search.fuzzy",
        http_route="/fuzzy",
        search_callable=lambda: es_service.fuzzy_search(query),
        query_params={"query": query}
    )

@router.get("/advanced", summary="Advanced search with filters and aggregations")
async def advanced_search(
    query: str = Query(..., description="Search query"),
    brand: Optional[str] = Query(None, description="Filter by brand"),
    category: Optional[str] = Query(None, description="Filter by category"),
    min_price: Optional[float] = Query(None, description="Minimum price"),
    max_price: Optional[float] = Query(None, description="Maximum price"),
    # Add all other specific filter params from your original function
    processor: Optional[str] = Query(None), ram: Optional[str] = Query(None),
    storage: Optional[str] = Query(None), screen_size: Optional[str] = Query(None),
    resolution: Optional[str] = Query(None), material: Optional[str] = Query(None),
    size: Optional[str] = Query(None), fit: Optional[str] = Query(None),
    pattern: Optional[str] = Query(None),
    es_service: ElasticsearchService = Depends(get_elasticsearch_service)
) -> Dict[str, Any]:
    
    # Prepare filters and query_params for _handle_search_request
    filters = {}
    query_params_for_span = {"query": query}

    if brand: filters["brand"] = brand; query_params_for_span["filter_brand"] = brand
    if category: filters["category"] = category; query_params_for_span["filter_category"] = category
    
    price_filter = {}
    if min_price is not None: price_filter["gte"] = min_price; query_params_for_span["filter_min_price"] = min_price
    if max_price is not None: price_filter["lte"] = max_price; query_params_for_span["filter_max_price"] = max_price
    if price_filter: filters["price"] = price_filter # Assuming your service expects price filter like this

    attributes_filter = {}
    if processor: attributes_filter["processor"] = processor; query_params_for_span["filter_processor"] = processor
    if ram: attributes_filter["ram"] = ram; query_params_for_span["filter_ram"] = ram
    if storage: attributes_filter["storage"] = storage; query_params_for_span["filter_storage"] = storage
    if screen_size: attributes_filter["screen_size"] = screen_size; query_params_for_span["filter_screen_size"] = screen_size
    if resolution: attributes_filter["resolution"] = resolution; query_params_for_span["filter_resolution"] = resolution
    if material: attributes_filter["material"] = material; query_params_for_span["filter_material"] = material
    if size: attributes_filter["size"] = size; query_params_for_span["filter_size"] = size
    if fit: attributes_filter["fit"] = fit; query_params_for_span["filter_fit"] = fit
    if pattern: attributes_filter["pattern"] = pattern; query_params_for_span["filter_pattern"] = pattern
    if attributes_filter: filters["attributes"] = attributes_filter
            
    return await _handle_search_request(
        span_name="endpoint.search.advanced",
        http_route="/advanced",
        search_callable=lambda: es_service.advanced_search(query, filters=filters),
        query_params=query_params_for_span
    )