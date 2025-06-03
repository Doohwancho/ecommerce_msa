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
import logging

router = APIRouter()
logger = logging.getLogger(__name__)
tracer = trace.get_tracer(__name__)

# 모든 결제 조회
@router.get("/", response_model=List[PaymentResponse])
async def get_all_payments(
    db: AsyncSession = Depends(get_read_db)
):
    logger.info("Attempting to get all payments.")
    with tracer.start_as_current_span("endpoint.get_all_payments") as span:
        try:
            payment_service = PaymentService(db)
            result = await db.execute(select(Payment).order_by(Payment.created_at.desc()))
            payments = result.scalars().all()
            
            payment_count = len(payments)
            span.set_attribute("payments.count", payment_count)
            if payments:
                status_counts_log = {}
                for p_item in payments:
                    status_counts_log[p_item.status] = status_counts_log.get(p_item.status, 0) + 1
                for s_key, s_count in status_counts_log.items():
                    span.set_attribute(f"payments.status.{s_key}", s_count)
            
            logger.info("Successfully retrieved all payments.", extra={"count": payment_count, "status_counts": status_counts_log})
            span.set_status(Status(StatusCode.OK))
            return [payment_service._convert_to_payment_response(p) for p in payments]
        except Exception as e:
            logger.error("Error getting all payments.", extra={"error": str(e)}, exc_info=True)
            span.set_status(Status(StatusCode.ERROR, str(e)))
            span.record_exception(e)
            raise HTTPException(status_code=500, detail=f"Failed to retrieve payments: {str(e)}")

@router.post("/", response_model=PaymentResponse, status_code=status.HTTP_201_CREATED)
async def create_payment(
    payment_data: PaymentCreate,
    db: AsyncSession = Depends(get_write_db)
):
    """새로운 결제 생성"""
    log_extra = {
        "order_id": payment_data.order_id,
        "amount": payment_data.amount,
        "currency": payment_data.currency,
        "method": payment_data.payment_method.value
    }
    logger.info("Attempting to create payment.", extra=log_extra)
    with tracer.start_as_current_span("endpoint.create_payment") as span:
        try:
            span.set_attribute("payment.order_id", payment_data.order_id)
            span.set_attribute("payment.amount", payment_data.amount)
            span.set_attribute("payment.currency", payment_data.currency)
            span.set_attribute("payment.method", payment_data.payment_method.value)
            
            service = PaymentService(session=db)
            created_payment = await service.create_payment(payment_data)
            
            if created_payment:
                span.set_attribute("payment.id", str(created_payment.id))
                span.set_attribute("payment.status", created_payment.status)
                log_extra["payment_id"] = str(created_payment.id)
                log_extra["payment_status"] = created_payment.status
            
            logger.info("Successfully created payment.", extra=log_extra)
            span.set_status(Status(StatusCode.OK))
            return created_payment
        except HTTPException as he:
            logger.warning("HTTPException during payment creation.", extra=dict(log_extra, status_code=he.status_code, detail=he.detail))
            span.set_status(Status(StatusCode.ERROR, he.detail))
            span.record_exception(he)
            raise
        except Exception as e:
            logger.error("Error creating payment.", extra=dict(log_extra, error=str(e)), exc_info=True)
            span.set_status(Status(StatusCode.ERROR, str(e)))
            span.record_exception(e)
            raise HTTPException(status_code=500, detail=f"An unexpected error occurred: {str(e)}")

@router.get("/{payment_id}", response_model=PaymentResponse)
async def get_payment(
    payment_id: int,
    db: AsyncSession = Depends(get_read_db)
):
    """결제 ID로 결제 조회"""
    logger.info("Attempting to get payment by ID.", extra={"payment_id": payment_id})
    with tracer.start_as_current_span("endpoint.get_payment_by_id") as span:
        try:
            span.set_attribute("payment.id", payment_id)
            
            service = PaymentService(session=db)
            payment = await service.get_payment(payment_id)
            
            if not payment:
                logger.warning("Payment not found by ID.", extra={"payment_id": payment_id})
                span.set_status(Status(StatusCode.ERROR, f"Payment {payment_id} not found"))
                not_found_exc = HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Payment {payment_id} not found")
                setattr(not_found_exc, "_otel_recorded_for_404", True)
                span.record_exception(not_found_exc)
                raise not_found_exc
            
            log_extra_success = {
                "payment_id": payment.id,
                "order_id": payment.order_id,
                "status": payment.status,
                "amount": payment.amount
            }
            span.set_attribute("payment.order_id", payment.order_id)
            span.set_attribute("payment.status", payment.status)
            span.set_attribute("payment.amount", payment.amount)
            
            logger.info("Successfully retrieved payment by ID.", extra=log_extra_success)
            span.set_status(Status(StatusCode.OK))
            return payment
        except HTTPException as he_raised:
            if not getattr(he_raised, "_otel_recorded_for_404", False):
                logger.warning("HTTPException while getting payment by ID.", extra={"payment_id": payment_id, "status_code": he_raised.status_code, "detail": he_raised.detail})
                if span.status.status_code != StatusCode.ERROR:
                    span.set_status(Status(StatusCode.ERROR, he_raised.detail))
                span.record_exception(he_raised)
            raise
        except Exception as e:
            logger.error("Error getting payment by ID.", extra={"payment_id": payment_id, "error": str(e)}, exc_info=True)
            span.set_status(Status(StatusCode.ERROR, str(e)))
            span.record_exception(e)
            raise HTTPException(status_code=500, detail=f"An unexpected error occurred: {str(e)}")

