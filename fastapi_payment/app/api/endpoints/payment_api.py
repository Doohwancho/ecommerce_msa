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
from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode

router = APIRouter()
tracer = trace.get_tracer(__name__)

# 모든 결제 조회
@router.get("/", response_model=List[PaymentResponse])
async def get_all_payments(
    db: AsyncSession = Depends(get_read_db)
):
    with tracer.start_as_current_span("get_all_payments") as span:
        try:
            payment_service = PaymentService(db)
            result = await db.execute(select(Payment))
            payments = result.scalars().all()
            
            # Set payments summary in span
            span.set_attribute("payments.count", len(payments))
            if payments:
                status_counts = {}
                for payment in payments:
                    status_counts[payment.status] = status_counts.get(payment.status, 0) + 1
                for status, count in status_counts.items():
                    span.set_attribute(f"payments.status.{status}", count)
            
            span.set_status(Status(StatusCode.OK))
            return [payment_service._convert_to_payment_response(payment) for payment in payments]
        except Exception as e:
            span.set_status(Status(StatusCode.ERROR, str(e)))
            raise HTTPException(status_code=500, detail=str(e))

@router.post("/", response_model=PaymentResponse, status_code=status.HTTP_201_CREATED)
async def create_payment(
    payment_data: PaymentCreate,
    db: AsyncSession = Depends(get_write_db)
):
    """새로운 결제 생성"""
    with tracer.start_as_current_span("create_payment") as span:
        try:
            # Set payment creation attributes
            span.set_attribute("payment.order_id", payment_data.order_id)
            span.set_attribute("payment.amount", payment_data.amount)
            span.set_attribute("payment.currency", payment_data.currency)
            span.set_attribute("payment.method", payment_data.payment_method)
            
            service = PaymentService(db)
            result = await service.create_payment(payment_data)
            
            # Set payment creation result attributes
            if result:
                span.set_attribute("payment.id", result.id)
                span.set_attribute("payment.status", result.status)
            
            span.set_status(Status(StatusCode.OK))
            return result
        except Exception as e:
            span.set_status(Status(StatusCode.ERROR, str(e)))
            raise HTTPException(status_code=500, detail=str(e))

@router.get("/{payment_id}", response_model=PaymentResponse)
async def get_payment(
    payment_id: int,
    db: AsyncSession = Depends(get_read_db)
):
    """결제 ID로 결제 조회"""
    with tracer.start_as_current_span("get_payment") as span:
        try:
            span.set_attribute("payment.id", payment_id)
            
            service = PaymentService(db)
            payment = await service.get_payment(payment_id)
            
            if not payment:
                span.set_status(Status(StatusCode.ERROR, f"Payment {payment_id} not found"))
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Payment {payment_id} not found"
                )
            
            # Set payment details in span
            span.set_attribute("payment.order_id", payment.order_id)
            span.set_attribute("payment.status", payment.status)
            span.set_attribute("payment.amount", payment.amount)
            
            span.set_status(Status(StatusCode.OK))
            return payment
        except HTTPException:
            raise
        except Exception as e:
            span.set_status(Status(StatusCode.ERROR, str(e)))
            raise HTTPException(status_code=500, detail=str(e))

@router.put("/{payment_id}", response_model=PaymentResponse)
async def update_payment(
    payment_id: int,
    payment_update: PaymentUpdate,
    db: AsyncSession = Depends(get_write_db)
):
    """결제 상태 업데이트"""
    with tracer.start_as_current_span("update_payment") as span:
        try:
            span.set_attribute("payment.id", payment_id)
            span.set_attribute("payment.status.new", payment_update.status)
            
            service = PaymentService(db)
            payment = await service.update_payment(payment_id, payment_update)
            
            if not payment:
                span.set_status(Status(StatusCode.ERROR, f"Payment {payment_id} not found"))
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Payment {payment_id} not found"
                )
            
            # Set update result in span
            span.set_attribute("payment.status.previous", payment.status)
            span.set_attribute("payment.order_id", payment.order_id)
            
            span.set_status(Status(StatusCode.OK))
            return payment
        except HTTPException:
            raise
        except Exception as e:
            span.set_status(Status(StatusCode.ERROR, str(e)))
            raise HTTPException(status_code=500, detail=str(e))

@router.post("/{payment_id}/transactions", response_model=TransactionResponse, status_code=status.HTTP_201_CREATED)
async def create_transaction(
    payment_id: int,
    transaction_data: TransactionCreate,
    db: AsyncSession = Depends(get_write_db)
):
    """결제 트랜잭션 생성"""
    with tracer.start_as_current_span("create_transaction") as span:
        try:
            span.set_attribute("payment.id", payment_id)
            span.set_attribute("transaction.type", transaction_data.transaction_type)
            span.set_attribute("transaction.amount", transaction_data.amount)
            
            service = PaymentService(db)
            result = await service.create_transaction(transaction_data)
            
            # Set transaction creation result attributes
            if result:
                span.set_attribute("transaction.id", result.id)
                span.set_attribute("transaction.status", result.status)
            
            span.set_status(Status(StatusCode.OK))
            return result
        except Exception as e:
            span.set_status(Status(StatusCode.ERROR, str(e)))
            raise HTTPException(status_code=500, detail=str(e))

@router.get("/{payment_id}/transactions", response_model=List[TransactionResponse])
async def get_payment_transactions(
    payment_id: int,
    db: AsyncSession = Depends(get_read_db)
):
    """결제의 모든 트랜잭션 조회"""
    with tracer.start_as_current_span("get_payment_transactions") as span:
        try:
            span.set_attribute("payment.id", payment_id)
            
            service = PaymentService(db)
            transactions = await service.get_payment_transactions(payment_id)
            
            # Set transactions summary in span
            span.set_attribute("transactions.count", len(transactions))
            if transactions:
                type_counts = {}
                for transaction in transactions:
                    type_counts[transaction.transaction_type] = type_counts.get(transaction.transaction_type, 0) + 1
                for type_, count in type_counts.items():
                    span.set_attribute(f"transactions.type.{type_}", count)
            
            span.set_status(Status(StatusCode.OK))
            return transactions
        except Exception as e:
            span.set_status(Status(StatusCode.ERROR, str(e)))
            raise HTTPException(status_code=500, detail=str(e))

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
    with tracer.start_as_current_span("process_payment") as span:
        try:
            # Set payment processing attributes
            span.set_attribute("payment.order_id", order_id)
            span.set_attribute("payment.amount", amount)
            span.set_attribute("payment.method", payment_method)
            span.set_attribute("payment.gateway", payment_gateway)
            
            service = PaymentService(db)
            result = await service.process_payment(
                order_id=order_id,
                amount=amount,
                payment_method=payment_method,
                payment_gateway=payment_gateway,
                payment_data=payment_data
            )
            
            # Set payment processing result attributes
            if result:
                span.set_attribute("payment.id", result.id)
                span.set_attribute("payment.status", result.status)
                span.set_attribute("transactions.count", len(result.transactions))
            
            span.set_status(Status(StatusCode.OK))
            return result
        except Exception as e:
            span.set_status(Status(StatusCode.ERROR, str(e)))
            raise HTTPException(status_code=500, detail=str(e))