from elasticsearch import AsyncElasticsearch
from app.config.logging import logger
import os

class ElasticsearchConfig:
    def __init__(self):
        self.hosts = os.getenv("ELASTICSEARCH_HOSTS", "http://elasticsearch-service:9200").split(",")
        self.username = os.getenv("ELASTICSEARCH_USERNAME", "elastic")
        self.password = os.getenv("ELASTICSEARCH_PASSWORD", "changeme")
        self.client = None

    async def get_client(self):
        """Elasticsearch 클라이언트를 싱글톤으로 반환"""
        if self.client is None:
            try:
                self.client = AsyncElasticsearch(
                    hosts=self.hosts,
                    basic_auth=(self.username, self.password)
                )
                # 연결 테스트
                await self.client.info()
                logger.info("Successfully connected to Elasticsearch")
            except Exception as e:
                logger.error(f"Failed to connect to Elasticsearch: {str(e)}")
                raise
        return self.client

    async def close(self):
        """Elasticsearch 클라이언트 연결 종료"""
        if self.client:
            await self.client.close()
            self.client = None
            logger.info("Elasticsearch connection closed")

# 전역 설정 인스턴스 생성
elasticsearch_config = ElasticsearchConfig() 