from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from app.models.order import Order, OrderItem, OrderStatus
from app.models.outbox import Outbox
from app.models.failed_event import FailedEvent
from app.schemas.order import OrderCreate, OrderItemCreate, OrderUpdate
from app.grpc.product_client import ProductClient
from app.grpc.user_client import UserClient
from app.config.kafka import get_kafka_producer, ORDER_CREATED_TOPIC, ORDER_DLQ_TOPIC
from fastapi import HTTPException, BackgroundTasks
import asyncio
import logging
import datetime
import json
from typing import Optional
from kafka.errors import KafkaError
import uuid

# 로깅 설정
logger = logging.getLogger(__name__)

class OrderManager:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.product_client = ProductClient()
        self.user_client = UserClient()
        self.kafka_producer = get_kafka_producer()
        self.max_retries = 3
        self.retry_delay = 1  # seconds
    
    async def _store_failed_event(self, event_type: str, event_data: dict, error: str) -> None:
        """Store failed event in database"""
        try:
            failed_event = FailedEvent(
                event_type=event_type,
                event_data=event_data,
                error_message=error,
                status='pending'
            )
            self.session.add(failed_event)
            await self.session.commit()
            logger.info(f"Stored failed event in database: {error}")
        except Exception as e:
            logger.critical(f"Failed to store event in database: {str(e)}")
            # If database storage fails, we're in a critical situation
            # Log the event details for manual recovery
            logger.critical(f"Critical event loss - Event type: {event_type}, Data: {json.dumps(event_data)}")

    async def _publish_to_dlq(self, event: dict, error: str) -> None:
        """Publish failed event to Dead Letter Queue"""
        try:
            dlq_event = {
                'original_event': event,
                'error': error,
                'timestamp': datetime.datetime.utcnow().isoformat(),
                'retry_count': 0  # Initial retry count
            }
            self.kafka_producer.send(ORDER_DLQ_TOPIC, dlq_event)
            self.kafka_producer.flush()
            logger.info(f"Published failed event to DLQ: {error}")
        except Exception as e:
            logger.error(f"Failed to publish to DLQ: {str(e)}")
            # If DLQ publishing fails, store in database
            await self._store_failed_event('order_created', event, f"DLQ Error: {str(e)}")

    async def _publish_kafka_event(self, topic: str, event: dict) -> None:
        """Publish event to Kafka in background"""
        try:
            # feat: 중복 방지
            # order_id를 키로 사용해서 보내기
            # 같은 order_id를 가진 메시지는 같은 파티션으로 가게 됨
            # Consumer에서 order_id로 중복 체크하기 쉬워짐
            # 메시지 순서도 보장됨 (같은 키는 같은 파티션으로 가니까)
            # 근데 이건 완벽한 중복 방지는 아님 (네트워크 문제로 재시도하면 여전히 중복 가능)
            # 그렇기 때문에 카프카 설정에 Idempotent 설정을 해줌 
            self.kafka_producer.send(
                topic,
                key=str(event['order_id']).encode('utf-8'),  # 키로 order_id 사용
                value=event
            )
            self.kafka_producer.flush()
            logger.info(f"Successfully published event to Kafka topic: {topic}")
        except KafkaError as e:
            logger.error(f"Failed to publish event to Kafka: {str(e)}")
            # Try to publish to DLQ
            await self._publish_to_dlq(event, str(e))

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
        
        try:
            # step1) 사용자 존재 확인
            user = await self.user_client.get_user(order_data.user_id)
            if not user:
                raise HTTPException(status_code=404, detail="User not found")
            
            # step2) 상품 가용성 체크와 가격 계산 (트랜잭션 밖에서)
            total_amount = 0.0
            order_items = []
            products = {}  # product_id -> product 정보 캐싱
            
            for item_data in order_data.items:
                is_available, product = await self.product_client.check_availability(
                    item_data.product_id,
                    item_data.quantity
                )
                if not is_available:
                    raise HTTPException(
                        status_code=400,
                        detail=f"Product {item_data.product_id} is not available"
                    )
                products[item_data.product_id] = product
                total_amount += product.price * item_data.quantity
                order_items.append({
                    'product_id': item_data.product_id,
                    'quantity': item_data.quantity,
                    'price': product.price
                })

            # step3) 트랜잭션 시작
            async with self.session.begin():
                # Create order
                order = Order(
                    user_id=order_data.user_id,
                    status=OrderStatus.PENDING,
                    total_amount=total_amount,
                    created_at=datetime.datetime.utcnow(),
                    updated_at=datetime.datetime.utcnow()
                )
                self.session.add(order)
                await self.session.flush()

                # Create order items
                for item_data in order_data.items:
                    product = products[item_data.product_id]  # 캐시된 product 정보 사용
                    order_item = OrderItem(
                        order_id=order.order_id,
                        product_id=item_data.product_id,
                        quantity=item_data.quantity,
                        price_at_order=product.price,  # 수정: item_data.price -> product.price.amount
                        created_at=datetime.datetime.utcnow()
                    )
                    self.session.add(order_item)

                # Create outbox event for Debezium CDC
                order_created_event = {
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
                self.session.add(outbox_event)

                await self.session.commit()
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


    async def get_order(self, order_id: int) -> Order:
        logger.info(f"Fetching order {order_id}")
        # Load order with its items in a single query
        query = (
            select(Order)
            .options(selectinload(Order.items))
            .where(Order.order_id == order_id)
        )
        result = await self.session.execute(query)
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
        result = await self.session.execute(query)
        return result.scalars().all()
    
    async def update_order_status(self, order_id: int, status: OrderStatus) -> Order:
        logger.info(f"Updating status for order {order_id} to {status}")
        order = await self.get_order(order_id)
        order.status = status
        await self.session.commit()
        return order
    
    async def update_order(self, order_id: str, order_update: OrderUpdate) -> Order:
        logger.info(f"Updating order {order_id}")
        order = await self.get_order(order_id)
        
        # Update order fields
        for field, value in order_update.dict(exclude_unset=True).items():
            setattr(order, field, value)
        
        order.updated_at = datetime.datetime.utcnow()
        await self.session.commit()
        return order
    
    async def delete_order(self, order_id: str):
        logger.info(f"Deleting order {order_id}")
        order = await self.get_order(order_id)
        await self.session.delete(order)
        await self.session.commit()
    
    async def close(self):
        """Cleanup resources"""
        await self.session.close()
        await self.product_client.close()
        await self.user_client.close()