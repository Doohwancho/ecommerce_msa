from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.config.database import get_mysql_db
from app.services.order_manager import OrderManager
from app.models.schemas import OrderCreate, OrderResponse
from app.models.order import OrderStatus
from typing import List
import logging

# 로깅 설정
logger = logging.getLogger(__name__)

router = APIRouter()

@router.post("/", response_model=OrderResponse)
async def create_order(order: OrderCreate, db: Session = Depends(get_mysql_db)):
    logger.info("POST /api/orders/ called")
    manager = OrderManager(db)
    new_order = await manager.create_order(order)
    return new_order

@router.get("/{order_id}", response_model=OrderResponse)
def get_order(order_id: int, db: Session = Depends(get_mysql_db)):
    logger.info(f"GET /api/orders/{order_id} called")
    manager = OrderManager(db)
    return manager.get_order(order_id)

@router.get("/user/{user_id}", response_model=List[OrderResponse])
def get_user_orders(user_id: str, db: Session = Depends(get_mysql_db)):
    logger.info(f"GET /api/orders/user/{user_id} called")
    manager = OrderManager(db)
    return manager.get_user_orders(user_id)

@router.put("/{order_id}/status", response_model=OrderResponse)
def update_order_status(
    order_id: int, 
    status: OrderStatus, 
    db: Session = Depends(get_mysql_db)
):
    logger.info(f"PUT /api/orders/{order_id}/status called")
    manager = OrderManager(db)
    return manager.update_order_status(order_id, status)