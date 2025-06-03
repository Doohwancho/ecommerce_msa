from fastapi import APIRouter, Depends, HTTPException, Query, Body
from typing import Dict, Any, Optional, List
from elasticsearch import AsyncElasticsearch # Keep for type hinting if service exposes client
from app.services.elasticsearch_service import ElasticsearchService
from app.config.elasticsearch import elasticsearch_config # Assuming this provides get_client()
import logging # Changed from app.config.logging import logger
from datetime import datetime, timezone

from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode
from opentelemetry.semconv.trace import SpanAttributes # For semantic conventions

router = APIRouter()
# Use a specific name for the tracer, e.g., module path
tracer = trace.get_tracer("app.api.elasticsearch_router")

logger = logging.getLogger(__name__) # Added this line

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
        logger.info("Attempting to create search index.")
        try:
            success = await es_service.create_product_index()
            if not success:
                error_detail = "Failed to create Elasticsearch index via service"
                span.set_attribute(SpanAttributes.HTTP_STATUS_CODE, 500)
                span.set_status(Status(StatusCode.ERROR, error_detail))
                logger.error("Index creation failed as reported by service.", extra={"detail": error_detail})
                service_exc = HTTPException(status_code=500, detail=error_detail)
                setattr(service_exc, '_otel_recorded', True)
                span.record_exception(service_exc)
                raise service_exc
            
            span.set_status(Status(StatusCode.OK))
            logger.info("Search index created successfully.")
            return {"message": "Index created successfully"}
        except HTTPException as he:
            if not getattr(he, '_otel_recorded', False):
                if span.status.status_code == StatusCode.UNSET:
                    span.set_attribute(SpanAttributes.HTTP_STATUS_CODE, he.status_code)
                    span.set_status(Status(StatusCode.ERROR, description=f"HTTPException: {he.detail}"))
                span.record_exception(he)
                logger.warning("HTTPException during index creation.", 
                               extra={"status_code": he.status_code, "detail": he.detail})
            raise
        except Exception as e:
            logger.error("Unhandled error creating index.", extra={"error": str(e)}, exc_info=True)
            span.set_attribute(SpanAttributes.HTTP_STATUS_CODE, 500)
            span.set_status(Status(StatusCode.ERROR, description=f"Unhandled error: {str(e)}"))
            span.record_exception(e)
            raise HTTPException(status_code=500, detail=f"An unexpected error occurred: {str(e)}")

@router.post("/admin/reindex", summary="Perform full reindexing of all products")
async def reindex(
    es_service: ElasticsearchService = Depends(get_elasticsearch_service)
) -> Dict[str, Any]:
    """Perform full reindexing of all products"""
    with tracer.start_as_current_span("endpoint.admin.reindex_all_products") as span:
        span.set_attribute(SpanAttributes.HTTP_METHOD, "POST")
        span.set_attribute(SpanAttributes.HTTP_ROUTE, "/admin/reindex")
        logger.info("Attempting full reindex of all products.")
        try:
            result = await es_service.reindex_products()
            if result.get("error"):
                error_detail = result['error']
                span.set_attribute(SpanAttributes.HTTP_STATUS_CODE, 500)
                span.set_status(Status(StatusCode.ERROR, error_detail))
                logger.error("Full reindex failed as reported by service.", extra={"detail": error_detail})
                service_exc = HTTPException(status_code=500, detail=error_detail)
                setattr(service_exc, '_otel_recorded', True)
                span.record_exception(service_exc)
                raise service_exc
            
            processed_count = result.get("processed_count", "N/A")
            span.set_attribute("app.reindex.documents_processed", processed_count)
            span.set_status(Status(StatusCode.OK))
            logger.info("Full reindex completed.", extra={"processed_count": processed_count, "result_summary": result.get("message", "Success")})
            return result
        except HTTPException as he:
            if not getattr(he, '_otel_recorded', False):
                if span.status.status_code == StatusCode.UNSET:
                    span.set_attribute(SpanAttributes.HTTP_STATUS_CODE, he.status_code)
                    span.set_status(Status(StatusCode.ERROR, description=f"HTTPException: {he.detail}"))
                span.record_exception(he)
                logger.warning("HTTPException during full reindex.", extra={"status_code": he.status_code, "detail": he.detail})
            raise
        except Exception as e:
            logger.error("Unhandled error during full reindex.", extra={"error": str(e)}, exc_info=True)
            span.set_attribute(SpanAttributes.HTTP_STATUS_CODE, 500)
            span.set_status(Status(StatusCode.ERROR, description=f"Unhandled error: {str(e)}"))
            span.record_exception(e)
            raise HTTPException(status_code=500, detail=f"An unexpected error occurred: {str(e)}")

# Apply similar enhancements to other admin endpoints:
# incremental_reindex, reindex_specific_products, get_reindex_status, debug_dates

