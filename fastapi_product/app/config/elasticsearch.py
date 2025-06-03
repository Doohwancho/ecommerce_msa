from elasticsearch import AsyncElasticsearch
import logging
import os

logger = logging.getLogger(__name__)

class ElasticsearchConfig:
    def __init__(self):
        self.hosts = os.getenv("ELASTICSEARCH_HOSTS", "http://elasticsearch-service:9200").split(",")
        self.username = os.getenv("ELASTICSEARCH_USERNAME", "elastic")
        self.password = os.getenv("ELASTICSEARCH_PASSWORD", "changeme")
        self.client = None
        logger.info("ElasticsearchConfig initialized.", extra={"hosts": self.hosts})

    async def get_client(self):
        """Elasticsearch 클라이언트를 싱글톤으로 반환"""
        if self.client is None:
            logger.info("Elasticsearch client is None, attempting to create new client.", extra={"hosts": self.hosts})
            try:
                self.client = AsyncElasticsearch(
                    hosts=self.hosts,
                    basic_auth=(self.username, self.password)
                )
                await self.client.info() # Test connection
                logger.info("Successfully connected to Elasticsearch.", extra={"hosts": self.hosts})
            except Exception as e:
                logger.error("Failed to connect to Elasticsearch.", extra={"hosts": self.hosts, "error": str(e)}, exc_info=True)
                self.client = None # Ensure client is reset on failure
                raise
        return self.client

    async def close(self):
        """Elasticsearch 클라이언트 연결 종료"""
        if self.client:
            try:
                await self.client.close()
                self.client = None
                logger.info("Elasticsearch connection closed.")
            except Exception as e:
                logger.error("Error closing Elasticsearch connection.", extra={"error": str(e)}, exc_info=True)
                # Attempt to set client to None even if close fails, to allow re-initialization
                self.client = None 
        else:
            logger.info("Elasticsearch client was already None, no action taken for close.")

# 전역 설정 인스턴스 생성
elasticsearch_config = ElasticsearchConfig() 