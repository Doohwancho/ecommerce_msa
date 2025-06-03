# fastapi_payment/app/services/payment_service.py
from typing import List, Optional, Dict, Any
from datetime import datetime
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update
from fastapi import HTTPException
import json
import logging

# OpenTelemetry API 임포트
from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode, SpanKind
from opentelemetry.semconv.trace import SpanAttributes
from opentelemetry import propagate

from app.schemas.payment_schemas import (
    PaymentBase, PaymentCreate, PaymentUpdate, PaymentResponse,
    TransactionBase, TransactionCreate, TransactionResponse,
    PaymentStatus, PaymentMethod, PaymentWithTransactions
)
from app.models.payment_model import Payment, PaymentTransaction
from app.config.payment_database import WriteSessionLocal, ReadSessionLocal
import uuid
from app.models.outbox import Outbox

logger = logging.getLogger(__name__)
tracer = trace.get_tracer(__name__, "0.1.0")

class PaymentService:
    def __init__(self, session: Optional[AsyncSession] = None):
        self.write_db_session: Optional[AsyncSession] = session
        self.read_db_session: Optional[AsyncSession] = session
        logger.debug("PaymentService instance created.")

    async def _get_write_db(self) -> AsyncSession:
        if self.write_db_session is None:
            logger.info("Creating new write DB session as it was None.")
            self.write_db_session = WriteSessionLocal()
            if self.write_db_session is None:
                logger.error("Failed to create write DB session from factory.")
                raise ConnectionError("Failed to obtain a write database session.")
        return self.write_db_session

    async def _get_read_db(self) -> AsyncSession:
        if self.read_db_session is None:
            logger.info("Creating new read DB session as it was None.")
            self.read_db_session = ReadSessionLocal()
            if self.read_db_session is None:
                logger.error("Failed to create read DB session from factory.")
                raise ConnectionError("Failed to obtain a read database session.")
        return self.read_db_session

    def _convert_to_payment_response(self, payment: Payment) -> PaymentResponse:
        return PaymentResponse(
            payment_id=payment.payment_id,
            order_id=payment.order_id,
            amount=payment.amount,
            currency=payment.currency,
            payment_method=PaymentMethod(payment.payment_method.value),
            payment_status=PaymentStatus(payment.payment_status.value),
            created_at=payment.created_at,
            updated_at=payment.updated_at
        )

    async def get_all_payments(self) -> List[PaymentResponse]:
        with tracer.start_as_current_span("PaymentService.get_all_payments") as span:
            logger.info("Fetching all payments.")
            try:
                db = await self._get_read_db()
                result = await db.execute(select(Payment).order_by(Payment.created_at.desc()))
                payments = result.scalars().all()
                
                payment_count = len(payments)
                span.set_attribute("app.payments.count", payment_count)
                logger.info("Successfully fetched payments.", extra={"count": payment_count})
                span.set_status(Status(StatusCode.OK))
                return [self._convert_to_payment_response(p) for p in payments]
            except Exception as e:
                logger.error("Error getting all payments.", extra={"error": str(e)}, exc_info=True)
                span.record_exception(e)
                span.set_status(Status(StatusCode.ERROR, "FailedToGetAllPayments"))
                raise HTTPException(status_code=500, detail=f"Failed to retrieve payments: {str(e)}")

    async def create_payment(self, payment_data: PaymentCreate) -> PaymentResponse:
        """새로운 결제를 생성하고 Outbox 이벤트를 기록합니다. (기존 코드 스타일 최대한 반영)"""
        tracer = trace.get_tracer(__name__, "0.1.0") # 메소드 내에서 tracer 가져오기 (기존 코드 방식)
        current_service_entry_span = trace.get_current_span()

        if current_service_entry_span and current_service_entry_span.is_recording():
            ctx = current_service_entry_span.get_span_context()
            parent_span_id_hex = current_service_entry_span.parent.span_id if current_service_entry_span.parent else None
            parent_span_id_str = f"{parent_span_id_hex:x}" if parent_span_id_hex else "None"
            logger.info(
                "PaymentService.create_payment: ENTRY",
                extra={
                    "trace_id": f"{ctx.trace_id:x}",
                    "span_id": f"{ctx.span_id:x}",
                    "parent_span_id": parent_span_id_str,
                    "is_remote": ctx.is_remote,
                    "order_id": payment_data.order_id
                }
            )
        else:
            logger.warning("PaymentService.create_payment: No active/recording span at service entry.", extra={"order_id": payment_data.order_id})

        # 스팬 이름을 "PaymentService.create_payment"으로 변경 (기존 코드 방식)
        with tracer.start_as_current_span("PaymentService.create_payment") as span:
            span.set_attribute("app.order_id", payment_data.order_id)
            span.set_attribute("app.payment.amount", payment_data.amount)
            span.set_attribute("app.payment.currency", payment_data.currency)
            span.set_attribute("app.payment.method", payment_data.payment_method.value)
            # 로깅 포맷을 기존 코드와 유사하게
            logger.info(f"Attempting to create payment for order_id: {payment_data.order_id}", 
                        extra={ # 구조화된 로깅용 extra는 유지
                            "order_id": payment_data.order_id, 
                            "amount": payment_data.amount,
                            "currency": payment_data.currency,
                            "method": payment_data.payment_method.value
                        })

            try:
                # SAGA 테스트용 실패 시뮬레이션 (기존 코드 로직 유지)
                if round(payment_data.amount) == 35000: 
                    sim_error_msg = "Simulated payment failure for SAGA (order_amount = 35000)" # 금액은 기존 코드와 맞춤
                    logger.warning(sim_error_msg, extra={"order_id": payment_data.order_id, "amount": payment_data.amount}) # extra 추가
                    span.set_attribute("app.payment.simulated_failure", True)
                    span.set_attribute("app.payment.simulated_failure_reason", sim_error_msg)
                    raise Exception(sim_error_msg)

                db_session = await self._get_write_db()
                async with db_session.begin():
                    span.add_event("DatabaseTransactionStartedForPayment")
                    payment = Payment(
                        order_id=payment_data.order_id,
                        amount=payment_data.amount,
                        currency=payment_data.currency,
                        payment_method=payment_data.payment_method,
                        payment_status=PaymentStatus.PENDING
                    )
                    db_session.add(payment)
                    await db_session.flush()
                    
                    span.set_attribute("app.payment_id", str(payment.payment_id))
                    logger.debug("Payment record created in DB.", extra={"payment_id": str(payment.payment_id), "order_id": payment.order_id})
                    span.add_event("PaymentRecordCreatedInDB", {"payment.id": str(payment.payment_id)})

                    payment_event_payload = {
                        'type': "payment_success",
                        'payment_id': str(payment.payment_id),
                        'order_id': payment.order_id,
                        'amount': payment.amount,
                        'currency': payment.currency,
                        'payment_method': payment.payment_method.value,
                        'payment_status': PaymentStatus.PENDING.value,
                        'created_at': datetime.utcnow().isoformat()
                    }

                    current_otel_span = trace.get_current_span()
                    context_to_propagate = trace.set_span_in_context(current_otel_span)
                    carrier = {}
                    propagator = propagate.get_global_textmap()
                    propagator.inject(carrier, context=context_to_propagate)

                    logger.debug("Trace context injected for Outbox.", extra={"payment_id": str(payment.payment_id), "traceparent": carrier.get('traceparent')})
                    span.add_event("TraceContextInjectedToCarrierForOutbox", 
                               {"traceparent": carrier.get('traceparent'), "tracestate": carrier.get('tracestate')})

                    outbox_event = Outbox(
                        id=str(uuid.uuid4()),
                        aggregatetype="payment",
                        aggregateid=str(payment.payment_id),
                        type="payment_success",
                        payload=payment_event_payload,
                        traceparent_for_header=carrier.get('traceparent'),
                        tracestate_for_header=carrier.get('tracestate')
                    )
                    db_session.add(outbox_event)
                    logger.debug("Outbox event prepared for payment.", extra={"payment_id": str(payment.payment_id), "event_type": "payment_success"})
                    span.add_event("OutboxEventPreparedForPayment", {"outbox.event.type": "payment_success"})
                    
                span.add_event("DatabaseTransactionCommittedForPayment")
                
                logger.info("Payment created successfully.", 
                            extra={"payment_id": str(payment.payment_id), "order_id": payment.order_id})
                span.set_status(Status(StatusCode.OK))
                return self._convert_to_payment_response(payment)

            except Exception as e:
                logger.error("Error creating payment.", 
                             extra={"order_id": payment_data.order_id, "error": str(e)}, 
                             exc_info=True)
                span.record_exception(e)
                span.set_status(Status(StatusCode.ERROR, "FailedToCreatePayment"))
                raise HTTPException(status_code=500, detail=f"Error creating payment for order {payment_data.order_id}: {str(e)}")

    async def get_payment(self, payment_id: int) -> Optional[PaymentResponse]:
        with tracer.start_as_current_span("PaymentService.get_payment") as span:
            span.set_attribute("app.payment_id", payment_id)
            logger.info("Fetching payment.", extra={"payment_id": payment_id})
            try:
                db = await self._get_read_db()
                payment = await db.get(Payment, payment_id)

                if payment:
                    logger.info("Payment found.", 
                                extra={"payment_id": payment_id, "status": payment.payment_status.value})
                    span.set_attribute("app.payment.found", True)
                    span.set_attribute("app.payment.status", payment.payment_status.value)
                    span.set_status(Status(StatusCode.OK))
                    return self._convert_to_payment_response(payment)
                else:
                    logger.warning("Payment not found.", extra={"payment_id": payment_id})
                    span.set_attribute("app.payment.found", False)
                    span.set_status(Status(StatusCode.OK, "PaymentNotFound"))
                    return None
            except Exception as e:
                logger.error("Error getting payment.", 
                             extra={"payment_id": payment_id, "error": str(e)}, 
                             exc_info=True)
                span.record_exception(e)
                span.set_status(Status(StatusCode.ERROR, "FailedToGetPayment"))
                raise HTTPException(status_code=500, detail=f"Failed to retrieve payment {payment_id}: {str(e)}")

    async def update_payment(self, payment_id: int, payment_update: PaymentUpdate) -> Optional[PaymentResponse]:
        with tracer.start_as_current_span("PaymentService.update_payment") as span:
            span.set_attribute("app.payment_id", payment_id)
            update_payload_dict = payment_update.dict(exclude_unset=True)
            if payment_update.payment_status:
                span.set_attribute("app.payment.new_status", payment_update.payment_status.value)
            
            logger.info("Attempting to update payment.", 
                        extra={"payment_id": payment_id, "update_data": update_payload_dict})
            
            db_session = await self._get_write_db()
            try:
                async with db_session.begin():
                    span.add_event("DatabaseTransactionStartedForUpdate")
                    payment_to_update = await db_session.get(Payment, payment_id)

                    if not payment_to_update:
                        logger.warning("Payment not found for update.", extra={"payment_id": payment_id})
                        span.set_attribute("app.payment.found", False)
                        span.set_status(Status(StatusCode.OK, "PaymentNotFoundForUpdate"))
                        return None
                    
                    logger.debug("Payment found for update.", 
                                 extra={"payment_id": payment_id, "old_status": payment_to_update.payment_status.value})
                    span.set_attribute("app.payment.found", True)
                    span.set_attribute("app.payment.old_status", payment_to_update.payment_status.value)

                    for field, value in update_payload_dict.items():
                        setattr(payment_to_update, field, value)
                    
                    payment_to_update.updated_at = datetime.utcnow()
                span.add_event("DatabaseTransactionCommittedForUpdate")

                await db_session.refresh(payment_to_update)
                
                logger.info("Payment updated successfully.", 
                            extra={"payment_id": payment_id, "new_status": payment_to_update.payment_status.value})
                span.set_status(Status(StatusCode.OK))
                return self._convert_to_payment_response(payment_to_update)

            except Exception as e:
                logger.error("Error updating payment.", 
                             extra={"payment_id": payment_id, "error": str(e)}, 
                             exc_info=True)
                span.record_exception(e)
                span.set_status(Status(StatusCode.ERROR, "FailedToUpdatePayment"))
                raise HTTPException(status_code=500, detail=f"Failed to update payment {payment_id}: {str(e)}")

    async def create_transaction(self, transaction_data: TransactionCreate) -> TransactionResponse:
        with tracer.start_as_current_span("PaymentService.create_transaction") as span:
            span.set_attribute("app.payment_id", transaction_data.payment_id)
            span.set_attribute("app.transaction.type", transaction_data.transaction_type)
            span.set_attribute("app.transaction.status", transaction_data.status)
            logger.info("Creating transaction.", 
                        extra={
                            "payment_id": transaction_data.payment_id,
                            "type": transaction_data.transaction_type,
                            "status": transaction_data.status
                        })

            db_session = await self._get_write_db()
            try:
                async with db_session.begin():
                    request_json_str = json.dumps(transaction_data.request_data) if transaction_data.request_data is not None else None
                    response_json_str = json.dumps(transaction_data.response_data) if transaction_data.response_data is not None else None

                    transaction = PaymentTransaction(
                        payment_id=transaction_data.payment_id,
                        transaction_type=transaction_data.transaction_type,
                        amount=transaction_data.amount,
                        status=transaction_data.status,
                        payment_gateway=transaction_data.payment_gateway,
                        pg_transaction_id=transaction_data.pg_transaction_id,
                        request_data=request_json_str,
                        response_data=response_json_str
                    )
                    db_session.add(transaction)
                    await db_session.flush()
                
                span.set_attribute("app.transaction_id", str(transaction.id))
                logger.info("Transaction created successfully.", 
                            extra={"transaction_id": str(transaction.id), "payment_id": transaction_data.payment_id})
                span.set_status(Status(StatusCode.OK))
                return TransactionResponse.from_orm(transaction)
            except Exception as e:
                logger.error("Error creating transaction.", 
                             extra={"payment_id": transaction_data.payment_id, "error": str(e)}, 
                             exc_info=True)
                span.record_exception(e)
                span.set_status(Status(StatusCode.ERROR, "FailedToCreateTransaction"))
                raise HTTPException(status_code=500, detail=f"Failed to create transaction: {str(e)}")

    async def get_payment_transactions(self, payment_id: int) -> List[TransactionResponse]:
        with tracer.start_as_current_span("PaymentService.get_payment_transactions") as span:
            span.set_attribute("app.payment_id", payment_id)
            logger.info("Fetching transactions for payment.", extra={"payment_id": payment_id})
            try:
                db = await self._get_read_db()
                result = await db.execute(
                    select(PaymentTransaction)
                    .where(PaymentTransaction.payment_id == payment_id)
                    .order_by(PaymentTransaction.created_at.asc())
                )
                transactions_db = result.scalars().all()
                
                transactions_response = []
                for t_db in transactions_db:
                    temp_response = TransactionResponse.from_orm(t_db)
                    try:
                        if temp_response.request_data and isinstance(temp_response.request_data, str):
                            temp_response.request_data = json.loads(temp_response.request_data)
                        if temp_response.response_data and isinstance(temp_response.response_data, str):
                            temp_response.response_data = json.loads(temp_response.response_data)
                    except json.JSONDecodeError as je:
                        logger.warning("Failed to parse JSON data in transaction record.", 
                                       extra={"transaction_id": t_db.id, "payment_id": payment_id, "error": str(je)})
                    transactions_response.append(temp_response)

                span.set_attribute("app.transactions.count", len(transactions_response))
                logger.info("Successfully fetched transactions.", 
                            extra={"payment_id": payment_id, "count": len(transactions_response)})
                span.set_status(Status(StatusCode.OK))
                return transactions_response
            except Exception as e:
                logger.error("Error getting transactions for payment.", 
                             extra={"payment_id": payment_id, "error": str(e)}, 
                             exc_info=True)
                span.record_exception(e)
                span.set_status(Status(StatusCode.ERROR, "FailedToGetTransactions"))
                raise HTTPException(status_code=500, detail=f"Failed to retrieve transactions: {str(e)}")

    async def process_payment(
        self, order_id: str, amount: float, payment_method: PaymentMethod,
        payment_gateway: str, payment_data_for_pg: Dict[str, Any]
    ) -> PaymentWithTransactions:
        with tracer.start_as_current_span("PaymentService.process_payment") as span:
            log_extra_base = {
                "order_id": order_id, 
                "amount": amount, 
                "method": payment_method.value,
                "gateway": payment_gateway
            }
            span.set_attribute("app.order_id", order_id)
            span.set_attribute("app.payment.amount", amount)
            span.set_attribute("app.payment.method", payment_method.value)
            span.set_attribute("app.payment.gateway", payment_gateway)
            logger.info("Starting payment process.", extra=log_extra_base)

            try:
                span.add_event("Step1_CreateInitialPaymentRecord")
                payment_create_schema = PaymentCreate(
                    order_id=order_id, amount=amount, currency="KRW",
                    payment_method=payment_method
                )
                payment_response = await self.create_payment(payment_create_schema)
                span.set_attribute("app.payment_id", payment_response.payment_id)
                log_extra_base["payment_id"] = payment_response.payment_id

                span.add_event("Step2_SimulateExternalPaymentGatewayCall_Start", 
                               {"pg.request_preview": str(payment_data_for_pg)[:128]})
                logger.info("Simulating call to payment gateway.", 
                            extra=dict(log_extra_base, pg_request_preview=str(payment_data_for_pg)[:128]))
                
                pg_simulated_response = {
                    "success": True,
                    "pg_transaction_id": f"pg_{payment_response.payment_id}_{uuid.uuid4().hex[:8]}",
                    "gateway_status": "APPROVED",
                    "response_code": "0000"
                }
                if round(amount) == 36000:
                    pg_simulated_response["success"] = False
                    pg_simulated_response["gateway_status"] = "DECLINED_SAGA_TEST"
                    logger.warning("Simulated PG call failure for SAGA test in process_payment.", extra=log_extra_base)

                span.add_event("Step2_SimulateExternalPaymentGatewayCall_End", 
                               {"pg.response.success": pg_simulated_response["success"],
                                "pg.transaction_id": pg_simulated_response["pg_transaction_id"]})
                logger.debug("Simulated PG call completed.", 
                             extra=dict(log_extra_base, pg_response_success=pg_simulated_response["success"], 
                                        pg_transaction_id=pg_simulated_response["pg_transaction_id"]))

                span.add_event("Step3_CreatePaymentTransactionRecord")
                transaction_create_schema = TransactionCreate(
                    payment_id=payment_response.payment_id,
                    transaction_type="charge",
                    amount=amount,
                    status="success" if pg_simulated_response["success"] else "failed",
                    payment_gateway=payment_gateway,
                    pg_transaction_id=pg_simulated_response.get("pg_transaction_id"),
                    request_data=payment_data_for_pg,
                    response_data=pg_simulated_response
                )
                transaction_response = await self.create_transaction(transaction_create_schema)
                span.set_attribute("app.transaction_id", transaction_response.id)
                log_extra_base["transaction_id"] = transaction_response.id

                span.add_event("Step4_UpdateFinalPaymentStatus")
                final_payment_status = PaymentStatus.PAID if pg_simulated_response["success"] else PaymentStatus.FAILED
                payment_update_schema = PaymentUpdate(
                    payment_status=final_payment_status,
                    external_payment_id=pg_simulated_response.get("pg_transaction_id"),
                    payment_date=datetime.utcnow() if pg_simulated_response["success"] else None
                )
                updated_payment_response = await self.update_payment(payment_response.payment_id, payment_update_schema)
                
                if not updated_payment_response:
                    err_msg = "Failed to update payment status after PG call."
                    logger.error(err_msg, extra=log_extra_base)
                    span.set_status(Status(StatusCode.ERROR, err_msg))
                    raise HTTPException(status_code=500, detail=f"{err_msg} Payment ID: {payment_response.payment_id}")

                span.set_attribute("app.payment.final_status", updated_payment_response.payment_status.value)
                log_extra_base["final_status"] = updated_payment_response.payment_status.value

                payment_with_transactions_response = PaymentWithTransactions(
                    **updated_payment_response.dict(),
                    transactions=[transaction_response]
                )
                
                logger.info("Payment process completed.", extra=log_extra_base)
                span.set_status(Status(StatusCode.OK))
                return payment_with_transactions_response
            
            except HTTPException as http_exc:
                logger.error("HTTPException during payment processing.", 
                             extra=dict(log_extra_base, error_detail=http_exc.detail, status_code=http_exc.status_code), 
                             exc_info=True)
                span.record_exception(http_exc)
                span.set_status(Status(StatusCode.ERROR, f"ProcessPaymentFailed_HTTPException: {http_exc.detail}"))
                raise
            except Exception as e:
                logger.error("Error processing payment.", 
                             extra=dict(log_extra_base, error=str(e)), 
                             exc_info=True)
                span.record_exception(e)
                span.set_status(Status(StatusCode.ERROR, "FailedToProcessPayment_UnknownError"))
                raise HTTPException(status_code=500, detail=f"Failed to process payment for order {order_id}: {str(e)}")

    async def close(self):
        with tracer.start_as_current_span("PaymentService.close") as span:
            closed_any = False
            try:
                if self.write_db_session and self.write_db_session is not None:
                    await self.write_db_session.close()
                    logger.info("Write DB session closed by PaymentService.")
                    span.add_event("WriteDBSessionClosed")
                    closed_any = True
                if self.read_db_session and self.read_db_session is not None:
                    await self.read_db_session.close()
                    logger.info("Read DB session closed by PaymentService.")
                    span.add_event("ReadDBSessionClosed")
                    closed_any = True
                
                if not closed_any:
                    logger.info("No active DB sessions to close in PaymentService.")
                span.set_status(Status(StatusCode.OK))
            except Exception as e:
                logger.error("Error closing database sessions in PaymentService.", 
                             extra={"error": str(e)}, 
                             exc_info=True)
                span.record_exception(e)
                span.set_status(Status(StatusCode.ERROR, "FailedToCloseDBSessions"))