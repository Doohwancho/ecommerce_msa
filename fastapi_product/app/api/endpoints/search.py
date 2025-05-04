from fastapi import APIRouter, Depends, HTTPException, Query, Body
from typing import Dict, Any, Optional, List
from elasticsearch import AsyncElasticsearch
from app.services.elasticsearch_service import ElasticsearchService
from app.config.elasticsearch import elasticsearch_config
from datetime import datetime, timezone

router = APIRouter()

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
    success = await es_service.create_product_index()
    if not success:
        raise HTTPException(status_code=500, detail="Failed to create index")
    return {"message": "Index created successfully"}

@router.post("/admin/reindex")
async def reindex(
    es_service: ElasticsearchService = Depends(get_elasticsearch_service)
) -> Dict[str, Any]:
    """Perform full reindexing of all products"""
    result = await es_service.reindex_products()
    if "error" in result:
        raise HTTPException(status_code=500, detail=result["error"])
    return result

@router.post("/admin/incremental-reindex")
async def incremental_reindex(
    es_service: ElasticsearchService = Depends(get_elasticsearch_service)
) -> Dict[str, Any]:
    """Perform incremental reindexing of changed products since last reindex"""
    result = await es_service.incremental_reindex()
    if "error" in result:
        raise HTTPException(status_code=500, detail=result["error"])
    return result

@router.post("/admin/reindex-specific")
async def reindex_specific_products(
    product_ids: List[str] = Body(..., description="List of product IDs to reindex"),
    es_service: ElasticsearchService = Depends(get_elasticsearch_service)
) -> Dict[str, Any]:
    """Reindex specific products immediately"""
    result = await es_service.reindex_specific_products(product_ids)
    if "error" in result:
        raise HTTPException(status_code=500, detail=result["error"])
    return result

@router.get("/admin/reindex-status")
async def get_reindex_status(
    es_service: ElasticsearchService = Depends(get_elasticsearch_service)
) -> Dict[str, Any]:
    """Get the status of the last reindexing operation"""
    try:
        last_reindex_time = await es_service.get_last_reindex_time()
        current_time = datetime.now(timezone.utc)
        last_reindex_datetime = datetime.fromisoformat(last_reindex_time)
        
        # Ensure last_reindex_datetime is timezone-aware
        if last_reindex_datetime.tzinfo is None:
            last_reindex_datetime = last_reindex_datetime.replace(tzinfo=timezone.utc)
            
        return {
            "last_reindex_time": last_reindex_time,
            "current_time": current_time.isoformat(),
            "time_since_last_reindex": str(current_time - last_reindex_datetime)
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/admin/debug-dates")
async def debug_dates(
    es_service: ElasticsearchService = Depends(get_elasticsearch_service)
):
    """날짜 형식 디버깅"""
    return await es_service.debug_date_formats()

# Search endpoints
@router.get("/basic")
async def basic_search(
    query: str = Query(..., description="Search query"),
    es_service: ElasticsearchService = Depends(get_elasticsearch_service)
) -> Dict[str, Any]:
    """Basic search using all_text field"""
    return await es_service.basic_search(query)

@router.get("/weighted")
async def weighted_search(
    query: str = Query(..., description="Search query"),
    es_service: ElasticsearchService = Depends(get_elasticsearch_service)
) -> Dict[str, Any]:
    """Search with field-specific weights"""
    return await es_service.weighted_search(query)

@router.get("/autocomplete")
async def autocomplete_search(
    prefix: str = Query(..., description="Search prefix for autocomplete"),
    es_service: ElasticsearchService = Depends(get_elasticsearch_service)
) -> Dict[str, Any]:
    """Autocomplete search"""
    return await es_service.autocomplete_search(prefix)

@router.get("/fuzzy")
async def fuzzy_search(
    query: str = Query(..., description="Search query with typo tolerance"),
    es_service: ElasticsearchService = Depends(get_elasticsearch_service)
) -> Dict[str, Any]:
    """Fuzzy search with typo tolerance"""
    return await es_service.fuzzy_search(query)

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
    filters = {}
    
    if brand:
        filters["brand"] = brand
    if category:
        filters["category"] = category
    if min_price is not None or max_price is not None:
        filters["minPrice"] = min_price
        filters["maxPrice"] = max_price
    
    # Build attributes filter
    attributes = {}
    if processor:
        attributes["processor"] = processor
    if ram:
        attributes["ram"] = ram
    if storage:
        attributes["storage"] = storage
    if screen_size:
        attributes["screen_size"] = screen_size
    if resolution:
        attributes["resolution"] = resolution
    if material:
        attributes["material"] = material
    if size:
        attributes["size"] = size
    if fit:
        attributes["fit"] = fit
    if pattern:
        attributes["pattern"] = pattern
    
    if attributes:
        filters["attributes"] = attributes
    
    return await es_service.advanced_search(query, filters) 