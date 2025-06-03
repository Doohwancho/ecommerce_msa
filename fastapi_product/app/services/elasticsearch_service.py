from elasticsearch import AsyncElasticsearch, exceptions as es_exceptions # Import specific ES exceptions
from typing import Dict, List, Optional, Any
import logging # Keep standard logging
from datetime import datetime, timedelta, timezone
import traceback # For detailed traceback logging

# OTel imports
from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode
from opentelemetry.semconv.trace import SpanAttributes # For semantic conventions

# Use the logger from the logging configuration
logger = logging.getLogger(__name__)

class ElasticsearchService:
    def __init__(self, es_client: AsyncElasticsearch):
        self.client = es_client
        self.source_index = "my_db.products"
        self.index_name = "products_optimized"
        self.search_alias = "products_search"
        self.reindex_metadata_index = ".reindex_metadata"
        # Initialize tracer for this service
        self.tracer = trace.get_tracer("app.services.ElasticsearchService", "0.1.0")

    async def setup_alias(self) -> bool:
        """Set up the search alias for the index with OTel tracing."""
        with self.tracer.start_as_current_span("service.elasticsearch.setup_alias") as span:
            span.set_attribute(SpanAttributes.DB_SYSTEM, "elasticsearch")
            span.set_attribute("elasticsearch.alias_name", self.search_alias)
            span.set_attribute("elasticsearch.target_index", self.index_name)
            try:
                # ElasticsearchInstrumentor will trace these client calls
                if await self.client.indices.exists_alias(name=self.search_alias, index=self.index_name): # Check against specific index too
                    logger.info("Alias already exists for index. Attempting to update/repoint if necessary.", extra={
                        "alias_name": self.search_alias,
                        "target_index": self.index_name
                    })
                    try: # Try to delete from any index it might be on.
                        await self.client.indices.delete_alias(index="_all", name=self.search_alias, ignore_unavailable=True)
                        span.add_event("Removed existing alias from all indices", {"alias_name": self.search_alias})
                    except es_exceptions.NotFoundError:
                        span.add_event("Alias did not exist on _all, or specific index, proceeding to add.", {"alias_name": self.search_alias})


                await self.client.indices.put_alias(index=self.index_name, name=self.search_alias)
                logger.info("Alias successfully pointed to index.", extra={
                    "alias_name": self.search_alias,
                    "target_index": self.index_name
                })
                span.set_status(Status(StatusCode.OK))
                return True
            except Exception as e:
                error_msg = f"Error setting up alias '{self.search_alias}' for index '{self.index_name}'"
                logger.error(error_msg, extra={"alias_name": self.search_alias, "target_index": self.index_name, "error": str(e)}, exc_info=True)
                span.record_exception(e)
                span.set_status(Status(StatusCode.ERROR, description=str(e))) # Use str(e) for description
                return False

    async def create_product_index(self) -> bool:
        """Create a new optimized product index with custom mappings and settings, with OTel tracing."""
        with self.tracer.start_as_current_span("service.elasticsearch.create_product_index") as span:
            span.set_attribute(SpanAttributes.DB_SYSTEM, "elasticsearch")
            span.set_attribute(SpanAttributes.DB_OPERATION, "create_index")
            span.set_attribute("elasticsearch.index_name", self.index_name)
            try:
                # ElasticsearchInstrumentor traces these client calls
                if await self.client.indices.exists(index=self.index_name):
                    logger.info("Index already exists. Deleting it first.", extra={"index_name": self.index_name})
                    span.add_event("Index_exists_deleting", {"index_name": self.index_name})
                    await self.client.indices.delete(index=self.index_name)
                    span.add_event("Index_deleted", {"index_name": self.index_name})

                span.set_attribute("elasticsearch.index.settings.number_of_shards", 3) 
                
                index_body = {
                    "settings": {
                        "number_of_shards": 3,"number_of_replicas": 1,
                        "analysis": {
                            "tokenizer": {
                                "ngram_tokenizer": {"type": "ngram","min_gram": 2,"max_gram": 3,"token_chars": ["letter", "digit"]},
                                "autocomplete_tokenizer": {"type": "edge_ngram","min_gram": 1,"max_gram": 10,"token_chars": ["letter", "digit"]},
                                "nori_user_dict": {"type": "nori_tokenizer", "decompound_mode": "mixed", "user_dictionary_rules": ["운동화","축구화"]}
                            },
                            "filter": {
                                "korean_synonym_filter": {"type": "synonym","lenient": True,"synonyms": ["노트북, 랩탑 => 노트북","휴대폰, 핸드폰, 스마트폰 => 스마트폰","컴퓨터, PC, 피씨, 데스크탑 => 컴퓨터","TV, 텔레비전, 티비 => TV"],"ignore_case": True}
                            },
                            "analyzer": {
                                "korean_analyzer": {"type": "custom","tokenizer": "nori_user_dict","filter": ["nori_readingform","lowercase","korean_synonym_filter"]},
                                "ngram_analyzer": {"tokenizer": "ngram_tokenizer","filter": ["lowercase"]},
                                "autocomplete_analyzer": {"tokenizer": "autocomplete_tokenizer","filter": ["lowercase"]}
                            }
                        }
                    },
                    "mappings": { 
                        "properties": {
                            "title": {"type": "text","analyzer": "korean_analyzer","fields": {"ngram": {"type": "text","analyzer": "ngram_analyzer"},"autocomplete": {"type": "text","analyzer": "autocomplete_analyzer"},"keyword": {"type": "keyword"}}},
                            "description": {"type": "text","analyzer": "korean_analyzer","fields": {"ngram": {"type": "text","analyzer": "ngram_analyzer"}}},
                            "brand": {"type": "text","analyzer": "korean_analyzer","fields": {"autocomplete": {"type": "text","analyzer": "autocomplete_analyzer"},"keyword": {"type": "keyword"}}},
                            "category_breadcrumbs": {"type": "text","analyzer": "korean_analyzer","fields": {"keyword": {"type": "keyword"}}},
                            "category_ids": {"type": "keyword"},"category_path": {"type": "keyword"},"primary_category_id": {"type": "integer"},"category_level": {"type": "integer"},
                            "model": {"type": "keyword"},"sku": {"type": "keyword"},"upc": {"type": "keyword"},
                            "color": {"type": "text","fields": {"keyword": {"type": "keyword"}}},
                            "price": {"properties": {"amount": {"type": "float"},"currency": {"type": "keyword"}}},
                            "stock": {"type": "integer"},"stock_reserved": {"type": "integer"},
                            "weight": {"properties": {"value": {"type": "float"},"unit": {"type": "keyword"}}},
                            "dimensions": {"properties": {"length": {"type": "float"},"width": {"type": "float"},"height": {"type": "float"},"unit": {"type": "keyword"}}},
                            "attributes": {"properties": {"processor": {"type": "keyword"},"ram": {"type": "keyword"},"storage": {"type": "keyword"},"screen_size": {"type": "keyword"},"resolution": {"type": "keyword"},"material": {"type": "keyword"},"size": {"type": "keyword"},"fit": {"type": "keyword"},"pattern": {"type": "keyword"}}},
                            "variants": {"type": "nested","properties": {"id": {"type": "keyword"},"sku": {"type": "keyword"},"color": {"type": "text","fields": {"keyword": {"type": "keyword"}}},"price": {"properties": {"amount": {"type": "float"},"currency": {"type": "keyword"}}},"inventory": {"type": "integer"}}},
                            "images": {"type": "nested","properties": {"url": {"type": "keyword", "index": False},"main": {"type": "boolean"}}},
                            "created_at": {"type": "date"},"updated_at": {"type": "date"},
                            "all_text": {"type": "text","analyzer": "korean_analyzer","fields": {"ngram": {"type": "text","analyzer": "ngram_analyzer"}}}
                        }
                    }
                }
                await self.client.indices.create(index=self.index_name, body=index_body)
                span.add_event("Index_created_successfully", {"index_name": self.index_name})

                alias_success = await self.setup_alias()
                if not alias_success:
                    logger.warning("Index created, but failed to set up search alias.", extra={
                        "index_name": self.index_name,
                        "alias_name": self.search_alias
                    })
                    span.set_status(Status(StatusCode.ERROR, "Index created, but alias setup failed"))
                    return False

                logger.info("Index created and alias set up successfully.", extra={
                    "index_name": self.index_name,
                    "alias_name": self.search_alias
                })
                span.set_status(Status(StatusCode.OK))
                return True
            except Exception as e:
                error_msg = f"Error creating index '{self.index_name}'"
                logger.error(error_msg, extra={"index_name": self.index_name, "error": str(e)}, exc_info=True)
                logger.error(f"Full error details: {repr(e)}") # Keep for detailed debugging if needed
                logger.error(f"Traceback: {traceback.format_exc()}") # Keep for detailed debugging
                span.record_exception(e)
                span.set_status(Status(StatusCode.ERROR, description=str(e)))
                return False

    async def reindex_products(self, script_override: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Reindex products from source to optimized index, with OTel tracing."""
        with self.tracer.start_as_current_span("service.elasticsearch.reindex_products") as span:
            span.set_attribute(SpanAttributes.DB_SYSTEM, "elasticsearch")
            span.set_attribute(SpanAttributes.DB_OPERATION, "reindex")
            span.set_attribute("elasticsearch.source_index", self.source_index)
            span.set_attribute("elasticsearch.dest_index", self.index_name)

            try:
                if not await self.client.indices.exists(index=self.source_index):
                    error_msg = f"Source index '{self.source_index}' does not exist."
                    logger.error(error_msg, extra={"source_index": self.source_index})
                    span.set_status(Status(StatusCode.ERROR, error_msg))
                    return {"error": error_msg, "details": "Please create and populate the source index first."}
                if not await self.client.indices.exists(index=self.index_name):
                    error_msg = f"Target index '{self.index_name}' does not exist."
                    logger.error(error_msg, extra={"target_index": self.index_name})
                    span.set_status(Status(StatusCode.ERROR, error_msg))
                    return {"error": error_msg, "details": "Please create the target index first using /admin/create-index."}

                reindex_body_script = script_override if script_override else {
                    "source": """
                        StringBuilder sb = new StringBuilder();
                        if (ctx._source.title != null) sb.append(ctx._source.title + " ");
                        if (ctx._source.description != null) sb.append(ctx._source.description + " ");
                        if (ctx._source.brand != null) sb.append(ctx._source.brand + " ");
                        // ... (rest of your script) ...
                        if (ctx._source.color != null) sb.append(ctx._source.color + " ");
                        if (ctx._source.category_breadcrumbs != null) { for (def cat : ctx._source.category_breadcrumbs) { sb.append(cat + " "); } }
                        if (ctx._source.attributes != null) { for (def attr : ctx._source.attributes.entrySet()) { sb.append(attr.getValue() + " "); } }
                        if (ctx._source.variants != null) { for (def variant : ctx._source.variants) { if (variant.color != null) sb.append(variant.color + " "); if (variant.attributes != null) { for (def attr : variant.attributes.entrySet()) { sb.append(attr.getValue() + " "); } } } }
                        ctx._source.all_text = sb.toString();
                    """
                }
                
                response = await self.client.reindex(
                    refresh=True,
                    body={
                        "source": {"index": self.source_index, "_source": [
                            "title", "description", "brand", "model", "sku", "upc", "color",
                            "category_*", "price", "stock", "stock_reserved", "weight", "dimensions",
                            "attributes", "variants", "images", "created_at", "updated_at"
                        ]},
                        "dest": {"index": self.index_name},
                        "script": reindex_body_script
                    }
                )
                span.set_attribute("elasticsearch.reindex.total", response.get("total"))
                span.set_attribute("elasticsearch.reindex.created", response.get("created"))
                span.set_attribute("elasticsearch.reindex.updated", response.get("updated"))
                span.set_attribute("elasticsearch.reindex.deleted", response.get("deleted"))
                span.set_attribute("elasticsearch.reindex.took_ms", response.get("took"))
                
                if response.get("failures"):
                    failures_count = len(response['failures'])
                    failures_summary = f"Reindexing completed with {failures_count} failures."
                    logger.error(failures_summary, extra={
                        "failures_count": failures_count,
                        "failures_preview": response['failures'][:3]
                    })
                    span.set_attribute("elasticsearch.reindex.failures_count", failures_count)
                    span.set_status(Status(StatusCode.ERROR, description=failures_summary))
                    return {"error": failures_summary, "failures": response["failures"], "reindex_stats": response}

                try:
                    current_time_iso = datetime.now(timezone.utc).isoformat()
                    await self.update_last_reindex_time(current_time_iso)
                    logger.info("Full reindex completed. Updated reindex metadata.", extra={
                        "index_name": self.index_name,
                        "last_reindex_time": current_time_iso
                    })
                    span.set_attribute("app.reindex.metadata_updated_time", current_time_iso)
                except Exception as meta_e:
                    meta_error_msg = f"Reindexing successful, but failed to update metadata: {meta_e}"
                    logger.error(meta_error_msg, extra={"error": str(meta_e)}, exc_info=True)
                    span.add_event("metadata_update_failed_after_reindex", {"error": str(meta_e)})
                    return {
                        "warning": meta_error_msg, "reindex_stats": response,
                        "last_reindex_time_update_attempted": datetime.now(timezone.utc).isoformat()
                    }

                span.set_status(Status(StatusCode.OK))
                return {"message": "Full reindex completed successfully.", "reindex_stats": response, "last_reindex_time": current_time_iso}
            except Exception as e:
                error_msg = f"Error during full reindex: {e}"
                logger.error(error_msg, extra={"error": str(e)}, exc_info=True)
                span.record_exception(e)
                span.set_status(Status(StatusCode.ERROR, description=str(e)))
                return {"error": error_msg}

    async def ensure_metadata_index(self) -> bool:
        with self.tracer.start_as_current_span("service.elasticsearch.ensure_metadata_index") as span:
            span.set_attribute(SpanAttributes.DB_SYSTEM, "elasticsearch")
            span.set_attribute("elasticsearch.index_name", self.reindex_metadata_index)
            try:
                exists = await self.client.indices.exists(index=self.reindex_metadata_index)
                if not exists:
                    logger.info("Creating metadata index", extra={"index_name": self.reindex_metadata_index})
                    await self.client.indices.create(
                        index=self.reindex_metadata_index,
                        body={"mappings": {"properties": {
                            "index_name": {"type": "keyword"},
                            "last_reindex_time": {"type": "date"},
                            "reindex_count": {"type": "integer"}
                        }}}
                    )
                    current_time = datetime.now(timezone.utc).isoformat()
                    await self.client.index(
                        index=self.reindex_metadata_index, id=self.index_name,
                        body={"index_name": self.index_name, "last_reindex_time": current_time, "reindex_count": 0},
                        refresh=True
                    )
                    logger.info("Metadata index created with initial doc.", extra={
                        "metadata_index": self.reindex_metadata_index,
                        "target_index": self.index_name
                    })
                    span.add_event("metadata_index_created")
                else:
                    logger.info("Metadata index already exists.", extra={"index_name": self.reindex_metadata_index})
                    span.add_event("metadata_index_exists")
                span.set_status(Status(StatusCode.OK))
                return True
            except Exception as e:
                error_msg = f"Error ensuring metadata index '{self.reindex_metadata_index}'"
                logger.error(error_msg, extra={"index_name": self.reindex_metadata_index, "error": str(e)}, exc_info=True)
                span.record_exception(e)
                span.set_status(Status(StatusCode.ERROR, description=str(e)))
                raise 

    async def get_last_reindex_time(self) -> str:
        with self.tracer.start_as_current_span("service.elasticsearch.get_last_reindex_time") as span:
            span.set_attribute(SpanAttributes.DB_SYSTEM, "elasticsearch")
            span.set_attribute("elasticsearch.metadata_index", self.reindex_metadata_index)
            span.set_attribute("elasticsearch.target_index_metadata", self.index_name)
            try:
                await self.ensure_metadata_index()
                
                result = await self.client.get(index=self.reindex_metadata_index, id=self.index_name)
                last_time = result["_source"]["last_reindex_time"]
                span.set_attribute("app.reindex.last_recorded_time", last_time)
                span.set_status(Status(StatusCode.OK))
                return last_time
            except es_exceptions.NotFoundError:
                logger.warning("Metadata document not found. Initializing.", extra={
                    "target_index": self.index_name,
                    "metadata_index": self.reindex_metadata_index
                })
                span.add_event("metadata_document_not_found_initializing")
                current_time = datetime.now(timezone.utc).isoformat()
                await self.update_last_reindex_time(current_time, initial_setup=True) 
                span.set_attribute("app.reindex.last_recorded_time", current_time) 
                span.set_status(Status(StatusCode.OK)) 
                return current_time
            except Exception as e:
                error_msg = f"Error getting last reindex time for '{self.index_name}'"
                logger.error(error_msg, extra={"target_index": self.index_name, "error": str(e)}, exc_info=True)
                span.record_exception(e)
                span.set_status(Status(StatusCode.ERROR, description=str(e)))
                return datetime.now(timezone.utc).isoformat()


    async def update_last_reindex_time(self, timestamp: Optional[str] = None, initial_setup: bool = False) -> bool:
        with self.tracer.start_as_current_span("service.elasticsearch.update_last_reindex_time") as span:
            final_timestamp = timestamp if timestamp else datetime.now(timezone.utc).isoformat()
            span.set_attribute(SpanAttributes.DB_SYSTEM, "elasticsearch")
            span.set_attribute("elasticsearch.metadata_index", self.reindex_metadata_index)
            span.set_attribute("elasticsearch.target_index_metadata", self.index_name)
            span.set_attribute("app.reindex.update_time_to", final_timestamp)
            try:
                await self.ensure_metadata_index()

                body_doc = {"doc": {"last_reindex_time": final_timestamp}, "doc_as_upsert": False}
                script_increment = {"source": "if (ctx._source.containsKey('reindex_count')) { ctx._source.reindex_count += 1 } else { ctx._source.reindex_count = 1 }", "lang": "painless"}
                
                if initial_setup or not await self.client.exists(index=self.reindex_metadata_index, id=self.index_name):
                    logger.info("Metadata document not found or initial setup. Creating new.", extra={
                        "target_index": self.index_name,
                        "initial_setup": initial_setup
                    })
                    span.add_event("creating_new_metadata_document")
                    await self.client.index(
                        index=self.reindex_metadata_index, id=self.index_name,
                        body={"index_name": self.index_name, "last_reindex_time": final_timestamp, "reindex_count": 1 if not initial_setup else 0},
                        refresh=True
                    )
                else:
                    span.add_event("updating_existing_metadata_document")
                    await self.client.update(index=self.reindex_metadata_index, id=self.index_name, body=body_doc, refresh="wait_for")
                    if not initial_setup :
                        await self.client.update(index=self.reindex_metadata_index, id=self.index_name, body={"script": script_increment}, refresh="wait_for")

                logger.info("Updated last reindex time.", extra={
                    "target_index": self.index_name,
                    "updated_time": final_timestamp
                })
                span.set_status(Status(StatusCode.OK))
                return True
            except Exception as e:
                error_msg = f"Error updating last reindex time for '{self.index_name}'"
                logger.error(error_msg, extra={"target_index": self.index_name, "error": str(e)}, exc_info=True)
                span.record_exception(e)
                span.set_status(Status(StatusCode.ERROR, description=str(e)))
                raise

    async def incremental_reindex(self) -> Dict[str, Any]:
        """Incremental reindex with OTel tracing. Many debug logs from user code are kept."""
        with self.tracer.start_as_current_span("service.elasticsearch.incremental_reindex") as span:
            span.set_attribute(SpanAttributes.DB_SYSTEM, "elasticsearch")
            span.set_attribute(SpanAttributes.DB_OPERATION, "reindex_incremental")
            span.set_attribute("elasticsearch.source_index", self.source_index)
            span.set_attribute("elasticsearch.dest_index", self.index_name)
            try:
                if not await self.client.indices.exists(index=self.source_index):
                    error_msg = f"Source index '{self.source_index}' does not exist."
                    logger.error(error_msg, extra={"source_index": self.source_index})
                    return {"error": error_msg}
                if not await self.client.indices.exists(index=self.index_name):
                    error_msg = f"Target index '{self.index_name}' does not exist."
                    logger.error(error_msg, extra={"target_index": self.index_name})
                    return {"error" : error_msg}

                last_reindex_time_iso = await self.get_last_reindex_time()
                span.set_attribute("app.reindex.previous_reindex_time_used", last_reindex_time_iso)
                logger.info("Incremental reindex: last reindex time retrieved.", extra={"last_reindex_time": last_reindex_time_iso})

                count_response = await self.client.count(index=self.source_index, body={"query": {"range": {"updated_at": {"gt": last_reindex_time_iso}}}})
                docs_to_update = count_response["count"]
                span.set_attribute("elasticsearch.reindex.docs_to_update_count", docs_to_update)
                logger.info(f"Incremental reindex: {docs_to_update} documents to update.", extra={
                    "docs_to_update": docs_to_update,
                    "since_time": last_reindex_time_iso
                })

                if docs_to_update == 0:
                    logger.info("Incremental reindex: No documents to update.", extra={"last_reindex_time_checked": last_reindex_time_iso})
                    span.set_status(Status(StatusCode.OK))
                    return {"message": "No documents to update.", "docs_to_update": 0, "last_reindex_time_checked": last_reindex_time_iso}
                
                reindex_body_script = {
                    "source": """
                        StringBuilder sb = new StringBuilder(); /* ... rest of script ... */
                        if (ctx._source.title != null) sb.append(ctx._source.title + " ");
                        if (ctx._source.description != null) sb.append(ctx._source.description + " ");
                        if (ctx._source.brand != null) sb.append(ctx._source.brand + " ");
                        if (ctx._source.model != null) sb.append(ctx._source.model + " ");
                        if (ctx._source.sku != null) sb.append(ctx._source.sku + " ");
                        if (ctx._source.color != null) sb.append(ctx._source.color + " ");
                        if (ctx._source.category_breadcrumbs != null) { for (def cat : ctx._source.category_breadcrumbs) { sb.append(cat + " "); } }
                        if (ctx._source.attributes != null) { for (def attr : ctx._source.attributes.entrySet()) { sb.append(attr.getValue() + " "); } }
                        if (ctx._source.variants != null) { for (def variant : ctx._source.variants) { if (variant.color != null) sb.append(variant.color + " "); if (variant.attributes != null) { for (def attr : variant.attributes.entrySet()) { sb.append(attr.getValue() + " "); } } } }
                        ctx._source.all_text = sb.toString();
                    """
                }

                response = await self.client.reindex(
                    refresh=True,
                    body={
                        "source": {"index": self.source_index, "query": {"range": {"updated_at": {"gt": last_reindex_time_iso}}},
                                   "_source": [
                                        "title", "description", "brand", "model", "sku", "upc", "color",
                                        "category_*", "price", "stock", "stock_reserved", "weight", "dimensions",
                                        "attributes", "variants", "images", "created_at", "updated_at"
                                    ]},
                        "dest": {"index": self.index_name, "op_type": "index"}, 
                        "script": reindex_body_script
                    }
                )
                span.set_attribute("elasticsearch.reindex.total", response.get("total"))
                span.set_attribute("elasticsearch.reindex.created", response.get("created"))
                span.set_attribute("elasticsearch.reindex.updated", response.get("updated"))
                span.set_attribute("elasticsearch.reindex.deleted", response.get("deleted"))
                span.set_attribute("elasticsearch.reindex.took_ms", response.get("took"))

                if response.get("failures"):
                    failures_count = len(response['failures'])
                    failures_summary = f"Incremental reindex completed with {failures_count} failures."
                    logger.error(failures_summary, extra={
                        "failures_count": failures_count,
                        "failures_preview": response['failures'][:3]
                    })
                    return {"error": failures_summary, "failures": response["failures"]}

                current_time_iso_new = datetime.now(timezone.utc).isoformat()
                await self.update_last_reindex_time(current_time_iso_new)
                span.set_attribute("app.reindex.metadata_updated_time", current_time_iso_new)
                logger.info("Incremental reindex completed. Updated metadata.", extra={
                    "processed_docs": response.get('total'),
                    "new_reindex_time": current_time_iso_new
                })
                span.set_status(Status(StatusCode.OK))
                return {"message": "Incremental reindex completed.", "reindex_stats": response, "new_reindex_time": current_time_iso_new}
            except Exception as e:
                error_msg = f"Error during incremental reindex: {e}"
                logger.error(error_msg, extra={"error": str(e)}, exc_info=True)
                span.record_exception(e)
                span.set_status(Status(StatusCode.ERROR, str(e)))
                return {"error": error_msg}


    async def _perform_search(self, span_name_suffix: str, index_or_alias: str, query_body: Dict, query_params_for_span: Dict) -> Dict[str, Any]:
        """Helper for search operations with OTel tracing"""
        with self.tracer.start_as_current_span(f"service.elasticsearch.search.{span_name_suffix}") as span:
            span.set_attribute(SpanAttributes.DB_SYSTEM, "elasticsearch")
            span.set_attribute(SpanAttributes.DB_OPERATION, "search")
            span.set_attribute("elasticsearch.index_or_alias", index_or_alias)
            for key, value in query_params_for_span.items():
                 if value is not None: 
                    span.set_attribute(f"app.search.request.{key}", str(value))

            try:
                response = await self.client.search(index=index_or_alias, body=query_body)
                
                hits_data = response.get("hits", {})
                actual_hits = hits_data.get("hits", [])
                total_hits = hits_data.get("total", {}).get("value", 0)

                span.set_attribute("elasticsearch.search.hits_returned_count", len(actual_hits))
                span.set_attribute("elasticsearch.search.total_hits", total_hits)
                span.set_attribute("elasticsearch.search.took_ms", response.get("took"))

                if response.get("_shards", {}).get("failed", 0) > 0:
                    shard_failures = response["_shards"].get("failures", [])
                    shard_failures_count = response["_shards"]["failed"]
                    logger.warning("Search completed with shard failures.", extra={
                        "index_or_alias": index_or_alias,
                        "shard_failures_count": shard_failures_count,
                        "failures_preview": str(shard_failures[:3])
                    })
                    span.add_event("search_shard_failures", {"failures_details": str(shard_failures[:3])})
                    span.set_attribute("elasticsearch.search.shard_failures_count", shard_failures_count)

                span.set_status(Status(StatusCode.OK))
                return response
            except Exception as e:
                error_msg = f"Error in search operation '{span_name_suffix}'"
                logger.error(error_msg, extra={"search_type": span_name_suffix, "error": str(e)}, exc_info=True)
                span.record_exception(e)
                span.set_status(Status(StatusCode.ERROR, description=str(e)))
                return {"hits": {"total": {"value": 0}, "hits": []}, "aggregations": {}}


    async def basic_search(self, query: str) -> Dict[str, Any]:
        query_body = {"query": {"match": {"all_text": query}}}
        query_params = {"query_term": query, "search_type": "basic"}
        es_response = await self._perform_search("basic", self.search_alias, query_body, query_params)
        return es_response.get("hits", {"total": {"value": 0}, "hits": []})

    async def weighted_search(self, query: str) -> Dict[str, Any]:
        query_body = {"query": {"multi_match": {"query": query, "fields": ["title^3", "brand^2", "description^1.5", "all_text"], "type": "best_fields"}}}
        query_params = {"query_term": query, "search_type": "weighted"}
        es_response = await self._perform_search("weighted", self.search_alias, query_body, query_params)
        return es_response.get("hits", {"total": {"value": 0}, "hits": []})

    async def autocomplete_search(self, prefix: str) -> Dict[str, Any]:
        query_body = {"size": 5, "query": {"multi_match": {"query": prefix, "fields": ["title.autocomplete", "brand.autocomplete"], "type": "bool_prefix"}}, "_source": ["title", "brand", "sku"]}
        query_params = {"prefix": prefix, "search_type": "autocomplete"}
        es_response = await self._perform_search("autocomplete", self.search_alias, query_body, query_params)
        return es_response.get("hits", {"total": {"value": 0}, "hits": []})

    async def fuzzy_search(self, query: str) -> Dict[str, Any]:
        query_body = {"query": {"bool": {"should": [
            {"multi_match": {"query": query, "fields": ["title^2", "brand", "all_text"], "boost": 2}},
            {"multi_match": {"query": query, "fields": ["title.ngram", "all_text.ngram"], "boost": 1.5}},
            {"multi_match": {"query": query, "fields": ["title", "all_text"], "fuzziness": "AUTO", "boost": 1}}
        ]}}}
        query_params = {"query_term": query, "search_type": "fuzzy"}
        es_response = await self._perform_search("fuzzy", self.search_alias, query_body, query_params)
        return es_response.get("hits", {"total": {"value": 0}, "hits": []})

    async def advanced_search(self, query: str, filters: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        query_body = {
            "query": {"bool": {"must": {"multi_match": {"query": query, "fields": ["title^3", "brand^2", "description^1.5", "all_text"]}}, "filter": []}},
            "aggs": {
                "brands": {"terms": {"field": "brand.keyword", "size": 20}},
                "categories": {"terms": {"field": "category_breadcrumbs.keyword", "size": 20}},
                "price_ranges": {"range": {"field": "price.amount", "ranges": [{"to": 10000}, {"from": 10000, "to": 50000}, {"from": 50000, "to": 100000}, {"from": 100000}]}}
            }
        }
        if filters:
            if filters.get("brand"): query_body["query"]["bool"]["filter"].append({"term": {"brand.keyword": filters["brand"]}})
            if filters.get("category"): query_body["query"]["bool"]["filter"].append({"term": {"category_breadcrumbs.keyword": filters["category"]}})
            if filters.get("minPrice") is not None or filters.get("maxPrice") is not None:
                price_filter = {"range": {"price.amount": {}}}
                if filters.get("minPrice") is not None: price_filter["range"]["price.amount"]["gte"] = filters["minPrice"]
                if filters.get("maxPrice") is not None: price_filter["range"]["price.amount"]["lte"] = filters["maxPrice"]
                query_body["query"]["bool"]["filter"].append(price_filter)
            if filters.get("attributes"):
                for key, value in filters["attributes"].items(): query_body["query"]["bool"]["filter"].append({"term": {f"attributes.{key}": value}})
        
        query_params_for_span = {"query_term": query, "search_type": "advanced"}
        if filters: 
            for f_key, f_val in filters.items():
                if f_key != "attributes": 
                    query_params_for_span[f"filter_{f_key}"] = str(f_val)
            if "attributes" in filters:
                for attr_key, attr_val in filters["attributes"].items():
                    query_params_for_span[f"filter_attr_{attr_key}"] = str(attr_val)
        
        es_response = await self._perform_search("advanced", self.search_alias, query_body, query_params_for_span)
        return es_response