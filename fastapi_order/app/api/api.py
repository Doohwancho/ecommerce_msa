from fastapi import APIRouter
from app.api.endpoints import orders
import logging

# 로깅 설정
logger = logging.getLogger(__name__)

api_router = APIRouter()
api_router.include_router(orders.router, prefix="/orders", tags=["orders"])