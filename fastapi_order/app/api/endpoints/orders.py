from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession
from app.config.database import get_write_db, get_read_db
from app.services.order_manager import OrderManager
from app.schemas import OrderCreate, OrderCreateResponse, OrderResponse, TestOrderCreate, TestOrderItemCreate
from app.models.order import OrderStatus, OrderItem
from typing import List
import logging
from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode

# 로깅 설정
logger = logging.getLogger(__name__)
tracer = trace.get_tracer(__name__)

router = APIRouter()

@router.post("/", response_model=OrderCreateResponse)
async def create_order(
    order: OrderCreate,
    # background_tasks: BackgroundTasks = BackgroundTasks()
):
    with tracer.start_as_current_span("create_order") as span:
        try:
            # Set order creation attributes
            span.set_attribute("order.user_id", order.user_id)
            span.set_attribute("order.items_count", len(order.items))
            
            # Set item details
            for idx, item in enumerate(order.items):
                span.set_attribute(f"order.item_{idx}.product_id", item.product_id)
                span.set_attribute(f"order.item_{idx}.quantity", item.quantity)
            
            logger.info("POST /api/orders/ called")
            manager = OrderManager()
            result = await manager.create_order(order)
            
            # Set order creation result attributes
            if result and hasattr(result, 'order_id'):
                span.set_attribute("order.created_id", result.order_id)
            
            span.set_status(Status(StatusCode.OK))
            return result
        except Exception as e:
            span.set_status(Status(StatusCode.ERROR, str(e)))
            logger.error(f"Error creating order: {str(e)}")
            raise HTTPException(status_code=400, detail=str(e))

@router.get("/{order_id}", response_model=OrderResponse)
async def get_order(
    order_id: int
):
    with tracer.start_as_current_span("get_order") as span:
        try:
            span.set_attribute("order.id", order_id)
            logger.info(f"GET /api/orders/{order_id} called")
            manager = OrderManager()
            result = await manager.get_order(order_id)
            
            # Set order details in span
            if result:
                span.set_attribute("order.status", result.status)
                span.set_attribute("order.user_id", result.user_id)
                span.set_attribute("order.items_count", len(result.items))
            
            span.set_status(Status(StatusCode.OK))
            return result
        except HTTPException:
            raise
        except Exception as e:
            span.set_status(Status(StatusCode.ERROR, str(e)))
            logger.error(f"Error getting order: {str(e)}")
            raise HTTPException(status_code=500, detail=str(e))

@router.get("/user/{user_id}", response_model=List[OrderResponse])
async def get_user_orders(
    user_id: str
):
    with tracer.start_as_current_span("get_user_orders") as span:
        try:
            span.set_attribute("user.id", user_id)
            logger.info(f"GET /api/orders/user/{user_id} called")
            manager = OrderManager()
            orders = await manager.get_user_orders(user_id)
            
            # Set orders summary in span
            span.set_attribute("orders.count", len(orders))
            if orders:
                status_counts = {}
                for order in orders:
                    status_counts[order.status] = status_counts.get(order.status, 0) + 1
                for status, count in status_counts.items():
                    span.set_attribute(f"orders.status.{status}", count)
            
            span.set_status(Status(StatusCode.OK))
            return orders
        except Exception as e:
            span.set_status(Status(StatusCode.ERROR, str(e)))
            logger.error(f"Error getting user orders: {str(e)}")
            raise HTTPException(status_code=500, detail=str(e))

@router.put("/{order_id}/status", response_model=OrderResponse)
async def update_order_status(
    order_id: int, 
    status: OrderStatus
):
    with tracer.start_as_current_span("update_order_status") as span:
        try:
            span.set_attribute("order.id", order_id)
            span.set_attribute("order.status.new", status)
            
            logger.info(f"PUT /api/orders/{order_id}/status called")
            manager = OrderManager()
            result = await manager.update_order_status(order_id, status)
            
            # Set update result in span
            if result:
                span.set_attribute("order.status.previous", result.status)
                span.set_attribute("order.user_id", result.user_id)
            
            span.set_status(Status(StatusCode.OK))
            return result
        except Exception as e:
            span.set_status(Status(StatusCode.ERROR, str(e)))
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
#     with tracer.start_as_current_span("create_test_order_saga") as span:
#         try:
#             span.set_attribute("test_order.user_id", order_data.user_id)
#             span.set_attribute("test_order.items_count", len(order_data.items))
#             
#             logger.info("Creating test order for SAGA pattern testing")
#             manager = OrderManager(db)
#             
#             # quantity validation을 우회하기 위해 직접 OrderItem 객체 생성
#             order_items = [
#                 TestOrderItemCreate(
#                     product_id=item.product_id,
#                     quantity=item.quantity
#                 ) for item in order_data.items
#             ]
            
#             # Set test order items details
#             for idx, item in enumerate(order_items):
#                 span.set_attribute(f"test_order.item_{idx}.product_id", item.product_id)
#                 span.set_attribute(f"test_order.item_{idx}.quantity", item.quantity)
            
#             # OrderCreate 객체를 수정하여 validation을 우회
#             test_order_data = OrderCreate(
#                 user_id=order_data.user_id,
#                 items=order_items
#             )
            
#             result = await manager.create_order(test_order_data)
#             if result and hasattr(result, 'order_id'):
#                 span.set_attribute("test_order.created_id", result.order_id)
            
#             span.set_status(Status(StatusCode.OK))
#             return result
#         except Exception as e:
#             span.set_status(Status(StatusCode.ERROR, str(e)))
#             logger.error(f"Error creating test order: {str(e)}")
#             raise HTTPException(status_code=500, detail=str(e))