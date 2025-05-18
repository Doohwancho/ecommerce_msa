from fastapi import APIRouter, Depends, HTTPException, Query, Body
from typing import Dict, Any, Optional, List
from elasticsearch import AsyncElasticsearch
from app.services.elasticsearch_service import ElasticsearchService
from app.config.elasticsearch import elasticsearch_config
from datetime import datetime, timezone
from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode

router = APIRouter()
tracer = trace.get_tracer(__name__)

async def get_elasticsearch_service() -> ElasticsearchService:
    """Get ElasticsearchService instance with configured client"""
    es_client = await elasticsearch_config.get_client()
    return ElasticsearchService(es_client)

# Admin endpoints for index management
@router.post("/admin/create-index")
async def create_index(
    es_service: ElasticsearchService = Depends(get_elasticsearch_service)
) -> Dict[str, Any]:
    """Create a new optimized product index"""
    with tracer.start_as_current_span("create_search_index") as span:
        try:
            success = await es_service.create_product_index()
            if not success:
                span.set_status(Status(StatusCode.ERROR, "Failed to create index"))
                raise HTTPException(status_code=500, detail="Failed to create index")
            span.set_status(Status(StatusCode.OK))
            return {"message": "Index created successfully"}
        except Exception as e:
            span.set_status(Status(StatusCode.ERROR, str(e)))
            raise

@router.post("/admin/reindex")
async def reindex(
    es_service: ElasticsearchService = Depends(get_elasticsearch_service)
) -> Dict[str, Any]:
    """Perform full reindexing of all products"""
    with tracer.start_as_current_span("reindex_all_products") as span:
        try:
            result = await es_service.reindex_products()
            if "error" in result:
                span.set_status(Status(StatusCode.ERROR, result["error"]))
                raise HTTPException(status_code=500, detail=result["error"])
            span.set_status(Status(StatusCode.OK))
            return result
        except Exception as e:
            span.set_status(Status(StatusCode.ERROR, str(e)))
            raise

@router.post("/admin/incremental-reindex")
async def incremental_reindex(
    es_service: ElasticsearchService = Depends(get_elasticsearch_service)
) -> Dict[str, Any]:
    """Perform incremental reindexing of changed products since last reindex"""
    with tracer.start_as_current_span("incremental_reindex") as span:
        try:
            result = await es_service.incremental_reindex()
            if "error" in result:
                span.set_status(Status(StatusCode.ERROR, result["error"]))
                raise HTTPException(status_code=500, detail=result["error"])
            span.set_status(Status(StatusCode.OK))
            return result
        except Exception as e:
            span.set_status(Status(StatusCode.ERROR, str(e)))
            raise

@router.post("/admin/reindex-specific")
async def reindex_specific_products(
    product_ids: List[str] = Body(..., description="List of product IDs to reindex"),
    es_service: ElasticsearchService = Depends(get_elasticsearch_service)
) -> Dict[str, Any]:
    """Reindex specific products immediately"""
    with tracer.start_as_current_span("reindex_specific_products") as span:
        try:
            span.set_attribute("product_ids.count", len(product_ids))
            result = await es_service.reindex_specific_products(product_ids)
            if "error" in result:
                span.set_status(Status(StatusCode.ERROR, result["error"]))
                raise HTTPException(status_code=500, detail=result["error"])
            span.set_status(Status(StatusCode.OK))
            return result
        except Exception as e:
            span.set_status(Status(StatusCode.ERROR, str(e)))
            raise

@router.get("/admin/reindex-status")
async def get_reindex_status(
    es_service: ElasticsearchService = Depends(get_elasticsearch_service)
) -> Dict[str, Any]:
    """Get the status of the last reindexing operation"""
    with tracer.start_as_current_span("get_reindex_status") as span:
        try:
            last_reindex_time = await es_service.get_last_reindex_time()
            current_time = datetime.now(timezone.utc)
            last_reindex_datetime = datetime.fromisoformat(last_reindex_time)
            
            # Ensure last_reindex_datetime is timezone-aware
            if last_reindex_datetime.tzinfo is None:
                last_reindex_datetime = last_reindex_datetime.replace(tzinfo=timezone.utc)
            
            time_since_last_reindex = current_time - last_reindex_datetime
            span.set_attribute("time_since_last_reindex", str(time_since_last_reindex))
            
            span.set_status(Status(StatusCode.OK))
            return {
                "last_reindex_time": last_reindex_time,
                "current_time": current_time.isoformat(),
                "time_since_last_reindex": str(time_since_last_reindex)
            }
        except Exception as e:
            span.set_status(Status(StatusCode.ERROR, str(e)))
            raise HTTPException(status_code=500, detail=str(e))

@router.get("/admin/debug-dates")
async def debug_dates(
    es_service: ElasticsearchService = Depends(get_elasticsearch_service)
):
    """날짜 형식 디버깅"""
    with tracer.start_as_current_span("debug_dates") as span:
        try:
            result = await es_service.debug_date_formats()
            span.set_status(Status(StatusCode.OK))
            return result
        except Exception as e:
            span.set_status(Status(StatusCode.ERROR, str(e)))
            raise

# Search endpoints
@router.get("/basic")
async def basic_search(
    query: str = Query(..., description="Search query"),
    es_service: ElasticsearchService = Depends(get_elasticsearch_service)
) -> Dict[str, Any]:
    """Basic search using all_text field"""
    with tracer.start_as_current_span("basic_search") as span:
        try:
            span.set_attribute("search.query", query)
            result = await es_service.basic_search(query)
            span.set_attribute("search.results_count", len(result.get("hits", [])))
            span.set_status(Status(StatusCode.OK))
            return result
        except Exception as e:
            span.set_status(Status(StatusCode.ERROR, str(e)))
            raise

