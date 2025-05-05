from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession
from app.config.database import get_write_db, get_read_db
from app.services.order_manager import OrderManager
from app.schemas import OrderCreate, OrderCreateResponse, OrderResponse, TestOrderCreate, TestOrderItemCreate
from app.models.order import OrderStatus, OrderItem
from typing import List
import logging

# 로깅 설정
logger = logging.getLogger(__name__)

router = APIRouter()

@router.post("/", response_model=OrderCreateResponse)
async def create_order(
    order: OrderCreate,
    # background_tasks: BackgroundTasks = BackgroundTasks()
):
    logger.info("POST /api/orders/ called")
    manager = OrderManager()  # DB 세션을 전달하지 않음
    try:
        # return await manager.create_order(order, background_tasks)
        return await manager.create_order(order)
    except Exception as e:
        logger.error(f"Error creating order: {str(e)}")
        raise HTTPException(status_code=400, detail=str(e))

@router.get("/{order_id}", response_model=OrderResponse)
async def get_order(
    order_id: int
):
    logger.info(f"GET /api/orders/{order_id} called")
    manager = OrderManager()  # DB 세션을 전달하지 않음
    try:
        return await manager.get_order(order_id)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting order: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/user/{user_id}", response_model=List[OrderResponse])
async def get_user_orders(
    user_id: str
):
    logger.info(f"GET /api/orders/user/{user_id} called")
    manager = OrderManager()  # DB 세션을 전달하지 않음
    try:
        return await manager.get_user_orders(user_id)
    except Exception as e:
        logger.error(f"Error getting user orders: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@router.put("/{order_id}/status", response_model=OrderResponse)
async def update_order_status(
    order_id: int, 
    status: OrderStatus
):
    logger.info(f"PUT /api/orders/{order_id}/status called")
    manager = OrderManager()  # DB 세션을 전달하지 않음
    try:
        return await manager.update_order_status(order_id, status)
    except Exception as e:
        logger.error(f"Error updating order status: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

# @router.post("/test/saga", response_model=OrderResponse)
# async def create_test_order_for_saga(
#     order_data: TestOrderCreate,
#     db: AsyncSession = Depends(get_write_db)  # Write DB 사용
# ):
#     """
#     SAGA 패턴 테스트를 위한 특별한 엔드포인트.
#     quantity validation을 우회하여 0 quantity 주문을 생성할 수 있습니다.
#     """
#     logger.info("Creating test order for SAGA pattern testing")
#     manager = OrderManager(db)
#     try:
#         # quantity validation을 우회하기 위해 직접 OrderItem 객체 생성
#         order_items = [
#             TestOrderItemCreate(
#                 product_id=item.product_id,
#                 quantity=item.quantity
#             ) for item in order_data.items
#         ]
        
#         # OrderCreate 객체를 수정하여 validation을 우회
#         test_order_data = OrderCreate(
#             user_id=order_data.user_id,
#             items=order_items
#         )
        
#         return await manager.create_order(test_order_data)
#     except Exception as e:
#         logger.error(f"Error creating test order: {str(e)}")
#         raise HTTPException(status_code=500, detail=str(e))