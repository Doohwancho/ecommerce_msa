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

async def get_order_manager() -> OrderManager:
    """OrderManager 인스턴스를 생성하고 반환하는 의존성 함수"""
    return OrderManager()

@router.post("/", response_model=OrderCreateResponse)
async def create_order(
    order: OrderCreate,
    order_manager: OrderManager = Depends(get_order_manager)
):
    with tracer.start_as_current_span("create_order") as span:
        try:
            span.set_attribute("order.user_id", order.user_id)
            span.set_attribute("order.items_count", len(order.items))
            
            for idx, item in enumerate(order.items):
                span.set_attribute(f"order.item_{idx}.product_id", item.product_id)
                span.set_attribute(f"order.item_{idx}.quantity", item.quantity)
            
            result = await order_manager.create_order(order)
            
            if result and hasattr(result, 'order_id'):
                span.set_attribute("order.created_id", result.order_id)
                logger.info("Order created successfully", extra={
                    "order_id": result.order_id,
                    "user_id": order.user_id,
                    "items_count": len(order.items)
                })
            
            span.set_status(Status(StatusCode.OK))
            return result
        except Exception as e:
            logger.error("Error creating order", extra={
                "user_id": order.user_id,
                "error": str(e)
            }, exc_info=True)
            span.set_status(Status(StatusCode.ERROR, str(e)))
            raise HTTPException(status_code=400, detail=str(e))

@router.get("/{order_id}", response_model=OrderResponse)
async def get_order(
    order_id: int
):
    with tracer.start_as_current_span("get_order") as span:
        try:
            span.set_attribute("order.id", order_id)
            manager = OrderManager()
            result = await manager.get_order(order_id)
            
            if result:
                span.set_attribute("order.status", result.status)
                span.set_attribute("order.user_id", result.user_id)
                span.set_attribute("order.items_count", len(result.items))
                logger.info("Order retrieved successfully", extra={
                    "order_id": order_id,
                    "status": result.status,
                    "user_id": result.user_id,
                    "items_count": len(result.items)
                })
            else:
                logger.warning("Order not found", extra={"order_id": order_id})
            
            span.set_status(Status(StatusCode.OK))
            return result
        except HTTPException:
            raise
        except Exception as e:
            logger.error("Error getting order", extra={
                "order_id": order_id,
                "error": str(e)
            }, exc_info=True)
            span.set_status(Status(StatusCode.ERROR, str(e)))
            raise HTTPException(status_code=500, detail=str(e))

@router.get("/user/{user_id}", response_model=List[OrderResponse])
async def get_user_orders(
    user_id: str
):
    with tracer.start_as_current_span("get_user_orders") as span:
        try:
            span.set_attribute("user.id", user_id)
            manager = OrderManager()
            orders = await manager.get_user_orders(user_id)
            
            span.set_attribute("orders.count", len(orders))
            if orders:
                status_counts = {}
                for order in orders:
                    status_counts[order.status] = status_counts.get(order.status, 0) + 1
                for status, count in status_counts.items():
                    span.set_attribute(f"orders.status.{status}", count)
                
                logger.info("User orders retrieved successfully", extra={
                    "user_id": user_id,
                    "total_orders": len(orders),
                    "status_counts": status_counts
                })
            else:
                logger.info("No orders found for user", extra={"user_id": user_id})
            
            span.set_status(Status(StatusCode.OK))
            return orders
        except Exception as e:
            logger.error("Error getting user orders", extra={
                "user_id": user_id,
                "error": str(e)
            }, exc_info=True)
            span.set_status(Status(StatusCode.ERROR, str(e)))
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
            
            manager = OrderManager()
            result = await manager.update_order_status(order_id, status)
            
            if result:
                span.set_attribute("order.status.previous", result.status)
                span.set_attribute("order.user_id", result.user_id)
                logger.info("Order status updated successfully", extra={
                    "order_id": order_id,
                    "previous_status": result.status,
                    "new_status": status,
                    "user_id": result.user_id
                })
            
            span.set_status(Status(StatusCode.OK))
            return result
        except Exception as e:
            logger.error("Error updating order status", extra={
                "order_id": order_id,
                "new_status": status,
                "error": str(e)
            }, exc_info=True)
            span.set_status(Status(StatusCode.ERROR, str(e)))
            raise HTTPException(status_code=500, detail=str(e))