# fastapi_payment/app/api/endpoints/payment_api.py
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from app.config.payment_database import get_write_db, get_read_db
from app.services.payment_service import PaymentService
from app.models.payment_model import Payment
from app.schemas.payment_schemas import (
    PaymentCreate, PaymentUpdate, PaymentResponse,
    TransactionCreate, TransactionResponse,
    PaymentWithTransactions, PaymentMethod
)
from sqlalchemy import select

router = APIRouter()


# 모든 결제 조회
@router.get("/", response_model=List[PaymentResponse])
async def get_all_payments(
    db: AsyncSession = Depends(get_read_db)
):
    try:
        payment_service = PaymentService(db)
        result = await db.execute(select(Payment))
        payments = result.scalars().all()
        return [payment_service._convert_to_payment_response(payment) for payment in payments]
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/", response_model=PaymentResponse, status_code=status.HTTP_201_CREATED)
async def create_payment(
    payment_data: PaymentCreate,
    db: AsyncSession = Depends(get_write_db)
):
    """새로운 결제 생성"""
    service = PaymentService(db)
    return await service.create_payment(payment_data)



@router.get("/{payment_id}", response_model=PaymentResponse)
async def get_payment(
    payment_id: int,
    db: AsyncSession = Depends(get_read_db)
):
    """결제 ID로 결제 조회"""
    service = PaymentService(db)
    payment = await service.get_payment(payment_id)
    if not payment:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Payment {payment_id} not found"
        )
    return payment

@router.put("/{payment_id}", response_model=PaymentResponse)
async def update_payment(
    payment_id: int,
    payment_update: PaymentUpdate,
    db: AsyncSession = Depends(get_write_db)
):
    """결제 상태 업데이트"""
    service = PaymentService(db)
    payment = await service.update_payment(payment_id, payment_update)
    if not payment:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Payment {payment_id} not found"
        )
    return payment

@router.post("/{payment_id}/transactions", response_model=TransactionResponse, status_code=status.HTTP_201_CREATED)
async def create_transaction(
    payment_id: int,
    transaction_data: TransactionCreate,
    db: AsyncSession = Depends(get_write_db)
):
    """결제 트랜잭션 생성"""
    service = PaymentService(db)
    return await service.create_transaction(transaction_data)

@router.get("/{payment_id}/transactions", response_model=List[TransactionResponse])
async def get_payment_transactions(
    payment_id: int,
    db: AsyncSession = Depends(get_read_db)
):
    """결제의 모든 트랜잭션 조회"""
    service = PaymentService(db)
    return await service.get_payment_transactions(payment_id)

@router.post("/process", response_model=PaymentWithTransactions, status_code=status.HTTP_201_CREATED)
async def process_payment(
    order_id: str,
    amount: float,
    payment_method: PaymentMethod,
    payment_gateway: str,
    payment_data: dict,
    db: AsyncSession = Depends(get_write_db)
):
    """결제 처리 프로세스"""
    service = PaymentService(db)
    return await service.process_payment(
        order_id=order_id,
        amount=amount,
        payment_method=payment_method,
        payment_gateway=payment_gateway,
        payment_data=payment_data
    )