@router.put("/{payment_id}", response_model=PaymentResponse)
async def update_payment(
    payment_id: int,
    payment_update: PaymentUpdate,
    db: AsyncSession = Depends(get_write_db)
):
    """결제 상태 업데이트"""
    log_extra = {"payment_id": payment_id, "update_payload": payment_update.dict(exclude_unset=True)}
    logger.info("Attempting to update payment.", extra=log_extra)
    with tracer.start_as_current_span("endpoint.update_payment") as span:
        try:
            span.set_attribute("payment.id", payment_id)
            if payment_update.status:
                span.set_attribute("payment.status.new", payment_update.status)
            
            service = PaymentService(session=db)
            updated_payment = await service.update_payment(payment_id, payment_update)
            
            if not updated_payment:
                logger.warning("Payment not found for update.", extra=log_extra)
                span.set_status(Status(StatusCode.ERROR, f"Payment {payment_id} not found for update"))
                not_found_exc = HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Payment {payment_id} not found")
                setattr(not_found_exc, "_otel_recorded_for_404", True)
                span.record_exception(not_found_exc)
                raise not_found_exc
            
            log_extra_success = {
                "payment_id": updated_payment.id,
                "order_id": updated_payment.order_id,
                "new_status": updated_payment.status
            }
            span.set_attribute("payment.status.current", updated_payment.status)
            span.set_attribute("payment.order_id", updated_payment.order_id)
            
            logger.info("Successfully updated payment.", extra=log_extra_success)
            span.set_status(Status(StatusCode.OK))
            return updated_payment
        except HTTPException as he_raised:
            if not getattr(he_raised, "_otel_recorded_for_404", False):
                logger.warning("HTTPException while updating payment.", extra=dict(log_extra, status_code=he_raised.status_code, detail=he_raised.detail))
                if span.status.status_code != StatusCode.ERROR:
                    span.set_status(Status(StatusCode.ERROR, he_raised.detail))
                span.record_exception(he_raised)
            raise
        except Exception as e:
            logger.error("Error updating payment.", extra=dict(log_extra, error=str(e)), exc_info=True)
            span.set_status(Status(StatusCode.ERROR, str(e)))
            span.record_exception(e)
            raise HTTPException(status_code=500, detail=f"An unexpected error occurred: {str(e)}")

@router.post("/{payment_id}/transactions", response_model=TransactionResponse, status_code=status.HTTP_201_CREATED)
async def create_transaction(
    payment_id: int,
    transaction_data: TransactionCreate,
    db: AsyncSession = Depends(get_write_db)
):
    """결제 트랜잭션 생성"""
    if transaction_data.payment_id != payment_id:
        logger.warning("Path payment_id and payload payment_id mismatch.", extra={"path_payment_id": payment_id, "payload_payment_id": transaction_data.payment_id})
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Path payment_id and payload payment_id mismatch")

    log_extra = {
        "payment_id": payment_id,
        "transaction_type": transaction_data.transaction_type,
        "amount": transaction_data.amount
    }
    logger.info("Attempting to create transaction for payment.", extra=log_extra)
    with tracer.start_as_current_span("endpoint.create_transaction_for_payment") as span:
        try:
            span.set_attribute("payment.id", payment_id)
            span.set_attribute("transaction.type", transaction_data.transaction_type)
            span.set_attribute("transaction.amount", transaction_data.amount)
            
            service = PaymentService(session=db)
            created_transaction = await service.create_transaction(transaction_data)
            
            if created_transaction:
                span.set_attribute("transaction.id", str(created_transaction.id))
                span.set_attribute("transaction.status", created_transaction.status)
                log_extra["transaction_id"] = str(created_transaction.id)
                log_extra["transaction_status"] = created_transaction.status

            logger.info("Successfully created transaction for payment.", extra=log_extra)
            span.set_status(Status(StatusCode.OK))
            return created_transaction
        except HTTPException as he:
            logger.warning("HTTPException during transaction creation.", extra=dict(log_extra, status_code=he.status_code, detail=he.detail))
            span.set_status(Status(StatusCode.ERROR, he.detail))
            span.record_exception(he)
            raise
        except Exception as e:
            logger.error("Error creating transaction.", extra=dict(log_extra, error=str(e)), exc_info=True)
            span.set_status(Status(StatusCode.ERROR, str(e)))
            span.record_exception(e)
            raise HTTPException(status_code=500, detail=f"An unexpected error occurred: {str(e)}")

