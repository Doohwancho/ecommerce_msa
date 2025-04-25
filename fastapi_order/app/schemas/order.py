from pydantic import BaseModel, Field
from typing import List, Optional
import datetime
from app.models.order import OrderStatus

class OrderItemCreate(BaseModel):
    product_id: str
    quantity: int

class OrderCreate(BaseModel):
    user_id: str
    items: List[OrderItemCreate]

class OrderUpdate(BaseModel):
    status: OrderStatus

class OrderCreateResponse(BaseModel):
    order_id: int
    status: str
    message: str

class OrderItemResponse(BaseModel):
    order_item_id: int
    product_id: str
    quantity: int
    price_at_order: float
    created_at: datetime.datetime

    class Config:
        orm_mode = True

class OrderResponse(BaseModel):
    order_id: int
    user_id: str
    status: OrderStatus
    total_amount: float
    created_at: datetime.datetime
    updated_at: datetime.datetime
    items: List[OrderItemResponse]

    class Config:
        orm_mode = True

# SAGA 테스트를 위한 모델
class TestOrderItemCreate(BaseModel):
    product_id: str
    quantity: int  # validation 없음

class TestOrderCreate(BaseModel):
    user_id: str
    items: List[TestOrderItemCreate] 