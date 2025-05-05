from app.config.kafka_consumer import KafkaConsumer
from app.services.product_service import ProductService
from app.config.database import WriteSessionLocal
from app.models.outbox import Outbox
import uuid
import json
from app.config.logging import logger
import asyncio
import datetime

class ProductManager:
    def __init__(self):
        self.kafka_consumer = None
        self.max_retries = 3
    
    async def initialize_kafka(self, bootstrap_servers: str, group_id: str):
        # 사용자 정의 KafkaConsumer 클래스 사용
        self.kafka_consumer = KafkaConsumer(
            bootstrap_servers=bootstrap_servers,
            group_id=group_id
        )

        # 이벤트 핸들러 등록
        self.kafka_consumer.register_handler('order_success', self.handle_order_success)
        self.kafka_consumer.register_handler('order_failed', self.handle_order_failed)
        
        # Kafka 소비자 시작
        await self.kafka_consumer.start()
        logger.info("Initialized Kafka consumer and registered handlers")
    
    async def handle_order_success(self, event_data: dict):
        retry_count = 0
        while retry_count < self.max_retries:
            try:
                logger.info(f"Processing order_success event: {event_data}")
                
                # items 필드 직접 접근
                items = event_data.get('items', [])
                if not items:
                    raise ValueError("No items found in order event")
                
                for item in items:
                    product_id = item.get('product_id')
                    quantity = item.get('quantity')
                    
                    if not product_id or not quantity:
                        logger.warning(f"Invalid item data: {item}")
                        continue
                    
                    # 여기서 새로운 세션을 사용
                    async with WriteSessionLocal() as session:
                        product_service = ProductService()
                        logger.info(f"Calling confirm_inventory with product_id={product_id}, quantity={quantity}")
                        
                        # 핵심 변경: ConfirmInventoryRequest 객체가 아닌 개별 인자 전달
                        await product_service.confirm_inventory(product_id=product_id, quantity=quantity)
                        logger.info(f"Confirmed inventory for product {product_id}, quantity {quantity}")
                    
                # 성공적으로 처리됨
                return
                    
            except Exception as e:
                retry_count += 1
                logger.error(f"Error processing order success event (attempt {retry_count}/{self.max_retries}): {str(e)}")
                
                if retry_count < self.max_retries:
                    await asyncio.sleep(2 ** retry_count)
                else:
                    await self.create_compensation_event(event_data)

    async def handle_order_failed(self, event_data: dict):
        retry_count = 0

        while retry_count < self.max_retries:
            try:
                logger.info(f"Processing order_failed event: {event_data}")
                
                # items 필드 직접 접근 (이미 파싱된 상태)
                items = event_data.get('items', [])
                if not items:
                    raise ValueError("No items found in order failed event")
                
                for item in items:
                    product_id = item.get('product_id')
                    quantity = item.get('quantity')
                    
                    if not product_id or not quantity:
                        logger.warning(f"Invalid item data: {item}")
                        continue
                    
                    # 여기서 새로운 세션을 사용
                    async with WriteSessionLocal() as session:
                        product_service = ProductService()
                        await product_service.release_inventory(product_id=product_id, quantity=quantity)
                        logger.info(f"Released inventory for product {product_id}, quantity {quantity}")
                
                # 성공적으로 처리됨
                return
                
            except Exception as e:
                retry_count += 1
                logger.error(f"Error processing order failed event (attempt {retry_count}/{self.max_retries}): {str(e)}")
                
                if retry_count < self.max_retries:
                    # 재시도 전 대기 (지수 백오프)
                    await asyncio.sleep(2 ** retry_count)
                else:
                    # 모든 재시도 실패 - 매우 심각한 상황이므로 명확히 로깅
                    logger.critical(f"CRITICAL: Failed to release inventory after {self.max_retries} attempts. Manual intervention required!")
                    await self.create_compensation_event(event_data)


    async def create_compensation_event(self, original_event: dict):
        """Outbox 패턴을 사용하여 보상 이벤트 생성"""
        try:
            print("create_compensation_event")
            # TODO
            # inventory rollback confirm실패는 재시도 몇번 후 안되면 logger.critical()로 입력 

            # # 새로운 세션 생성
            # async with AsyncSessionLocal() as session:
            #     async with session.begin():  # 트랜잭션 시작
            #         # 실패한 결제 정보 로깅
            #         order_id = original_event.get('order_id')
            #         items = original_event.get('items', [])  # 주문 아이템 정보 가져오기
            #         logger.info(f"Creating compensation event for failed payment of order {order_id}")
                    
            #         # 보상 이벤트 데이터 생성
            #         compensation_event = {
            #             'order_id': order_id,
            #             'items': items,  # 각 아이템의 product_id와 quantity 정보
            #             'reason': 'Payment processing failed after multiple retries',
            #             'timestamp': datetime.datetime.utcnow().isoformat()
            #         }
                    
            #         # Outbox 테이블에 보상 이벤트 저장
            #         outbox_event = Outbox(
            #             id=str(uuid.uuid4()),
            #             aggregatetype="payment",  # 도메인/서비스 이름으로 변경
            #             aggregateid=str(order_id),
            #             type="payment_failed",    # 이벤트 타입은 그대로 유지
            #             payload=compensation_event
            #         )
            #         session.add(outbox_event)
            #         logger.info(f"Compensation event for order {order_id} added to outbox")
                    # 세션은 with 블록을 나갈 때 자동으로 커밋됩니다
        except Exception as e:
            logger.critical(f"Failed to create compensation event: {str(e)}")
    
    async def stop(self):
        if self.kafka_consumer:
            await self.kafka_consumer.stop()
        # await self.db.close()