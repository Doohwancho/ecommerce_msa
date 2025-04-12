from pydantic import BaseModel, Field
from typing import List, Optional
import datetime
from app.models.order import OrderStatus

class OrderItemCreate(BaseModel):
    product_id: str
    quantity: int = Field(gt=0)

class OrderCreate(BaseModel):
    user_id: str
    items: List[OrderItemCreate]

class OrderUpdate(BaseModel):
    status: OrderStatus

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