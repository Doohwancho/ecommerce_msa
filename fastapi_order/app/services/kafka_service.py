import os
from app.config.kafka_consumer import OrderKafkaConsumer
from app.services.order_manager import OrderManager
from app.config.database import AsyncSessionLocal
import logging
import json
import asyncio

logger = logging.getLogger(__name__)

# Kafka 설정
KAFKA_BOOTSTRAP_SERVERS = os.getenv('KAFKA_BOOTSTRAP_SERVERS', 'kafka-service:9092')
KAFKA_CONSUMER_GROUP = os.getenv('KAFKA_CONSUMER_GROUP', 'order-service-group')
PAYMENT_TOPIC = 'payment'  # Payment 서비스의 토픽

# 글로벌 변수로 Kafka Consumer 인스턴스 유지
kafka_consumer = None

async def handle_payment_success_wrapper(event_data):
    """payment_success 이벤트를 처리하는 래퍼 함수"""
    async with AsyncSessionLocal() as session:
        order_manager = OrderManager(session)
        await order_manager.handle_payment_success(event_data)

async def handle_payment_failed_wrapper(event_data):
    """payment_failed 이벤트를 처리하는 래퍼 함수"""
    async with AsyncSessionLocal() as session:
        order_manager = OrderManager(session)
        await order_manager.handle_payment_failed(event_data)

async def init_kafka_consumer():
    """Kafka Consumer를 초기화하고 시작합니다."""
    global kafka_consumer
    
    # 이미 실행 중인 경우 중복 시작 방지
    if kafka_consumer is not None:
        return
    
    # Kafka Consumer 생성
    kafka_consumer = OrderKafkaConsumer(
        bootstrap_servers=KAFKA_BOOTSTRAP_SERVERS,
        group_id=KAFKA_CONSUMER_GROUP
    )
    
    # payment_success 이벤트 핸들러 등록
    kafka_consumer.register_handler(
        PAYMENT_TOPIC, 
        handle_payment_success_wrapper,
        event_type='payment_success'  # 이벤트 타입 지정
    )
    
    # payment_failed 이벤트 핸들러 등록
    kafka_consumer.register_handler(
        PAYMENT_TOPIC, 
        handle_payment_failed_wrapper,
        event_type='payment_failed'  # 이벤트 타입 지정
    )
    
    # Consumer 시작
    kafka_consumer.start()
    logger.info(f"Kafka consumer started, listening to topic: {PAYMENT_TOPIC} for payment events")

async def stop_kafka_consumer():
    """Kafka Consumer를 종료합니다."""
    global kafka_consumer
    if kafka_consumer:
        kafka_consumer.stop()
        kafka_consumer = None
        logger.info("Kafka consumer stopped")