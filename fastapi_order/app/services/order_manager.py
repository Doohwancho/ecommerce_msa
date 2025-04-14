from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from app.models.order import Order, OrderItem, OrderStatus
from app.schemas.order import OrderCreate, OrderItemCreate, OrderUpdate
from app.grpc.product_client import ProductClient
from app.grpc.user_client import UserClient
from app.config.kafka import get_kafka_producer, ORDER_CREATED_TOPIC
from fastapi import HTTPException
import asyncio
import logging
import datetime

# 로깅 설정
logger = logging.getLogger(__name__)

class OrderManager:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.product_client = ProductClient()
        self.user_client = UserClient()
        self.kafka_producer = get_kafka_producer()
    
    async def create_order(self, order_data: OrderCreate):
        logger.info("Creating a new order")
        # 사용자 존재 확인
        user = await self.user_client.get_user(order_data.user_id)
        
        # Create order
        order = Order(
            user_id=order_data.user_id,
            status=OrderStatus.PENDING,
            total_amount=0.0,
            created_at=datetime.datetime.utcnow(),
            updated_at=datetime.datetime.utcnow()
        )
        self.session.add(order)
        await self.session.flush()

        total_amount = 0.0
        order_items = []
        for item_data in order_data.items:
            # Check product availability and get product details in one call
            is_available, product = await self.product_client.check_availability(
                item_data.product_id,
                item_data.quantity
            )
            if not is_available:
                raise ValueError(f"Product {item_data.product_id} is not available")

            # Create order item
            order_item = OrderItem(
                order_id=order.order_id,
                product_id=item_data.product_id,
                quantity=item_data.quantity,
                price_at_order=product.price,
                created_at=datetime.datetime.utcnow()
            )
            self.session.add(order_item)
            total_amount += product.price * item_data.quantity
            order_items.append({
                'product_id': item_data.product_id,
                'quantity': item_data.quantity,
                'price': product.price
            })

        order.total_amount = total_amount
        await self.session.commit()
        logger.info(f"Order {order.order_id} created successfully")

        # Publish order created event to Kafka
        order_created_event = {
            'order_id': order.order_id,
            'user_id': order.user_id,
            'total_amount': order.total_amount,
            'status': order.status.value,
            'items': order_items,
            'created_at': order.created_at.isoformat()
        }
        self.kafka_producer.send(ORDER_CREATED_TOPIC, order_created_event)
        self.kafka_producer.flush()
        logger.info(f"Published order created event for order {order.order_id}")

        # Refresh the order and load its items
        await self.session.refresh(order)
        # Load the items relationship
        query = (
            select(Order)
            .options(selectinload(Order.items))
            .where(Order.order_id == order.order_id)
        )
        result = await self.session.execute(query)
        loaded_order = result.scalar_one()
        
        return loaded_order
    
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