@router.get("/{payment_id}/transactions", response_model=List[TransactionResponse])
async def get_payment_transactions(
    payment_id: int,
    db: AsyncSession = Depends(get_read_db)
):
    """결제의 모든 트랜잭션 조회"""
    logger.info("Attempting to get transactions for payment.", extra={"payment_id": payment_id})
    with tracer.start_as_current_span("endpoint.get_payment_transactions") as span:
        try:
            span.set_attribute("payment.id", payment_id)
            
            service = PaymentService(session=db)
            transactions = await service.get_payment_transactions(payment_id)
            
            transaction_count = len(transactions)
            span.set_attribute("transactions.count", transaction_count)
            if transactions:
                type_counts_log = {}
                for t_item in transactions:
                    type_counts_log[t_item.transaction_type] = type_counts_log.get(t_item.transaction_type, 0) + 1
                for t_key, t_count in type_counts_log.items():
                    span.set_attribute(f"transactions.type.{t_key}", t_count)
            
            logger.info("Successfully retrieved transactions for payment.", extra={"payment_id": payment_id, "count": transaction_count, "type_counts": type_counts_log})
            span.set_status(Status(StatusCode.OK))
            return transactions
        except Exception as e:
            logger.error("Error getting transactions for payment.", extra={"payment_id": payment_id, "error": str(e)}, exc_info=True)
            span.set_status(Status(StatusCode.ERROR, str(e)))
            span.record_exception(e)
            raise HTTPException(status_code=500, detail=f"An unexpected error occurred: {str(e)}")

@router.post("/process", response_model=PaymentWithTransactions, status_code=status.HTTP_201_CREATED)
async def process_payment(
    order_id: str,
    amount: float,
    payment_method: PaymentMethod,
    payment_gateway: str,
    payment_data_for_pg: dict,
    db: AsyncSession = Depends(get_write_db)
):
    """결제 처리 프로세스"""
    log_extra = {
        "order_id": order_id,
        "amount": amount,
        "method": payment_method.value,
        "gateway": payment_gateway,
        "pg_data_preview": str(payment_data_for_pg)[:100]
    }
    logger.info("Attempting to process payment.", extra=log_extra)
    with tracer.start_as_current_span("endpoint.process_payment") as span:
        try:
            span.set_attribute("payment.order_id", order_id)
            span.set_attribute("payment.amount", amount)
            span.set_attribute("payment.method", payment_method.value)
            span.set_attribute("payment.gateway", payment_gateway)
            
            service = PaymentService(session=db)
            result = await service.process_payment(
                order_id=order_id,
                amount=amount,
                payment_method=payment_method,
                payment_gateway=payment_gateway,
                payment_data_for_pg=payment_data_for_pg
            )
            
            if result:
                span.set_attribute("payment.id", str(result.id))
                span.set_attribute("payment.status", result.status)
                span.set_attribute("transactions.count", len(result.transactions))
                log_extra["payment_id"] = str(result.id)
                log_extra["final_status"] = result.status
                log_extra["transaction_count"] = len(result.transactions)

            logger.info("Successfully processed payment.", extra=log_extra)
            span.set_status(Status(StatusCode.OK))
            return result
        except HTTPException as he:
            logger.warning("HTTPException during payment processing.", extra=dict(log_extra, status_code=he.status_code, detail=he.detail))
            span.set_status(Status(StatusCode.ERROR, he.detail))
            span.record_exception(he)
            raise
        except Exception as e:
            logger.error("Error processing payment.", extra=dict(log_extra, error=str(e)), exc_info=True)
            span.set_status(Status(StatusCode.ERROR, str(e)))
            span.record_exception(e)
            raise HTTPException(status_code=500, detail=f"An unexpected error occurred: {str(e)}")