@router.post("/admin/incremental-reindex", summary="Perform incremental reindexing")
async def incremental_reindex(
    es_service: ElasticsearchService = Depends(get_elasticsearch_service)
) -> Dict[str, Any]:
    with tracer.start_as_current_span("endpoint.admin.incremental_reindex") as span:
        span.set_attribute(SpanAttributes.HTTP_METHOD, "POST")
        span.set_attribute(SpanAttributes.HTTP_ROUTE, "/admin/incremental-reindex")
        logger.info("Attempting incremental reindex.")
        try:
            result = await es_service.incremental_reindex()
            if result.get("error"):
                error_detail = result['error']
                span.set_attribute(SpanAttributes.HTTP_STATUS_CODE, 500)
                span.set_status(Status(StatusCode.ERROR, error_detail))
                logger.error("Incremental reindex failed as reported by service.", extra={"detail": error_detail})
                service_exc = HTTPException(status_code=500, detail=error_detail)
                setattr(service_exc, '_otel_recorded', True)
                span.record_exception(service_exc)
                raise service_exc
            processed_count = result.get("processed_count", "N/A")
            span.set_attribute("app.reindex.documents_processed", processed_count)
            span.set_status(Status(StatusCode.OK))
            logger.info("Incremental reindex completed.", extra={"processed_count": processed_count, "result_summary": result.get("message", "Success")})
            return result
        except HTTPException as he:
            if not getattr(he, '_otel_recorded', False):
                if span.status.status_code == StatusCode.UNSET:
                    span.set_attribute(SpanAttributes.HTTP_STATUS_CODE, he.status_code)
                    span.set_status(Status(StatusCode.ERROR, f"HTTPException: {he.detail}"))
                span.record_exception(he)
                logger.warning("HTTPException during incremental reindex.", extra={"status_code": he.status_code, "detail": he.detail})
            raise
        except Exception as e:
            logger.error("Unhandled error during incremental reindex.", extra={"error": str(e)}, exc_info=True)
            span.set_attribute(SpanAttributes.HTTP_STATUS_CODE, 500)
            span.set_status(Status(StatusCode.ERROR, f"Unhandled error: {str(e)}"))
            span.record_exception(e)
            raise HTTPException(status_code=500, detail=f"An unexpected error occurred: {str(e)}")

@router.post("/admin/reindex-specific", summary="Reindex specific products")
async def reindex_specific_products(
    product_ids: List[str] = Body(..., description="List of product IDs to reindex"),
    es_service: ElasticsearchService = Depends(get_elasticsearch_service)
) -> Dict[str, Any]:
    with tracer.start_as_current_span("endpoint.admin.reindex_specific_products") as span:
        span.set_attribute(SpanAttributes.HTTP_METHOD, "POST")
        span.set_attribute(SpanAttributes.HTTP_ROUTE, "/admin/reindex-specific")
        ids_count = len(product_ids)
        span.set_attribute("app.request.product_ids_count", ids_count)
        if product_ids: span.set_attribute("app.request.example_product_ids", str(product_ids[:min(3, ids_count)]))
        logger.info("Attempting specific reindex.", extra={"product_ids_count": ids_count})
        try:
            result = await es_service.reindex_specific_products(product_ids)
            if result.get("error"):
                error_detail = result['error']
                span.set_attribute(SpanAttributes.HTTP_STATUS_CODE, 500)
                span.set_status(Status(StatusCode.ERROR, error_detail))
                logger.error("Specific reindex failed as reported by service.", 
                               extra={"detail": error_detail, "product_ids_count": ids_count})
                service_exc = HTTPException(status_code=500, detail=error_detail)
                setattr(service_exc, '_otel_recorded', True)
                span.record_exception(service_exc)
                raise service_exc
            processed_count = result.get("processed_count", ids_count)
            span.set_attribute("app.reindex.documents_processed", processed_count)
            span.set_status(Status(StatusCode.OK))
            logger.info("Specific reindex completed.", 
                        extra={"requested_ids_count": ids_count, "processed_count": processed_count, "result_summary": result.get("message", "Success")})
            return result
        except HTTPException as he:
            if not getattr(he, '_otel_recorded', False):
                if span.status.status_code == StatusCode.UNSET:
                    span.set_attribute(SpanAttributes.HTTP_STATUS_CODE, he.status_code)
                    span.set_status(Status(StatusCode.ERROR, f"HTTPException: {he.detail}"))
                span.record_exception(he)
                logger.warning("HTTPException during specific reindex.", 
                               extra={"product_ids_count": ids_count, "status_code": he.status_code, "detail": he.detail})
            raise
        except Exception as e:
            logger.error("Unhandled error during specific reindex.", 
                         extra={"product_ids_count": ids_count, "error": str(e)}, 
                         exc_info=True)
            span.set_attribute(SpanAttributes.HTTP_STATUS_CODE, 500)
            span.set_status(Status(StatusCode.ERROR, f"Unhandled error: {str(e)}"))
            span.record_exception(e)
            raise HTTPException(status_code=500, detail=f"An unexpected error occurred: {str(e)}")

