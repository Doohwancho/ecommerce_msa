from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from app.models.order import Order, OrderItem, OrderStatus
from app.models.outbox import Outbox
from app.models.failed_event import FailedEvent
from app.schemas.order import OrderCreate, OrderItemCreate, OrderUpdate
from app.grpc.product_client import ProductClient
from app.grpc.user_client import UserClient
from fastapi import HTTPException, BackgroundTasks
import asyncio
import logging
import datetime
import json
from typing import Optional
from kafka.errors import KafkaError
import uuid
from sqlalchemy.orm import Session
from sqlalchemy.exc import SQLAlchemyError
from app.config.kafka_consumer import OrderKafkaConsumer
import os

# 로깅 설정
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class OrderManager:
    def __init__(self, db: Session):
        self.db = db
        self.kafka_consumer = OrderKafkaConsumer(
            bootstrap_servers=os.getenv('KAFKA_BOOTSTRAP_SERVERS', 'kafka-service:9092'),
            group_id=os.getenv('KAFKA_CONSUMER_GROUP', 'order-service-group')
        )
        self.user_client = UserClient()
        self.product_client = ProductClient()
        self.max_retries = 3
        self.retry_delay = 1  # seconds
    
    async def _store_failed_event(self, event_type: str, event_data: dict, error: str) -> None:
        """Store failed event in database"""
        try:
            # 이벤트 데이터를 JSON 문자열로 변환
            event_data_json = json.dumps(event_data)
            
            failed_event = FailedEvent(
                event_type=event_type,
                event_data=event_data_json,  # JSON 문자열로 저장
                error_message=error,
                status='pending'
            )
            self.db.add(failed_event)
            await self.db.commit()
            logger.info(f"Stored failed event in database: {error}")
        except Exception as e:
            logger.critical(f"Failed to store event in database: {str(e)}")
            # If database storage fails, we're in a critical situation
            # Log the event details for manual recovery
            logger.critical(f"Critical event loss - Event type: {event_type}, Data: {json.dumps(event_data)}")

    # async def _publish_to_dlq(self, event: dict, error: str) -> None:
    #     """Publish failed event to Dead Letter Queue"""
    #     try:
    #         dlq_event = {
    #             'original_event': event,
    #             'error': error,
    #             'timestamp': datetime.datetime.utcnow().isoformat(),
    #             'retry_count': 0  # Initial retry count
    #         }
    #         self.kafka_producer.send(ORDER_DLQ_TOPIC, dlq_event)
    #         self.kafka_producer.flush()
    #         logger.info(f"Published failed event to DLQ: {error}")
    #     except Exception as e:
    #         logger.error(f"Failed to publish to DLQ: {str(e)}")
    #         # If DLQ publishing fails, store in database
    #         await self._store_failed_event('order_created', event, f"DLQ Error: {str(e)}")

    # async def _publish_kafka_event(self, topic: str, event: dict) -> None:
    #     """Publish event to Kafka in background"""
    #     try:
    #         # feat: 중복 방지
    #         # order_id를 키로 사용해서 보내기
    #         # 같은 order_id를 가진 메시지는 같은 파티션으로 가게 됨
    #         # Consumer에서 order_id로 중복 체크하기 쉬워짐
    #         # 메시지 순서도 보장됨 (같은 키는 같은 파티션으로 가니까)
    #         # 근데 이건 완벽한 중복 방지는 아님 (네트워크 문제로 재시도하면 여전히 중복 가능)
    #         # 그렇기 때문에 카프카 설정에 Idempotent 설정을 해줌 
    #         self.kafka_producer.send(
    #             topic,
    #             key=str(event['order_id']).encode('utf-8'),  # 키로 order_id 사용
    #             value=event
    #         )
    #         self.kafka_producer.flush()
    #         logger.info(f"Successfully published event to Kafka topic: {topic}")
    #     except KafkaError as e:
    #         logger.error(f"Failed to publish event to Kafka: {str(e)}")
    #         # Try to publish to DLQ
    #         await self._publish_to_dlq(event, str(e))

    # ver1) 주문 후 kafka.send() 호출 + error handling(retry + DLQ + write on DB)
    # async def create_order(self, order_data: OrderCreate, background_tasks: BackgroundTasks):
    #     logger.info("Creating a new order")
    #     # step1) 사용자 존재 확인
    #     user = await self.user_client.get_user(order_data.user_id)
    #     if not user:
    #         raise HTTPException(status_code=404, detail="User not found")
 
    #     # step2) Create order
    #     order = Order(
    #         user_id=order_data.user_id,
    #         status=OrderStatus.PENDING,
    #         total_amount=0.0,
    #         created_at=datetime.datetime.utcnow(),
    #         updated_at=datetime.datetime.utcnow()
    #     )
    #     self.session.add(order)
    #     await self.session.flush()

    #     # step3) 주문 아이템 생성
    #     total_amount = 0.0
    #     order_items = []
    #     for item_data in order_data.items:
    #         # Check product availability and get product details in one call
    #         is_available, product = await self.product_client.check_availability(
    #             item_data.product_id,
    #             item_data.quantity
    #         )
    #         if not is_available:
    #             raise ValueError(f"Product {item_data.product_id} is not available")

    #         # Create order item
    #         order_item = OrderItem(
    #             order_id=order.order_id,
    #             product_id=item_data.product_id,
    #             quantity=item_data.quantity,
    #             price_at_order=product.price,
    #             created_at=datetime.datetime.utcnow()
    #         )
    #         self.session.add(order_item)
    #         total_amount += product.price * item_data.quantity
    #         order_items.append({
    #             'product_id': item_data.product_id,
    #             'quantity': item_data.quantity,
    #             'price': product.price
    #         })

    #     order.total_amount = total_amount
    #     await self.session.commit()
    #     logger.info(f"Order {order.order_id} created successfully")

    #     # step4) 주문 생성 이벤트 발행
    #     # Prepare order created event
    #     order_created_event = {
    #         'order_id': order.order_id,
    #         'user_id': order.user_id,
    #         'total_amount': order.total_amount,
    #         'status': order.status.value,
    #         'items': order_items,
    #         'created_at': order.created_at.isoformat()
    #     }
        
    #     # step5) 주문 생성 이벤트 발행
    #     # Add Kafka event publishing to background tasks
    #     background_tasks.add_task(
    #         self._publish_kafka_event,
    #         ORDER_CREATED_TOPIC,
    #         order_created_event
    #     )

    #     # step6) 주문 생성 이벤트 발행
    #     # Refresh the order and load its items
    #     await self.session.refresh(order)
    #     # Load the items relationship
    #     query = (
    #         select(Order)
    #         .options(selectinload(Order.items))
    #         .where(Order.order_id == order.order_id)
    #     )
    #     result = await self.session.execute(query)
    #     loaded_order = result.scalar_one()
        
    #     return loaded_order

    # ver2) outbox pattern
    async def create_order(self, order_data: OrderCreate):
        logger.info("Creating a new order")
        
        # 예약된 재고를 추적하기 위한 목록
        reserved_items = []

        try:
            # step1) 사용자 존재 확인
            try:
                user = await self.user_client.get_user(order_data.user_id)
                if not user:
                    raise HTTPException(status_code=404, detail=f"User {order_data.user_id} not found")
            except Exception as e:
                logger.error(f"Error validating user: {str(e)}")
                raise HTTPException(status_code=400, detail=f"Invalid user ID or user not found: {str(e)}")
            
            # step2) 상품 가용성 체크와 가격 계산 (트랜잭션 밖에서)
            total_amount = 0.0
            order_items = []
            products = {}  # product_id -> product 정보 캐싱
            
            for item_data in order_data.items:
                # 재고 확인 및 예약을 한 번에 처리
                success, message = await self.product_client.check_and_reserve_inventory(
                    item_data.product_id,
                    item_data.quantity
                )
                
                if not success:
                    # 에러 메시지 반환
                    raise HTTPException(
                        status_code=400,
                        detail=f"Failed to reserve product {item_data.product_id}: {message}"
                    )
                # 성공적으로 예약된 항목 추적
                reserved_items.append((item_data.product_id, item_data.quantity))
                
                # 제품 정보 가져오기 (가격 계산을 위해)
                product = await self.product_client.get_product(item_data.product_id)
                inventory = await self.product_client.get_product_inventory(item_data.product_id)
                products[item_data.product_id] = {
                    'product': product,
                    'inventory': inventory
                }

                total_amount += product.price * item_data.quantity
                order_items.append({
                    'product_id': item_data.product_id,
                    'quantity': item_data.quantity,
                    'price': product.price
                })

            # step3) 트랜잭션 시작
            async with self.db.begin():
                # Create order
                order = Order(
                    user_id=order_data.user_id,
                    status=OrderStatus.PENDING,
                    total_amount=total_amount,
                    created_at=datetime.datetime.utcnow(),
                    updated_at=datetime.datetime.utcnow()
                )
                self.db.add(order)
                await self.db.flush()

                # Create order items
                for item_data in order_data.items:
                    product_info = products[item_data.product_id]  # 캐시된 product 정보 사용
                    order_item = OrderItem(
                        order_id=order.order_id,
                        product_id=item_data.product_id,
                        quantity=item_data.quantity,
                        price_at_order=product_info['product'].price,  # product의 price 사용
                        created_at=datetime.datetime.utcnow()
                    )
                    self.db.add(order_item)

                # Create outbox event for Debezium CDC
                order_created_event = {
                    'type': "order_created",
                    'order_id': str(order.order_id),
                    'user_id': order.user_id,
                    'total_amount': total_amount,
                    'status': OrderStatus.PENDING.value,
                    'items': order_items,
                    'created_at': datetime.datetime.utcnow().isoformat()
                }

                outbox_event = Outbox(
                    id=str(uuid.uuid4()),
                    aggregatetype="order",  # Debezium이 필요로 하는 필드. 이게 kafka에서 토픽 값. subscriber는 토픽으로 구독하거나, 밑에 이벤트 타입으로 구독할 수도 있음. 
                    aggregateid=str(order.order_id),  # Debezium이 필요로 하는 필드: 해당 aggregate의 ID
                    type="order_created",  # 이벤트 타입, kafka에서는 메시지 헤더의 eventType 값. ex. order_updated, order_created, order_deleted
                    payload=order_created_event  # 이벤트 데이터
                )
                self.db.add(outbox_event)

                await self.db.commit()
                logger.info(f"Order {order.order_id} created successfully with outbox event")


            return  {
                "order_id": order.order_id,
                "status": "success",
                "message": "Order created successfully"
            }

        except Exception as e:
            logger.error(f"Failed to create order: {str(e)}")
            raise HTTPException(
                status_code=500,
                detail=f"Failed to create order: {str(e)}"
            )    

    async def handle_payment_failed(self, event_data):
        """Payment 실패 이벤트 처리 핸들러"""
        logger.info(f"Received payment_failed event: {event_data}")
        original_event_data = event_data  # 원본 데이터 보존

        order_id = None
        items = []

        try:
            # event_data 파싱
            if isinstance(event_data, str):
                try:
                    event_data = json.loads(event_data)
                except json.JSONDecodeError:
                    logger.error(f"Failed to parse payment_failed event (string): {event_data}")
                    return

            if not isinstance(event_data, dict):
                logger.error(f"Invalid event_data type: {type(event_data)}")
                return

            # Debezium 메시지 처리
            if 'payload' in event_data:
                payload = event_data['payload']
                if isinstance(payload, str):
                    try:
                        payload = json.loads(payload)
                        event_data = payload
                    except json.JSONDecodeError:
                        logger.error(f"Failed to parse payload as JSON: {payload}")
                        return
                else:
                    event_data = payload

            logger.debug(f"Processed event data: {event_data}")

            order_id = event_data.get('order_id')
            items = event_data.get('items', [])

            if not order_id:
                logger.error(f"No order_id in payment_failed event: {event_data}")
                return

            # 트랜잭션 및 DB 처리 (내부 try~except)
            try:
                async with self.db.begin():
                    # 1. 주문 조회
                    query = (
                        select(Order)
                        .options(selectinload(Order.items))
                        .where(Order.order_id == int(order_id))
                    )
                    result = await self.db.execute(query)
                    order = result.scalar_one_or_none()

                    if not order:
                        logger.error(f"Order {order_id} not found")
                        return

                    # 2. 주문 상태 변경
                    order.status = OrderStatus.CANCELLED
                    order.updated_at = datetime.datetime.utcnow()

                    # 3. 이벤트 발행
                    order_items = []
                    for item in order.items:
                        order_items.append({
                            'product_id': item.product_id,
                            'quantity': item.quantity,
                            'price': item.price_at_order
                        })

                    order_cancelled_event = {
                        'type': "order_cancelled",
                        'order_id': str(order.order_id),
                        'user_id': order.user_id,
                        'status': OrderStatus.CANCELLED.value,
                        'reason': 'Payment failed',
                        'items': order_items,
                        'created_at': datetime.datetime.utcnow().isoformat()
                    }

                    outbox_event = Outbox(
                        id=str(uuid.uuid4()),
                        aggregatetype="order",
                        aggregateid=str(order.order_id),
                        type="order_cancelled",
                        payload=order_cancelled_event
                    )
                    self.db.add(outbox_event)

                logger.info(f"Successfully rolled back order {order_id} due to payment failure")

            except Exception as e:
                logger.error(f"Failed to update order for payment_failed event: {str(e)}")
                if self.db.is_active:
                    await self.db.rollback()
                await self._store_failed_event('payment_failed_processing', {'order_id': order_id, 'items': items}, str(e))

        except Exception as e:
            logger.error(f"Failed to handle payment_failed event: {str(e)}")
            await self._store_failed_event('payment_failed_parsing', original_event_data, str(e))



    async def handle_payment_success(self, event_data):
        original_event_data = event_data  # 원본 데이터 보존
        retry_count = 0

        try:
            logger.info(f"Processing payment_success event data: {event_data}")
         
            # payment_success 구조에서 필요한 필드 추출
            order_id = event_data.get('order_id')
            payment_id = event_data.get('payment_id')
            amount = event_data.get('amount')
            payment_method = event_data.get('payment_method', 'unknown')
            payment_status = event_data.get('payment_status', '')
            
            if not order_id:
                logger.error(f"No order_id in payment_success event: {event_data}")
                await self._store_failed_event('payment_success', event_data, "Missing order_id")
                return

            if payment_status in ['failed', 'cancelled']:
                logger.warning(f"Received payment_success event with conflicting status {payment_status} for order {order_id}")
                return

            logger.info(f"Processing payment success for order_id: {order_id}, payment_id: {payment_id}, amount: {amount}")


            while retry_count < self.max_retries:
                try:
                    # 트랜잭션 시작
                    async with self.db.begin():
                        # 1. 주문 조회
                        query = (
                            select(Order)
                            .options(selectinload(Order.items))
                            .where(Order.order_id == int(order_id))
                        )
                        result = await self.db.execute(query)
                        order = result.scalar_one_or_none()
                        
                        if not order:
                            raise ValueError(f"Order {order_id} not found")
                        
                        # 2. 주문 상태 업데이트
                        order.status = OrderStatus.COMPLETED
                        order.updated_at = datetime.datetime.utcnow()
                        
                        # 3. order_success 이벤트 생성 - 실제 주문 아이템 정보 사용
                        # payment_success 이벤트에는 items가 없으므로 주문에서 직접 가져옴
                        order_items = []
                        for item in order.items:
                            order_items.append({
                                'product_id': item.product_id,
                                'quantity': item.quantity,
                                'price': item.price_at_order
                            })
                        
                        order_success_event = {
                            'type': "order_success",
                            'order_id': str(order.order_id),
                            'user_id': order.user_id,
                            'status': OrderStatus.COMPLETED.value,
                            'items': order_items,
                            'payment_id': payment_id,
                            'amount': amount,
                            'payment_method': payment_method,
                            'payment_status': 'completed',  # 명시적으로 payment_status 추가
                            'created_at': datetime.datetime.utcnow().isoformat()
                        }
                        
                        # 4. Outbox에 이벤트 저장 - order_success 토픽 사용
                        outbox_event = Outbox(
                            id=str(uuid.uuid4()),
                            aggregatetype="order",
                            aggregateid=str(order.order_id),
                            type="order_success",
                            payload=order_success_event
                        )
                        self.db.add(outbox_event)
                        
                        logger.info(f"Order {order_id} status updated to COMPLETED and order_success event created")
                    
                    # 성공적으로 처리됨
                    logger.info(f"Successfully processed payment_success for order {order_id}")
                    return
                    
                except Exception as e:
                    retry_count += 1
                    logger.error(f"Error processing payment success event (attempt {retry_count}/{self.max_retries}): {str(e)}")
                    
                    if retry_count < self.max_retries:
                        await asyncio.sleep(2 ** retry_count)
                    else:
                        logger.error(f"Failed to process payment success event after {self.max_retries} attempts")
                        
                        # 보상 트랜잭션 시작
                        await self.create_compensation_event(event_data)

            # 모든 재시도 실패
            logger.error(f"All retries failed for payment_success event: {event_data}")

        except Exception as e:
            # 외부 try 블록에 대한 예외 처리 (파싱 및 데이터 검증 과정에서 발생한 예외)
            logger.error(f"Error handling payment_success event: {str(e)}")
            await self._store_failed_event('payment_success', original_event_data, str(e))
    
    async def create_compensation_event(self, original_event: dict):
        """Outbox 패턴을 사용하여 보상 이벤트 생성"""
        try:
            async with self.db.begin():
                order_id = original_event.get('order_id')
                logger.info(f"Creating compensation event for failed order update of order {order_id}")
                
                compensation_event = {
                    'type': "order_update_failed",
                    'order_id': order_id,
                    'reason': 'Failed to update order status after payment success',
                    'timestamp': datetime.datetime.utcnow().isoformat()
                }
                
                outbox_event = Outbox(
                    id=str(uuid.uuid4()),
                    aggregatetype="order",
                    aggregateid=str(order_id),
                    type="order_update_failed",
                    payload=compensation_event
                )
                self.db.add(outbox_event)
                logger.info(f"Compensation event for order {order_id} added to outbox")
                
        except Exception as e:
            logger.critical(f"Failed to create compensation event: {str(e)}")

    async def get_order(self, order_id: int) -> Order:
        logger.info(f"Fetching order {order_id}")
        # Load order with its items in a single query
        query = (
            select(Order)
            .options(selectinload(Order.items))
            .where(Order.order_id == order_id)
        )
        result = await self.db.execute(query)
        order = result.scalar_one_or_none()
        
        if not order:
            logger.error(f"Order {order_id} not found")
            raise HTTPException(status_code=404, detail=f"Order {order_id} not found")
        
        return order
    
    async def get_user_orders(self, user_id: str) -> list[Order]:
        logger.info(f"Fetching orders for user {user_id}")
        # Load orders with their items in a single query
        query = (
            select(Order)
            .options(selectinload(Order.items))
            .where(Order.user_id == user_id)
        )
        result = await self.db.execute(query)
        return result.scalars().all()
    
    async def update_order_status(self, order_id: int, status: OrderStatus) -> Order:
        logger.info(f"Updating status for order {order_id} to {status}")
        order = await self.get_order(order_id)
        order.status = status
        await self.db.commit()
        return order
    
    async def update_order(self, order_id: str, order_update: OrderUpdate) -> Order:
        logger.info(f"Updating order {order_id}")
        order = await self.get_order(order_id)
        
        # Update order fields
        for field, value in order_update.dict(exclude_unset=True).items():
            setattr(order, field, value)
        
        order.updated_at = datetime.datetime.utcnow()
        await self.db.commit()
        return order
    
    async def delete_order(self, order_id: str):
        logger.info(f"Deleting order {order_id}")
        order = await self.get_order(order_id)
        await self.db.delete(order)
        await self.db.commit()
    
    async def close(self):
        """Cleanup resources"""
        await self.db.close()
        await self.product_client.close()
        await self.user_client.close()
    async def start_kafka_consumer(self):
        """Start Kafka consumer in the background"""
        await self.kafka_consumer.start()

    async def stop_kafka_consumer(self):
        """Stop Kafka consumer"""
        await self.kafka_consumer.stop()
