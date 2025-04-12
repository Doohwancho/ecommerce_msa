from sqlalchemy.orm import Session
from app.models.order import Order, OrderItem, OrderStatus
from app.schemas.order import OrderCreate, OrderItemCreate, OrderUpdate
from app.grpc.product_client import ProductClient
from app.grpc.user_client import UserClient
from fastapi import HTTPException
import asyncio
import logging
import datetime

# 로깅 설정
logger = logging.getLogger(__name__)

class OrderManager:
    def __init__(self, session: Session):
        self.session = session
        self.product_client = ProductClient()
        self.user_client = UserClient()
    
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
        self.session.flush()

        total_amount = 0.0
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

        order.total_amount = total_amount
        self.session.commit()
        logger.info(f"Order {order.order_id} created successfully")
        return order
    
    def get_order(self, order_id: int) -> Order:
        logger.info(f"Fetching order {order_id}")
        order = self.session.query(Order).filter(Order.order_id == order_id).first()
        if not order:
            logger.error(f"Order {order_id} not found")
            raise HTTPException(status_code=404, detail=f"Order {order_id} not found")
        return order
    
    def get_user_orders(self, user_id: str) -> list[Order]:
        logger.info(f"Fetching orders for user {user_id}")
        return self.session.query(Order).filter(Order.user_id == user_id).all()
    
    def update_order_status(self, order_id: int, status: OrderStatus) -> Order:
        logger.info(f"Updating status for order {order_id} to {status}")
        order = self.get_order(order_id)
        order.status = status
        self.session.commit()
        logger.info(f"Order {order_id} status updated to {status}")
        return order

    async def close(self):
        await self.product_client.close()
        await self.user_client.close()

    async def update_order(self, order_id: str, order: OrderUpdate):
        db_order = await self.get_order(order_id)
        for key, value in order.dict(exclude_unset=True).items():
            setattr(db_order, key, value)
        await self.session.commit()
        await self.session.refresh(db_order)
        return db_order

    async def delete_order(self, order_id: str):
        db_order = await self.get_order(order_id)
        await self.session.delete(db_order)
        await self.session.commit()
        return True