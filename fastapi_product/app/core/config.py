# app/core/config.py
import os
from pydantic import BaseSettings

class Settings(BaseSettings):
    PROJECT_NAME: str = "Product Service"
    API_V1_STR: str = "/api/v1"
    
    # Kafka Settings
    KAFKA_BOOTSTRAP_SERVERS: str = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "kafka-service:9092")
    KAFKA_CONSUMER_GROUP: str = os.getenv("KAFKA_CONSUMER_GROUP", "product-service-group")
    
    # Database Settings
    MYSQL_USER: str = os.getenv("MYSQL_USER", "root")
    MYSQL_PASSWORD: str = os.getenv("MYSQL_PASSWORD", "root")
    MYSQL_HOST: str = os.getenv("MYSQL_HOST", "mysql-service")
    MYSQL_DATABASE: str = os.getenv("MYSQL_DATABASE", "product_category")
    
    # MongoDB Settings
    # MONGODB_URL: str = os.getenv("MONGODB_URL", "mongodb-service:27017")
    MONGODB_USERNAME: str = os.getenv("MONGODB_USERNAME", "mongo")
    MONGODB_PASSWORD: str = os.getenv("MONGODB_PASSWORD", "mongo")
    
    # gRPC Settings
    GRPC_PORT: int = int(os.getenv("GRPC_PORT", "50051"))
    
    class Config:
        env_file = ".env"
        case_sensitive = True

settings = Settings()