from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession
from app.config.database import get_async_mysql_db
from app.services.order_manager import OrderManager
from app.schemas import OrderCreate, OrderCreateResponse, OrderResponse
from app.models.order import OrderStatus
from typing import List
import logging

# 로깅 설정
logger = logging.getLogger(__name__)

router = APIRouter()

@router.post("/", response_model=OrderCreateResponse)
async def create_order(
    order: OrderCreate,
    db: AsyncSession = Depends(get_async_mysql_db),
    # background_tasks: BackgroundTasks = BackgroundTasks()
):
    logger.info("POST /api/orders/ called")
    manager = OrderManager(db)
    try:
        # return await manager.create_order(order, background_tasks)
        return await manager.create_order(order)
    except Exception as e:
        logger.error(f"Error creating order: {str(e)}")
        raise HTTPException(status_code=400, detail=str(e))

@router.get("/{order_id}", response_model=OrderResponse)
async def get_order(order_id: int, db: AsyncSession = Depends(get_async_mysql_db)):
    logger.info(f"GET /api/orders/{order_id} called")
    manager = OrderManager(db)
    try:
        return await manager.get_order(order_id)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting order: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/user/{user_id}", response_model=List[OrderResponse])
async def get_user_orders(user_id: str, db: AsyncSession = Depends(get_async_mysql_db)):
    logger.info(f"GET /api/orders/user/{user_id} called")
    manager = OrderManager(db)
    try:
        return await manager.get_user_orders(user_id)
    except Exception as e:
        logger.error(f"Error getting user orders: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@router.put("/{order_id}/status", response_model=OrderResponse)
async def update_order_status(
    order_id: int, 
    status: OrderStatus, 
    db: AsyncSession = Depends(get_async_mysql_db)
):
    logger.info(f"PUT /api/orders/{order_id}/status called")
    manager = OrderManager(db)
    try:
        return await manager.update_order_status(order_id, status)
    except Exception as e:
        logger.error(f"Error updating order status: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))