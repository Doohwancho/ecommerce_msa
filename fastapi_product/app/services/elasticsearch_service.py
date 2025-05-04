from elasticsearch import AsyncElasticsearch
from typing import Dict, List, Optional, Any
import logging
from datetime import datetime, timedelta, timezone

logger = logging.getLogger(__name__)

class ElasticsearchService:
    def __init__(self, es_client: AsyncElasticsearch):
        self.client = es_client
        self.source_index = "my_db.products"  # mongodb에서 가져온 원본 데이터 
        self.index_name = "products_optimized" # 검색 최적화 인덱스 먹인 데이터 
        self.search_alias = "products_search" # alias for `products_optimized`
        self.reindex_metadata_index = ".reindex_metadata"  # 메타데이터 저장용 인덱스


    async def setup_alias(self) -> bool:
        """Set up the search alias for the index"""
        try:
            # Remove existing alias if it exists
            if await self.client.indices.exists_alias(name=self.search_alias):
                await self.client.indices.delete_alias(index="_all", name=self.search_alias)
            
            # Add new alias
            await self.client.indices.update_aliases(
                body={
                    "actions": [
                        {
                            "add": {
                                "index": self.index_name,
                                "alias": self.search_alias
                            }
                        }
                    ]
                }
            )
            return True
        except Exception as e:
            logger.error(f"Error setting up alias: {str(e)}")
            return False

    async def create_product_index(self) -> bool:
        """Create a new optimized product index with custom mappings and settings"""
        try:
            # Check if index exists and delete if it does
            if await self.client.indices.exists(index=self.index_name):
                await self.client.indices.delete(index=self.index_name)

            # Create new index with optimized settings
            await self.client.indices.create(
                index=self.index_name,
                body={
                    "settings": {
                        "number_of_shards": 3,
                        "number_of_replicas": 1,
                        "analysis": {
                            "tokenizer": {
                                "ngram_tokenizer": {
                                    "type": "ngram",
                                    "min_gram": 2,
                                    "max_gram": 3,
                                    "token_chars": ["letter", "digit"]
                                },
                                "autocomplete_tokenizer": {
                                    "type": "edge_ngram",
                                    "min_gram": 1,
                                    "max_gram": 10,
                                    "token_chars": ["letter", "digit"]
                                },
                                "nori_user_dict": {  
                                    "type": "nori_tokenizer",  
                                    "decompound_mode": "mixed",
                                    "user_dictionary_rules": [
                                        "운동화",
                                        "축구화"
                                    ]
                                }
                            },
                            "filter": {
                                "korean_synonym_filter": {
                                    "type": "synonym",
                                    "lenient": True,  # 토큰화 문제를 완화
                                    "synonyms": [
                                        "노트북, 랩탑 => 노트북",
                                        "휴대폰, 핸드폰, 스마트폰 => 스마트폰",
                                        "컴퓨터, PC, 피씨, 데스크탑 => 컴퓨터",
                                        "TV, 텔레비전, 티비 => TV"
                                    ],
                                    "ignore_case": True
                                }
                            },
                            "analyzer": {
                                "korean_analyzer": {
                                    "type": "custom",
                                    # "tokenizer": "nori_tokenizer",
                                    "tokenizer": "nori_user_dict",
                                    "filter": [
                                        "nori_readingform",
                                        "lowercase",
                                        "korean_synonym_filter"
                                    ]
                                },
                                "ngram_analyzer": {
                                    "tokenizer": "ngram_tokenizer",
                                    "filter": ["lowercase"]
                                },
                                "autocomplete_analyzer": {
                                    "tokenizer": "autocomplete_tokenizer",
                                    "filter": ["lowercase"]
                                }
                            }
                        }
                    },
                    "mappings": {
                        "properties": {
                            "title": {
                                "type": "text",
                                "analyzer": "korean_analyzer",
                                "fields": {
                                    "ngram": {
                                        "type": "text",
                                        "analyzer": "ngram_analyzer"
                                    },
                                    "autocomplete": {
                                        "type": "text",
                                        "analyzer": "autocomplete_analyzer"
                                    },
                                    "keyword": {
                                        "type": "keyword"
                                    }
                                }
                            },
                            "description": {
                                "type": "text",
                                "analyzer": "korean_analyzer",
                                "fields": {
                                    "ngram": {
                                        "type": "text",
                                        "analyzer": "ngram_analyzer"
                                    }
                                }
                            },
                            "brand": {
                                "type": "text",
                                "analyzer": "korean_analyzer",
                                "fields": {
                                    "autocomplete": {
                                        "type": "text",
                                        "analyzer": "autocomplete_analyzer"
                                    },
                                    "keyword": {
                                        "type": "keyword"
                                    }
                                }
                            },
                            "category_breadcrumbs": {
                                "type": "text",
                                "analyzer": "korean_analyzer",
                                "fields": {
                                    "keyword": {
                                        "type": "keyword"
                                    }
                                }
                            },
                            "category_ids": {"type": "keyword"},
                            "category_path": {"type": "keyword"},
                            "primary_category_id": {"type": "integer"},
                            "category_level": {"type": "integer"},
                            "model": {"type": "keyword"},
                            "sku": {"type": "keyword"},
                            "upc": {"type": "keyword"},
                            "color": {
                                "type": "text",
                                "fields": {
                                    "keyword": {"type": "keyword"}
                                }
                            },
                            "price": {
                                "properties": {
                                    "amount": {"type": "float"},
                                    "currency": {"type": "keyword"}
                                }
                            },
                            "stock": {"type": "integer"},
                            "stock_reserved": {"type": "integer"},
                            "weight": {
                                "properties": {
                                    "value": {"type": "float"},
                                    "unit": {"type": "keyword"}
                                }
                            },
                            "dimensions": {
                                "properties": {
                                    "length": {"type": "float"},
                                    "width": {"type": "float"},
                                    "height": {"type": "float"},
                                    "unit": {"type": "keyword"}
                                }
                            },
                            "attributes": {
                                "properties": {
                                    "processor": {"type": "keyword"},
                                    "ram": {"type": "keyword"},
                                    "storage": {"type": "keyword"},
                                    "screen_size": {"type": "keyword"},
                                    "resolution": {"type": "keyword"},
                                    "material": {"type": "keyword"},
                                    "size": {"type": "keyword"},
                                    "fit": {"type": "keyword"},
                                    "pattern": {"type": "keyword"}
                                }
                            },
                            "variants": {
                                "type": "nested",
                                "properties": {
                                    "id": {"type": "keyword"},
                                    "sku": {"type": "keyword"},
                                    "color": {
                                        "type": "text",
                                        "fields": {
                                            "keyword": {"type": "keyword"}
                                        }
                                    },
                                    "price": {
                                        "properties": {
                                            "amount": {"type": "float"},
                                            "currency": {"type": "keyword"}
                                        }
                                    },
                                    "inventory": {"type": "integer"}
                                }
                            },
                            "images": {
                                "type": "nested",
                                "properties": {
                                    "url": {"type": "keyword", "index": False},
                                    "main": {"type": "boolean"}
                                }
                            },
                            "created_at": {"type": "date"},
                            "updated_at": {"type": "date"},
                            "all_text": {
                                "type": "text",
                                "analyzer": "korean_analyzer",
                                "fields": {
                                    "ngram": {
                                        "type": "text",
                                        "analyzer": "ngram_analyzer"
                                    }
                                }
                            }
                        }
                    }
                }
            )

            # Set up the search alias
            alias_success = await self.setup_alias()
            if not alias_success:
                logger.error("Failed to set up search alias")
                return False

            return True
        except Exception as e:
            logger.error(f"Error creating index: {str(e)}")
            logger.error(f"Full error details: {repr(e)}")  # 더 자세한 에러
            import traceback
            logger.error(f"Traceback: {traceback.format_exc()}")  # 전체 스택 트레이스
            return False

    async def reindex_products(self) -> Dict[str, Any]:
        """Reindex products from source to optimized index"""
        try:
            # Check if source index exists
            if not await self.client.indices.exists(index=self.source_index):
                return {
                    "error": f"Source index '{self.source_index}' does not exist. Please create it first."
                }

            # Check if target index exists
            if not await self.client.indices.exists(index=self.index_name):
                return {
                    "error": f"Target index '{self.index_name}' does not exist. Please create it first using /create-index endpoint."
                }

            # Perform reindexing
            response = await self.client.reindex(
                refresh=True,
                body={
                    "source": {
                        "index": self.source_index,
                        "_source": [
                            "title", "description", "brand", "model", "sku", "upc", "color",
                            "category_*", "price", "stock", "stock_reserved", "weight", "dimensions",
                            "attributes", "variants", "images", "created_at", "updated_at"
                        ]
                    },
                    "dest": {
                        "index": self.index_name
                    },
                    "script": {
                        "source": """
                            StringBuilder sb = new StringBuilder();
                            if (ctx._source.title != null) sb.append(ctx._source.title + " ");
                            if (ctx._source.description != null) sb.append(ctx._source.description + " ");
                            if (ctx._source.brand != null) sb.append(ctx._source.brand + " ");
                            if (ctx._source.model != null) sb.append(ctx._source.model + " ");
                            if (ctx._source.sku != null) sb.append(ctx._source.sku + " ");
                            if (ctx._source.color != null) sb.append(ctx._source.color + " ");
                            
                            if (ctx._source.category_breadcrumbs != null) {
                                for (def cat : ctx._source.category_breadcrumbs) {
                                    sb.append(cat + " ");
                                }
                            }
                            
                            if (ctx._source.attributes != null) {
                                for (def attr : ctx._source.attributes.entrySet()) {
                                    sb.append(attr.getValue() + " ");
                                }
                            }
                            
                            if (ctx._source.variants != null) {
                                for (def variant : ctx._source.variants) {
                                    if (variant.color != null) sb.append(variant.color + " ");
                                    if (variant.attributes != null) {
                                        for (def attr : variant.attributes.entrySet()) {
                                            sb.append(attr.getValue() + " ");
                                        }
                                    }
                                }
                            }
                            
                            ctx._source.all_text = sb.toString();
                        """
                    }
                }
            )

            # Verify reindexing success
            if response.get("failures"):
                return {
                    "error": "Reindexing completed with failures",
                    "failures": response["failures"]
                }

            # 리인덱싱 후 메타데이터 업데이트
            try:
                # 먼저 메타데이터 인덱스 확인/생성
                await self.ensure_metadata_index()

                current_time = datetime.now(timezone.utc).isoformat()
                await self.update_last_reindex_time(current_time)
                logger.info("Successfully updated reindex metadata")
            except Exception as metadata_error:
                # 더 자세한 에러 정보 로깅
                logger.error(f"Failed to update reindex metadata: {str(metadata_error)}")
                logger.error(f"Metadata error type: {type(metadata_error)}")
                logger.error(f"Metadata error args: {metadata_error.args}")

                # 메타데이터 업데이트 실패해도 리인덱싱 결과는 반환
                return {
                    "error": "Reindexing completed but failed to update metadata",
                    "metadata_error": str(metadata_error),
                    "reindex_result": {
                        "total": response["total"],
                        "created": response["created"],
                        "updated": response["updated"],
                        "failures": len(response["failures"]),
                        "took": f"{response['took']}ms"
                    }
                }

            # 모든 작업이 성공하면 결과 반환
            return {
                "total": response["total"],
                "created": response["created"],
                "updated": response["updated"],
                "failures": len(response["failures"]),
                "took": f"{response['took']}ms",
                "last_reindex_time": current_time
            }
        except Exception as e:
            logger.error(f"Error reindexing: {str(e)}")
            return {"error": str(e)}


    async def ensure_metadata_index(self) -> bool:
        """메타데이터 저장용 인덱스가 없으면 생성"""
        try:
            # 먼저 인덱스가 존재하는지 확인
            exists = await self.client.indices.exists(index=self.reindex_metadata_index)
            
            if not exists:
                logger.info(f"Creating metadata index: {self.reindex_metadata_index}")
                # 인덱스 생성
                await self.client.indices.create(
                    index=self.reindex_metadata_index,
                    body={
                        "mappings": {
                            "properties": {
                                "index_name": {"type": "keyword"},
                                "last_reindex_time": {"type": "date"},
                                "reindex_count": {"type": "integer"}
                            }
                        }
                    }
                )
                
                # 초기 메타데이터 생성
                current_time = datetime.now(timezone.utc).isoformat()
                await self.client.index(
                    index=self.reindex_metadata_index,
                    id=self.index_name,
                    body={
                        "index_name": self.index_name,
                        "last_reindex_time": current_time,
                        "reindex_count": 0
                    },
                    refresh=True
                )
                logger.info(f"Successfully created metadata index and initial document for {self.index_name}")
            else:
                logger.info(f"Metadata index {self.reindex_metadata_index} already exists")
                
            return True
            
        except Exception as e:
            logger.error(f"메타데이터 인덱스 생성/확인 오류: {str(e)}")
            raise  # 에러를 상위로 전파
    
    async def get_last_reindex_time(self) -> str:
        """마지막 리인덱싱 시간 가져오기"""
        try:
            # Ensure metadata index exists
            if not await self.ensure_metadata_index():
                logger.error("Failed to ensure metadata index exists")
                return datetime.now(timezone.utc).isoformat()
            
            try:
                # 메타데이터 조회
                result = await self.client.get(
                    index=self.reindex_metadata_index,
                    id=self.index_name
                )
                return result["_source"]["last_reindex_time"]
            except Exception as e:
                # 메타데이터가 없으면 현재 시간으로 초기화
                logger.warning(f"메타데이터 조회 실패, 현재 시간으로 초기화: {str(e)}")
                current_time = datetime.now(timezone.utc).isoformat()
                await self.update_last_reindex_time(current_time)
                return current_time
                
        except Exception as e:
            logger.error(f"마지막 리인덱싱 시간 조회 오류: {str(e)}")
            # 오류 시 현재 시간 반환
            return datetime.now(timezone.utc).isoformat()
    
    async def update_last_reindex_time(self, timestamp: str = None) -> bool:
        """리인덱싱 메타데이터 업데이트"""
        try:
            if timestamp is None:
                timestamp = datetime.now(timezone.utc).isoformat()
            
            # 먼저 메타데이터 인덱스가 존재하는지 확인
            await self.ensure_metadata_index()
            
            # 문서가 존재하는지 확인
            try:
                exists = await self.client.exists(
                    index=self.reindex_metadata_index,
                    id=self.index_name
                )
            except:
                exists = False
            
            if exists:
                # 문서가 존재하면 업데이트
                # 방법 1: doc만 사용
                await self.client.update(
                    index=self.reindex_metadata_index,
                    id=self.index_name,
                    body={
                        "doc": {
                            "last_reindex_time": timestamp,
                        }
                    },
                    refresh=True
                )
                
                # reindex_count 증가는 별도로 처리
                await self.client.update(
                    index=self.reindex_metadata_index,
                    id=self.index_name,
                    body={
                        "script": {
                            "source": "if (ctx._source.containsKey('reindex_count')) { ctx._source.reindex_count += 1 } else { ctx._source.reindex_count = 1 }",
                            "lang": "painless"
                        }
                    },
                    refresh=True
                )
            else:
                # 문서가 없으면 새로 생성
                await self.client.index(
                    index=self.reindex_metadata_index,
                    id=self.index_name,
                    body={
                        "index_name": self.index_name,
                        "last_reindex_time": timestamp,
                        "reindex_count": 1
                    },
                    refresh=True
                )
                
            logger.info(f"Successfully updated last reindex time to: {timestamp}")
            return True
        except Exception as e:
            logger.error(f"리인덱싱 메타데이터 업데이트 오류: {str(e)}")
            raise
    
    async def incremental_reindex(self) -> Dict[str, Any]:
        """마지막 업데이트 시간 이후의 데이터만 리인덱싱"""
        try:
            # 소스/대상 인덱스 확인
            if not await self.client.indices.exists(index=self.source_index):
                return {"error": f"소스 인덱스 '{self.source_index}'가 존재하지 않습니다."}
            
            if not await self.client.indices.exists(index=self.index_name):
                return {"error": f"대상 인덱스 '{self.index_name}'가 존재하지 않습니다. 먼저 /create-index 엔드포인트를 사용해 생성하세요."}
            
            # 마지막 리인덱싱 시간 가져오기
            last_reindex_time = await self.get_last_reindex_time()
            logger.info(f"마지막 리인덱싱 시간: {last_reindex_time}")
            
            # 디버깅: 소스 인덱스의 최근 문서 조회
            recent_docs = await self.client.search(
                index=self.source_index,
                body={
                    "size": 5,
                    "sort": [{"updated_at": {"order": "desc"}}],
                    "_source": ["_id", "updated_at", "created_at", "title"]
                }
            )
            
            logger.info("=== 최근 문서 정보 ===")
            for doc in recent_docs["hits"]["hits"]:
                logger.info(f"ID: {doc['_id']}")
                logger.info(f"updated_at: {doc['_source'].get('updated_at', 'N/A')}")
                logger.info(f"created_at: {doc['_source'].get('created_at', 'N/A')}")
                logger.info(f"title: {doc['_source'].get('title', 'N/A')}")
                logger.info("---")
            
            # 날짜 형식 확인을 위한 추가 쿼리
            format_test = await self.client.search(
                index=self.source_index,
                body={
                    "size": 0,
                    "aggs": {
                        "updated_field_type": {
                            "terms": {
                                "field": "updated_at",
                                "size": 1
                            }
                        }
                    }
                }
            )
            
            logger.info(f"Updated_at 필드 집계 결과: {format_test.get('aggregations', {})}")
            
            # 마지막 리인덱싱 이후 변경된 문서 수 확인
            count_response = await self.client.count(
                index=self.source_index,
                body={
                    "query": {
                        "range": {
                            "updated_at": {
                                "gt": last_reindex_time
                            }
                        }
                    }
                }
            )
            
            docs_to_update = count_response["count"]
            logger.info(f"업데이트할 문서 수: {docs_to_update}")
            
            # 디버깅: 실제 쿼리 내용 확인
            debug_query = {
                "query": {
                    "range": {
                        "updated_at": {
                            "gt": last_reindex_time
                        }
                    }
                }
            }
            logger.info(f"실행된 쿼리: {debug_query}")
            
            # 대안 쿼리 테스트 (gte 사용)
            alt_count_response = await self.client.count(
                index=self.source_index,
                body={
                    "query": {
                        "range": {
                            "updated_at": {
                                "gte": last_reindex_time
                            }
                        }
                    }
                }
            )
            logger.info(f"대안 쿼리 (gte) 결과: {alt_count_response['count']} 문서")
            
            if docs_to_update == 0:
                # 추가 디버깅 정보
                return {
                    "message": "업데이트할 문서가 없습니다.",
                    "last_reindex_time": last_reindex_time,
                    "docs_to_update": 0,
                    "debug_info": {
                        "recent_docs": recent_docs["hits"]["hits"][:3] if recent_docs["hits"]["hits"] else [],
                        "alternative_count": alt_count_response["count"]
                    }
                }
            
            # 부분 리인덱싱 실행
            response = await self.client.reindex(
                refresh=True,
                body={
                    "source": {
                        "index": self.source_index,
                        "query": {
                            "range": {
                                "updated_at": {
                                    "gt": last_reindex_time
                                }
                            }
                        },
                        "_source": [
                            "title", "description", "brand", "model", "sku", "upc", "color",
                            "category_*", "price", "stock", "stock_reserved", "weight", "dimensions",
                            "attributes", "variants", "images", "created_at", "updated_at"
                        ]
                    },
                    "dest": {
                        "index": self.index_name,
                        "op_type": "index"  # 겹치는 문서는 덮어쓰기
                    },
                    "script": {
                        "source": """
                            StringBuilder sb = new StringBuilder();
                            if (ctx._source.title != null) sb.append(ctx._source.title + " ");
                            if (ctx._source.description != null) sb.append(ctx._source.description + " ");
                            if (ctx._source.brand != null) sb.append(ctx._source.brand + " ");
                            if (ctx._source.model != null) sb.append(ctx._source.model + " ");
                            if (ctx._source.sku != null) sb.append(ctx._source.sku + " ");
                            if (ctx._source.color != null) sb.append(ctx._source.color + " ");
                            
                            if (ctx._source.category_breadcrumbs != null) {
                                for (def cat : ctx._source.category_breadcrumbs) {
                                    sb.append(cat + " ");
                                }
                            }
                            
                            if (ctx._source.attributes != null) {
                                for (def attr : ctx._source.attributes.entrySet()) {
                                    sb.append(attr.getValue() + " ");
                                }
                            }
                            
                            if (ctx._source.variants != null) {
                                for (def variant : ctx._source.variants) {
                                    if (variant.color != null) sb.append(variant.color + " ");
                                    if (variant.attributes != null) {
                                        for (def attr : variant.attributes.entrySet()) {
                                            sb.append(attr.getValue() + " ");
                                        }
                                    }
                                }
                            }
                            
                            ctx._source.all_text = sb.toString();
                        """
                    }
                }
            )
            
            # 리인덱싱 메타데이터 업데이트
            current_time = datetime.now().isoformat()
            await self.update_last_reindex_time(current_time)
            
            # 결과 확인
            if response.get("failures"):
                return {
                    "error": "부분 리인덱싱이 실패한 항목이 있습니다.",
                    "failures": response["failures"],
                    "updated_time": current_time
                }
            
            return {
                "message": "부분 리인덱싱 완료",
                "total_docs": response["total"],
                "updated_docs": response["created"] + response["updated"],
                "failures": len(response["failures"]),
                "took": f"{response['took']}ms",
                "previous_reindex_time": last_reindex_time,
                "current_reindex_time": current_time
            }
            
        except Exception as e:
            logger.error(f"부분 리인덱싱 오류: {str(e)}")
            return {"error": str(e)}


    # 특정 상품만 빠르게 리인덱싱 (긴급 업데이트용)
    async def reindex_specific_products(self, product_ids: List[str]) -> Dict[str, Any]:
        """특정 상품 ID 목록만 빠르게 리인덱싱"""
        try:
            if not product_ids:
                return {"error": "리인덱싱할 상품 ID가 제공되지 않았습니다."}
                
            # 소스/대상 인덱스 확인
            if not await self.client.indices.exists(index=self.source_index):
                return {"error": f"소스 인덱스 '{self.source_index}'가 존재하지 않습니다."}
            
            if not await self.client.indices.exists(index=self.index_name):
                return {"error": f"대상 인덱스 '{self.index_name}'가 존재하지 않습니다."}
            
            # 특정 상품 ID만 리인덱싱
            response = await self.client.reindex(
                refresh=True,
                body={
                    "source": {
                        "index": self.source_index,
                        "query": {
                            "terms": {
                                "_id": product_ids
                            }
                        }
                    },
                    "dest": {
                        "index": self.index_name,
                        "op_type": "index"  # 겹치는 문서는 덮어쓰기
                    },
                    "script": {
                        "source": """
                            StringBuilder sb = new StringBuilder();
                            if (ctx._source.title != null) sb.append(ctx._source.title + " ");
                            if (ctx._source.description != null) sb.append(ctx._source.description + " ");
                            if (ctx._source.brand != null) sb.append(ctx._source.brand + " ");
                            if (ctx._source.model != null) sb.append(ctx._source.model + " ");
                            if (ctx._source.sku != null) sb.append(ctx._source.sku + " ");
                            if (ctx._source.color != null) sb.append(ctx._source.color + " ");
                            
                            if (ctx._source.category_breadcrumbs != null) {
                                for (def cat : ctx._source.category_breadcrumbs) {
                                    sb.append(cat + " ");
                                }
                            }
                            
                            if (ctx._source.attributes != null) {
                                for (def attr : ctx._source.attributes.entrySet()) {
                                    sb.append(attr.getValue() + " ");
                                }
                            }
                            
                            if (ctx._source.variants != null) {
                                for (def variant : ctx._source.variants) {
                                    if (variant.color != null) sb.append(variant.color + " ");
                                    if (variant.attributes != null) {
                                        for (def attr : variant.attributes.entrySet()) {
                                            sb.append(attr.getValue() + " ");
                                        }
                                    }
                                }
                            }
                            
                            ctx._source.all_text = sb.toString();
                        """
                    }
                }
            )
            
            return {
                "message": "지정한 상품 리인덱싱 완료",
                "product_ids": product_ids,
                "total_docs": response["total"],
                "updated_docs": response["created"] + response["updated"],
                "failures": len(response["failures"]),
                "took": f"{response['took']}ms"
            }
            
        except Exception as e:
            logger.error(f"특정 상품 리인덱싱 오류: {str(e)}")
            return {"error": str(e)}

    async def debug_date_formats(self) -> Dict[str, Any]:
        """날짜 형식 디버깅"""
        try:
            # 메타데이터에서 저장된 형식 확인
            metadata = await self.client.get(
                index=self.reindex_metadata_index,
                id=self.index_name
            )
            
            # 소스 인덱스에서 실제 데이터 형식 확인
            sample_docs = await self.client.search(
                index=self.source_index,
                body={
                    "size": 3,
                    "_source": ["updated_at", "created_at"]
                }
            )
            
            return {
                "metadata_format": metadata["_source"]["last_reindex_time"],
                "sample_docs": sample_docs["hits"]["hits"],
                "current_time": datetime.now(timezone.utc).isoformat()
            }
        except Exception as e:
            return {"error": str(e)}

    async def basic_search(self, query: str) -> Dict[str, Any]:
        """Basic search using all_text field"""
        try:
            response = await self.client.search(
                index=self.search_alias,  # products_search alias 사용
                body={
                    "query": {
                        "match": {
                            "all_text": query
                        }
                    }
                }
            )
            return response["hits"]
        except Exception as e:
            logger.error(f"Error in basic search: {str(e)}")
            return {"total": {"value": 0}, "hits": []}

    async def weighted_search(self, query: str) -> Dict[str, Any]:
        """Search with field-specific weights"""
        try:
            response = await self.client.search(
                index=self.search_alias,  # products_search alias 사용
                body={
                    "query": {
                        "multi_match": {
                            "query": query,
                            "fields": [
                                "title^3",
                                "brand^2",
                                "description^1.5",
                                "all_text"
                            ],
                            "type": "best_fields"
                        }
                    }
                }
            )
            return response["hits"]
        except Exception as e:
            logger.error(f"Error in weighted search: {str(e)}")
            return {"total": {"value": 0}, "hits": []}

    async def autocomplete_search(self, prefix: str) -> Dict[str, Any]:
        """Autocomplete search"""
        try:
            response = await self.client.search(
                index=self.search_alias,  # products_search alias 사용
                body={
                    "size": 5,
                    "query": {
                        "multi_match": {
                            "query": prefix,
                            "fields": [
                                "title.autocomplete",
                                "brand.autocomplete"
                            ],
                            "type": "bool_prefix"
                        }
                    },
                    "_source": ["title", "brand", "sku"]
                }
            )
            return response["hits"]
        except Exception as e:
            logger.error(f"Error in autocomplete search: {str(e)}")
            return {"total": {"value": 0}, "hits": []}

    async def fuzzy_search(self, query: str) -> Dict[str, Any]:
        """Fuzzy search with typo tolerance"""
        try:
            response = await self.client.search(
                index=self.search_alias,  # products_search alias 사용
                body={
                    "query": {
                        "bool": {
                            "should": [
                                {
                                    "multi_match": {
                                        "query": query,
                                        "fields": ["title^2", "brand", "all_text"],
                                        "boost": 2
                                    }
                                },
                                {
                                    "multi_match": {
                                        "query": query,
                                        "fields": ["title.ngram", "all_text.ngram"],
                                        "boost": 1.5
                                    }
                                },
                                {
                                    "multi_match": {
                                        "query": query,
                                        "fields": ["title", "all_text"],
                                        "fuzziness": "AUTO",
                                        "boost": 1
                                    }
                                }
                            ]
                        }
                    }
                }
            )
            return response["hits"]
        except Exception as e:
            logger.error(f"Error in fuzzy search: {str(e)}")
            return {"total": {"value": 0}, "hits": []}

    async def advanced_search(
        self,
        query: str,
        filters: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Advanced search with filters and aggregations"""
        try:
            query_body = {
                "query": {
                    "bool": {
                        "must": {
                            "multi_match": {
                                "query": query,
                                "fields": [
                                    "title^3",
                                    "brand^2",
                                    "description^1.5",
                                    "all_text"
                                ]
                            }
                        },
                        "filter": []
                    }
                },
                "aggs": {
                    "brands": {
                        "terms": {"field": "brand.keyword", "size": 20}
                    },
                    "categories": {
                        "terms": {"field": "category_breadcrumbs.keyword", "size": 20}
                    },
                    "price_ranges": {
                        "range": {
                            "field": "price.amount",
                            "ranges": [
                                {"to": 10000},
                                {"from": 10000, "to": 50000},
                                {"from": 50000, "to": 100000},
                                {"from": 100000}
                            ]
                        }
                    }
                }
            }

            if filters:
                if filters.get("brand"):
                    query_body["query"]["bool"]["filter"].append({
                        "term": {"brand.keyword": filters["brand"]}
                    })

                if filters.get("category"):
                    query_body["query"]["bool"]["filter"].append({
                        "term": {"category_breadcrumbs.keyword": filters["category"]}
                    })

                if filters.get("minPrice") is not None or filters.get("maxPrice") is not None:
                    price_filter = {"range": {"price.amount": {}}}
                    if filters.get("minPrice") is not None:
                        price_filter["range"]["price.amount"]["gte"] = filters["minPrice"]
                    if filters.get("maxPrice") is not None:
                        price_filter["range"]["price.amount"]["lte"] = filters["maxPrice"]
                    query_body["query"]["bool"]["filter"].append(price_filter)

                if filters.get("attributes"):
                    for key, value in filters["attributes"].items():
                        query_body["query"]["bool"]["filter"].append({
                            "term": {f"attributes.{key}": value}
                        })

            response = await self.client.search(
                index=self.search_alias,  # products_search alias 사용
                body=query_body
            )

            return {
                "hits": response["hits"],
                "aggregations": response["aggregations"]
            }
        except Exception as e:
            logger.error(f"Error in advanced search: {str(e)}")
            return {
                "hits": {"total": {"value": 0}, "hits": []},
                "aggregations": {}
            } 