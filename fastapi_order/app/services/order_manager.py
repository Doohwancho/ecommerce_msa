from sqlalchemy.orm import Session
from app.models.order import Order, OrderItem, OrderStatus
from app.models.schemas import OrderCreate
from app.clients.product_client import ProductClient
from app.clients.user_client import UserClient
from fastapi import HTTPException
import asyncio
import logging

# 로깅 설정
logger = logging.getLogger(__name__)

class OrderManager:
    def __init__(self, db_session: Session):
        self.session = db_session
        self.product_client = ProductClient()
        self.user_client = UserClient()
    
    async def create_order(self, order_create: OrderCreate) -> Order:
        logger.info("Creating a new order")
        # 사용자 존재 확인
        await self.user_client.get_user(order_create.user_id)
        
        # 상품 정보 확인 및 가격 가져오기
        product_ids = [item.product_id for item in order_create.items]
        product_details = []
        
        # 각 상품 정보 병렬로 요청
        product_tasks = [self.product_client.get_product(pid) for pid in product_ids]
        products = await asyncio.gather(*product_tasks)
        
        # 제품 ID를 키로 하는 딕셔너리 생성
        product_dict = {p["product_id"]: p for p in products}
        
        # 주문 생성
        total_amount = 0
        for item in order_create.items:
            product = product_dict[item.product_id]
            price = product["price"]
            total_amount += price * item.quantity
            product_details.append({
                "product_id": item.product_id,
                "quantity": item.quantity,
                "price": price
            })
        
        # 주문 레코드 생성
        new_order = Order(
            user_id=order_create.user_id,
            status=OrderStatus.PENDING,
            total_amount=total_amount
        )
        self.session.add(new_order)
        self.session.flush()  # ID 생성을 위해 flush
        
        # 주문 아이템 생성
        for product in product_details:
            order_item = OrderItem(
                order_id=new_order.order_id,
                product_id=product["product_id"],
                quantity=product["quantity"],
                price_at_order=product["price"]
            )
            self.session.add(order_item)
        
        self.session.commit()
        logger.info(f"Order {new_order.order_id} created successfully")
        return new_order
    
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