@router.get("/admin/reindex-status", summary="Get status of the last reindexing operation")
async def get_reindex_status(
    es_service: ElasticsearchService = Depends(get_elasticsearch_service)
) -> Dict[str, Any]:
    with tracer.start_as_current_span("endpoint.admin.get_reindex_status") as span:
        span.set_attribute(SpanAttributes.HTTP_METHOD, "GET")
        span.set_attribute(SpanAttributes.HTTP_ROUTE, "/admin/reindex-status")
        logger.info("Attempting to get reindex status.")
        try:
            last_reindex_time_str = await es_service.get_last_reindex_time()
            if last_reindex_time_str is None:
                logger.warning("Last reindex time is not available from service.")
                span.set_attribute("app.reindex.status.last_time", "Not available")
                span.set_status(Status(StatusCode.OK))
                return {"message": "Last reindex time not available", "last_reindex_time": None}

            last_reindex_datetime = datetime.fromisoformat(last_reindex_time_str)
            if last_reindex_datetime.tzinfo is None: last_reindex_datetime = last_reindex_datetime.replace(tzinfo=timezone.utc)
            current_time = datetime.now(timezone.utc)
            time_since_last_reindex = current_time - last_reindex_datetime

            span.set_attribute("app.reindex.status.last_time", last_reindex_datetime.isoformat())
            span.set_attribute("app.reindex.status.time_since_last_reindex_seconds", time_since_last_reindex.total_seconds())
            span.set_status(Status(StatusCode.OK))
            logger.info("Successfully retrieved reindex status.", 
                        extra={"last_reindex_time": last_reindex_datetime.isoformat(), "time_since_last_reindex_seconds": time_since_last_reindex.total_seconds()})
            return {
                "last_reindex_time": last_reindex_datetime.isoformat(),
                "current_server_time": current_time.isoformat(),
                "time_since_last_reindex": str(time_since_last_reindex)
            }
        except ValueError as ve:
            logger.error("Invalid date format for last reindex time.", extra={"error": str(ve)}, exc_info=True)
            span.set_attribute(SpanAttributes.HTTP_STATUS_CODE, 500)
            span.set_status(Status(StatusCode.ERROR, f"Invalid date format: {str(ve)}"))
            span.record_exception(ve)
            raise HTTPException(status_code=500, detail=f"Invalid date format for reindex status: {str(ve)}")
        except Exception as e:
            logger.error("Error getting reindex status.", extra={"error": str(e)}, exc_info=True)
            span.set_attribute(SpanAttributes.HTTP_STATUS_CODE, 500)
            span.set_status(Status(StatusCode.ERROR, description=f"Unhandled error: {str(e)}"))
            span.record_exception(e)
            raise HTTPException(status_code=500, detail=f"An unexpected error occurred: {str(e)}")

@router.get("/admin/debug-dates", summary="Debug date formats used in Elasticsearch service")
async def debug_dates(
    es_service: ElasticsearchService = Depends(get_elasticsearch_service)
):
    with tracer.start_as_current_span("endpoint.admin.debug_dates") as span:
        span.set_attribute(SpanAttributes.HTTP_METHOD, "GET")
        span.set_attribute(SpanAttributes.HTTP_ROUTE, "/admin/debug-dates")
        logger.info("Attempting to debug date formats.")
        try:
            result = await es_service.debug_date_formats()
            span.set_status(Status(StatusCode.OK))
            logger.info("Date format debugging successful.", extra={"result_keys": list(result.keys()) if isinstance(result, dict) else None})
            return result
        except Exception as e:
            logger.error("Error debugging date formats.", extra={"error": str(e)}, exc_info=True)
            span.set_attribute(SpanAttributes.HTTP_STATUS_CODE, 500)
            span.set_status(Status(StatusCode.ERROR, description=f"Unhandled error: {str(e)}"))
            span.record_exception(e)
            raise HTTPException(status_code=500, detail=f"An unexpected error occurred: {str(e)}")


# --- Search endpoints ---
# Apply a consistent pattern for all search endpoints

