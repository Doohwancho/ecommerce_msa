from fastapi import APIRouter
from app.api.endpoints import payment_api

api_router = APIRouter()
api_router.include_router(payment_api.router, prefix="/payments", tags=["payments"])