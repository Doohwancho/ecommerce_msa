from app.config.payment_kafka import KafkaConsumer
from app.services.payment_service import PaymentService
from app.config.payment_database import AsyncSessionLocal
from app.schemas.payment_schemas import PaymentCreate, PaymentMethod  
import json
from app.config.payment_logging import logger

class PaymentManager:
    def __init__(self):
        self.kafka_consumer = None
        self.db = AsyncSessionLocal()
        self.payment_service = PaymentService(self.db)
    
    async def initialize_kafka(self, bootstrap_servers: str, group_id: str):
        # 사용자 정의 KafkaConsumer 클래스 사용
        self.kafka_consumer = KafkaConsumer(
            bootstrap_servers=bootstrap_servers,
            group_id=group_id
        )
        
        # 이벤트 핸들러 등록
        self.kafka_consumer.register_handler('order_created', self.handle_order_created)
        
        # Kafka 소비자 시작
        await self.kafka_consumer.start()
    
    async def handle_order_created(self, event_data: dict):
        try:
            # Order 모듈의 실제 이벤트 데이터 구조에 맞게 수정
            payment_data = PaymentCreate(
                order_id=event_data.get('order_id'),
                amount=event_data.get('total_amount'),
                currency="KRW",
                payment_method=PaymentMethod.CREDIT_CARD  
            )
            
            payment = await self.payment_service.create_payment(payment_data)
            logger.info(f"Created payment for order {payment.payment_id}")
        except Exception as e:
            logger.error(f"Error processing order created event: {e}")
            await self.db.rollback()
    
    async def stop(self):
        if self.kafka_consumer:
            await self.kafka_consumer.stop()
        await self.db.close()