async def _handle_search_request(
    span_name: str,
    http_route: str,
    search_callable, # e.g., es_service.basic_search
    query_params: Dict[str, Any],
    endpoint_name: str # For logging
):
    with tracer.start_as_current_span(span_name) as span:
        span.set_attribute(SpanAttributes.HTTP_METHOD, "GET") # Assuming all searches are GET
        span.set_attribute(SpanAttributes.HTTP_ROUTE, http_route)
        log_extra = {}
        for key, value in query_params.items():
            if value is not None: # Only set attribute if param is provided
                span_attr_key = f"app.search.request.{key}"
                log_extra_key = key # Use original key for logger's `extra`
                span.set_attribute(span_attr_key, str(value))
                log_extra[log_extra_key] = value
        
        logger.info(f"Attempting {endpoint_name} search.", extra=log_extra)
        try:
            result = await search_callable() # Call the specific search method
            
            hits = result.get("hits", {}).get("hits", []) # Safely access nested hits
            response_results_count = len(hits)
            total_hits = result.get("hits", {}).get("total", {}).get("value", "N/A")
            span.set_attribute("app.search.response.results_count", response_results_count)
            span.set_attribute("app.search.response.total_hits", total_hits)
            
            span.set_status(Status(StatusCode.OK))
            logger.info(f"{endpoint_name} search successful.", 
                        extra=dict(log_extra, results_count=response_results_count, total_hits=total_hits))
            return result
        except HTTPException as he: # If service layer raises an HTTPException (e.g., bad query)
            if span.status.status_code == StatusCode.UNSET:
                span.set_attribute(SpanAttributes.HTTP_STATUS_CODE, he.status_code)
                span.set_status(Status(StatusCode.ERROR, description=f"HTTPException: {he.detail}"))
            span.record_exception(he)
            logger.warning(f"HTTPException during {endpoint_name} search.", 
                           extra=dict(log_extra, status_code=he.status_code, detail=he.detail))
            raise
        except Exception as e:
            query_str = query_params.get("query") or query_params.get("prefix") or "N/A"
            error_msg_template = f"Unhandled error in {endpoint_name} search."
            logger.error(error_msg_template, extra=dict(log_extra, error=str(e)), exc_info=True)
            span.set_attribute(SpanAttributes.HTTP_STATUS_CODE, 500)
            span.set_status(Status(StatusCode.ERROR, description=f"{error_msg_template} Details: {str(e)}"))
            span.record_exception(e)
            raise HTTPException(status_code=500, detail=f"An error occurred during your {endpoint_name} search.")

@router.get("/basic", summary="Basic search using all_text field")
async def basic_search(
    query: str = Query(..., description="Search query"),
    es_service: ElasticsearchService = Depends(get_elasticsearch_service)
) -> Dict[str, Any]:
    return await _handle_search_request(
        span_name="endpoint.search.basic",
        http_route="/basic",
        search_callable=lambda: es_service.basic_search(query),
        query_params={"query": query},
        endpoint_name="basic"
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
        query_params={"query": query},
        endpoint_name="weighted"
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
        query_params={"prefix": prefix},
        endpoint_name="autocomplete"
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
        query_params={"query": query},
        endpoint_name="fuzzy"
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
    query_params_for_log_and_span = {"query": query}

    if brand: filters["brand"] = brand; query_params_for_log_and_span["filter_brand"] = brand
    if category: filters["category"] = category; query_params_for_log_and_span["filter_category"] = category
    
    price_filter = {}
    if min_price is not None: price_filter["gte"] = min_price; query_params_for_log_and_span["filter_min_price"] = min_price
    if max_price is not None: price_filter["lte"] = max_price; query_params_for_log_and_span["filter_max_price"] = max_price
    if price_filter: filters["price"] = price_filter # Assuming your service expects price filter like this

    attributes_filter = {}
    if processor: attributes_filter["processor"] = processor; query_params_for_log_and_span["filter_processor"] = processor
    if ram: attributes_filter["ram"] = ram; query_params_for_log_and_span["filter_ram"] = ram
    if storage: attributes_filter["storage"] = storage; query_params_for_log_and_span["filter_storage"] = storage
    if screen_size: attributes_filter["screen_size"] = screen_size; query_params_for_log_and_span["filter_screen_size"] = screen_size
    if resolution: attributes_filter["resolution"] = resolution; query_params_for_log_and_span["filter_resolution"] = resolution
    if material: attributes_filter["material"] = material; query_params_for_log_and_span["filter_material"] = material
    if size: attributes_filter["size"] = size; query_params_for_log_and_span["filter_size"] = size
    if fit: attributes_filter["fit"] = fit; query_params_for_log_and_span["filter_fit"] = fit
    if pattern: attributes_filter["pattern"] = pattern; query_params_for_log_and_span["filter_pattern"] = pattern
    if attributes_filter: filters["attributes"] = attributes_filter
            
    return await _handle_search_request(
        span_name="endpoint.search.advanced",
        http_route="/advanced",
        search_callable=lambda: es_service.advanced_search(query, filters=filters),
        query_params=query_params_for_log_and_span,
        endpoint_name="advanced"
    )