@router.get("/weighted")
async def weighted_search(
    query: str = Query(..., description="Search query"),
    es_service: ElasticsearchService = Depends(get_elasticsearch_service)
) -> Dict[str, Any]:
    """Search with field-specific weights"""
    with tracer.start_as_current_span("weighted_search") as span:
        try:
            span.set_attribute("search.query", query)
            result = await es_service.weighted_search(query)
            span.set_attribute("search.results_count", len(result.get("hits", [])))
            span.set_status(Status(StatusCode.OK))
            return result
        except Exception as e:
            span.set_status(Status(StatusCode.ERROR, str(e)))
            raise

@router.get("/autocomplete")
async def autocomplete_search(
    prefix: str = Query(..., description="Search prefix for autocomplete"),
    es_service: ElasticsearchService = Depends(get_elasticsearch_service)
) -> Dict[str, Any]:
    """Autocomplete search"""
    with tracer.start_as_current_span("autocomplete_search") as span:
        try:
            span.set_attribute("search.prefix", prefix)
            result = await es_service.autocomplete_search(prefix)
            span.set_attribute("search.results_count", len(result.get("hits", [])))
            span.set_status(Status(StatusCode.OK))
            return result
        except Exception as e:
            span.set_status(Status(StatusCode.ERROR, str(e)))
            raise

@router.get("/fuzzy")
async def fuzzy_search(
    query: str = Query(..., description="Search query with typo tolerance"),
    es_service: ElasticsearchService = Depends(get_elasticsearch_service)
) -> Dict[str, Any]:
    """Fuzzy search with typo tolerance"""
    with tracer.start_as_current_span("fuzzy_search") as span:
        try:
            span.set_attribute("search.query", query)
            result = await es_service.fuzzy_search(query)
            span.set_attribute("search.results_count", len(result.get("hits", [])))
            span.set_status(Status(StatusCode.OK))
            return result
        except Exception as e:
            span.set_status(Status(StatusCode.ERROR, str(e)))
            raise

@router.get("/advanced")
async def advanced_search(
    query: str = Query(..., description="Search query"),
    brand: Optional[str] = Query(None, description="Filter by brand"),
    category: Optional[str] = Query(None, description="Filter by category"),
    min_price: Optional[float] = Query(None, description="Minimum price"),
    max_price: Optional[float] = Query(None, description="Maximum price"),
    processor: Optional[str] = Query(None, description="Filter by processor"),
    ram: Optional[str] = Query(None, description="Filter by RAM"),
    storage: Optional[str] = Query(None, description="Filter by storage"),
    screen_size: Optional[str] = Query(None, description="Filter by screen size"),
    resolution: Optional[str] = Query(None, description="Filter by resolution"),
    material: Optional[str] = Query(None, description="Filter by material"),
    size: Optional[str] = Query(None, description="Filter by size"),
    fit: Optional[str] = Query(None, description="Filter by fit"),
    pattern: Optional[str] = Query(None, description="Filter by pattern"),
    es_service: ElasticsearchService = Depends(get_elasticsearch_service)
) -> Dict[str, Any]:
    """Advanced search with filters and aggregations"""
    with tracer.start_as_current_span("advanced_search") as span:
        try:
            # Set basic search attributes
            span.set_attribute("search.query", query)
            
            # Set filter attributes if they exist
            if brand:
                span.set_attribute("search.filter.brand", brand)
            if category:
                span.set_attribute("search.filter.category", category)
            if min_price is not None:
                span.set_attribute("search.filter.min_price", min_price)
            if max_price is not None:
                span.set_attribute("search.filter.max_price", max_price)
            
            # Build attributes filter
            attributes = {}
            if processor:
                attributes["processor"] = processor
                span.set_attribute("search.filter.processor", processor)
            if ram:
                attributes["ram"] = ram
                span.set_attribute("search.filter.ram", ram)
            if storage:
                attributes["storage"] = storage
                span.set_attribute("search.filter.storage", storage)
            if screen_size:
                attributes["screen_size"] = screen_size
                span.set_attribute("search.filter.screen_size", screen_size)
            if resolution:
                attributes["resolution"] = resolution
                span.set_attribute("search.filter.resolution", resolution)
            if material:
                attributes["material"] = material
                span.set_attribute("search.filter.material", material)
            if size:
                attributes["size"] = size
                span.set_attribute("search.filter.size", size)
            if fit:
                attributes["fit"] = fit
                span.set_attribute("search.filter.fit", fit)
            if pattern:
                attributes["pattern"] = pattern
                span.set_attribute("search.filter.pattern", pattern)
            
            filters = {}
            if brand:
                filters["brand"] = brand
            if category:
                filters["category"] = category
            if min_price is not None or max_price is not None:
                filters["minPrice"] = min_price
                filters["maxPrice"] = max_price
            
            if attributes:
                filters["attributes"] = attributes
            
            result = await es_service.advanced_search(query, filters)
            span.set_attribute("search.results_count", len(result.get("hits", [])))
            span.set_status(Status(StatusCode.OK))
            return result
        except Exception as e:
            span.set_status(Status(StatusCode.ERROR, str(e)))
            raise 