from app.config.payment_kafka import KafkaConsumer
from app.services.payment_service import PaymentService
from app.config.payment_database import AsyncSessionLocal
from app.schemas.payment_schemas import PaymentCreate, PaymentMethod  
from app.models.outbox import Outbox
import uuid
import json
from app.config.payment_logging import logger
import asyncio
import datetime

class PaymentManager:
    def __init__(self):
        self.kafka_consumer = None
        # self.db = AsyncSessionLocal()
        # self.payment_service = PaymentService(self.db)
        self.max_retries = 3
    
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
        retry_count = 0

        while retry_count < self.max_retries:
            try:
                logger.info(f"Processing order_created event: {event_data}")
                
                # Debezium 형식에서 실제 payload 추출
                actual_payload = event_data
                
                # Debezium 메시지 형식 확인 및 추출
                if isinstance(event_data, dict):
                    if 'payload' in event_data and 'after' in event_data['payload']:
                        # Debezium CDC 형식
                        after_data = event_data['payload']['after']
                        if 'payload' in after_data:
                            # payload가 문자열이면 JSON 파싱
                            if isinstance(after_data['payload'], str):
                                try:
                                    actual_payload = json.loads(after_data['payload'])
                                except json.JSONDecodeError:
                                    logger.error("Failed to parse payload JSON")
                                    raise ValueError("Invalid payload format")
                            else:
                                actual_payload = after_data['payload']
                
                logger.info(f"Extracted payload: {actual_payload}")
                
                # 필수 데이터 필드 검증
                order_id = actual_payload.get('order_id')
                total_amount = actual_payload.get('total_amount')
                items = actual_payload.get('items', [])
                
                if not order_id or total_amount is None or not items:
                    raise ValueError(f"Missing required fields in event data: {actual_payload}")
                
                # 테스트용으로 첫 번째 아이템의 quantity 사용
                test_quantity = items[0].get('quantity', 0) if items else 0
                
                payment_data = PaymentCreate(
                    order_id=order_id,
                    amount=total_amount,
                    currency="KRW",
                    payment_method=PaymentMethod.CREDIT_CARD,
                    stock_reserved=test_quantity  # 테스트용 (Payment SAGA 패턴 테스트)
                )
                
                # 여기서 새로운 세션을 사용
                async with AsyncSessionLocal() as session:
                    payment_service = PaymentService(session)
                    payment = await payment_service.create_payment(payment_data)
                    logger.info(f"Created payment for order {payment.order_id}")

                # 결제 성공 - 보상 트랜잭션 필요 없음
                return 
            except Exception as e:
                retry_count += 1
                logger.error(f"Error processing order created event (attempt {retry_count}/{self.max_retries}): {str(e)}")
                
                if retry_count < self.max_retries:
                    # 재시도 전 대기 (지수 백오프)
                    await asyncio.sleep(2 ** retry_count)
                else:
                    # 모든 재시도 실패 - 보상 트랜잭션 시작
                    await self.create_compensation_event(actual_payload)

    async def create_compensation_event(self, original_event: dict):
        """Outbox 패턴을 사용하여 보상 이벤트 생성"""
        try:
            # 새로운 세션 생성
            async with AsyncSessionLocal() as session:
                async with session.begin():  # 트랜잭션 시작
                    # 실패한 결제 정보 로깅
                    order_id = original_event.get('order_id')
                    items = original_event.get('items', [])  # 주문 아이템 정보 가져오기
                    logger.info(f"Creating compensation event for failed payment of order {order_id}")
                    
                    # 보상 이벤트 데이터 생성
                    compensation_event = {
                        'order_id': order_id,
                        'items': items,  # 각 아이템의 product_id와 quantity 정보
                        'reason': 'Payment processing failed after multiple retries',
                        'timestamp': datetime.datetime.utcnow().isoformat()
                    }
                    
                    # Outbox 테이블에 보상 이벤트 저장
                    outbox_event = Outbox(
                        id=str(uuid.uuid4()),
                        aggregatetype="payment",  # 도메인/서비스 이름으로 변경
                        aggregateid=str(order_id),
                        type="payment_failed",    # 이벤트 타입은 그대로 유지
                        payload=compensation_event
                    )
                    session.add(outbox_event)
                    logger.info(f"Compensation event for order {order_id} added to outbox")
                    # 세션은 with 블록을 나갈 때 자동으로 커밋됩니다
        except Exception as e:
            logger.critical(f"Failed to create compensation event: {str(e)}")
    
    async def stop(self):
        if self.kafka_consumer:
            await self.kafka_consumer.stop()
        # await self.db.close()