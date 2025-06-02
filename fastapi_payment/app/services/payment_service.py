# fastapi_payment/app/services/payment_service.py
from typing import List, Optional, Dict, Any
from datetime import datetime
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update
from fastapi import HTTPException # Depends는 현재 이 파일에서 직접 사용되지 않음
import json

# OpenTelemetry API 임포트
from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode, SpanKind
from opentelemetry.semconv.trace import SpanAttributes # 시맨틱 컨벤션
from opentelemetry import propagate

from app.schemas.payment_schemas import (
    PaymentBase, PaymentCreate, PaymentUpdate, PaymentResponse,
    TransactionBase, TransactionCreate, TransactionResponse,
    PaymentStatus, PaymentMethod, PaymentWithTransactions
)
from app.models.payment_model import Payment, PaymentTransaction
# get_async_mysql_db는 현재 이 파일에서 직접 사용되지 않음
from app.config.payment_database import WriteSessionLocal, ReadSessionLocal
from app.config.payment_logging import logger # 기존 로거 사용
import uuid
from app.models.outbox import Outbox

# 모듈 수준 트레이서
tracer = trace.get_tracer(__name__, "0.1.0") # 계측기 이름 및 버전 명시

class PaymentService:
    def __init__(self, session: Optional[AsyncSession] = None): # 주입된 세션은 현재 메서드들에서 직접 사용 안 함
        # self.session = session # 주입된 세션 (현재 로직에서는 직접 사용되지 않음)
        # 각 PaymentService 인스턴스가 자체 DB 세션 풀/팩토리를 참조
        # 실제 세션 객체는 _get_write_db/_get_read_db 호출 시 또는 필요시 생성/관리되어야 하나,
        # 현재 코드는 __init__에서 WriteSessionLocal()/ReadSessionLocal()을 호출하여
        # 인스턴스 변수에 할당하고 이를 계속 사용합니다.
        # 이는 단일 세션 객체를 서비스 인스턴스 생명주기 동안 공유하는 방식일 수 있습니다.
        # 비동기 컨텍스트에서는 각 요청/작업마다 새 세션을 얻는 것이 일반적입니다.
        # 여기서는 제공된 코드 구조를 따르되, 이 점을 인지합니다.
        self.write_db_session: AsyncSession = WriteSessionLocal()
        self.read_db_session: AsyncSession = ReadSessionLocal()

    async def _get_write_db(self) -> AsyncSession:
        # 현재 구현은 __init__에서 생성된 세션을 반환합니다.
        # 스팬 추가의 이점이 적어 생략합니다. DB 작업은 SQLAlchemyInstrumentor가 처리합니다.
        if not self.write_db_session: # 세션 유효성 검사
            logger.info("Recreating write DB session as it was closed or None.")
            self.write_db_session = WriteSessionLocal() # 필요시 세션 재생성
        return self.write_db_session

    async def _get_read_db(self) -> AsyncSession:
        if not self.read_db_session:
            logger.info("Recreating read DB session as it was closed or None.")
            self.read_db_session = ReadSessionLocal()
        return self.read_db_session

    def _convert_to_payment_response(self, payment: Payment) -> PaymentResponse:
        """Payment 모델을 PaymentResponse 스키마로 변환합니다. (내부 헬퍼, 스팬 불필요)"""
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
        """모든 결제 정보를 조회합니다."""
        with tracer.start_as_current_span("PaymentService.get_all_payments") as span:
            logger.info("Fetching all payments")
            try:
                db = await self._get_read_db()
                # SQLAlchemyInstrumentor가 이 DB 호출을 자동 계측
                result = await db.execute(select(Payment).order_by(Payment.created_at.desc()))
                payments = result.scalars().all()
                
                payment_count = len(payments)
                span.set_attribute("app.payments.count", payment_count)
                logger.info(f"Found {payment_count} payments")
                span.set_status(Status(StatusCode.OK))
                return [self._convert_to_payment_response(p) for p in payments]
            except Exception as e:
                logger.error(f"Error getting all payments: {str(e)}", exc_info=True)
                span.record_exception(e)
                span.set_status(Status(StatusCode.ERROR, "FailedToGetAllPayments"))
                raise HTTPException(status_code=500, detail=f"Failed to retrieve payments: {str(e)}")

    async def create_payment(self, payment_data: PaymentCreate) -> PaymentResponse:
        """새로운 결제를 생성하고 Outbox 이벤트를 기록합니다."""
        tracer = trace.get_tracer(__name__, "0.1.0") 
        current_service_entry_span = trace.get_current_span()

        if current_service_entry_span and current_service_entry_span.is_recording():
            ctx = current_service_entry_span.get_span_context()
            parent_span_id_hex = current_service_entry_span.parent.span_id if current_service_entry_span.parent else None
            parent_span_id_str = f"{parent_span_id_hex:x}" if parent_span_id_hex else "None"
            logger.info(
                f"PaymentService.create_payment: ENTRY - TraceID={ctx.trace_id:x}, "
                f"SpanID={ctx.span_id:x}, ParentSpanID={parent_span_id_str}, IsRemote={ctx.is_remote}"
            )
            # 여기서 ParentSpanID가 "PaymentManager.handle_order_created_logic" 스팬의 ID여야 해.
            # 그리고 TraceID는 당연히 order-service부터 쭉 이어져 온 그 ID여야 하고!
        else:
            logger.warning("PaymentService.create_payment: No active/recording span at service entry.")

        with tracer.start_as_current_span("PaymentService.create_payment") as span:
            span.set_attribute("app.order_id", payment_data.order_id)
            span.set_attribute("app.payment.amount", payment_data.amount)
            span.set_attribute("app.payment.currency", payment_data.currency)
            span.set_attribute("app.payment.method", payment_data.payment_method.value)
            logger.info(f"Attempting to create payment for order_id: {payment_data.order_id}")

            try:
                # SAGA 테스트용 실패 시뮬레이션
                if round(payment_data.amount) == 35000: # order 상품이 3500원 * 10 = 35000원인 경우, 일부러 SAGA 패턴 실패 시키기
                    sim_error_msg = "Simulated payment failure for SAGA (order_amount = 20)"
                    logger.warning(sim_error_msg)
                    span.set_attribute("app.payment.simulated_failure", True)
                    span.set_attribute("app.payment.simulated_failure_reason", sim_error_msg)
                    raise Exception(sim_error_msg) # 이 예외는 아래에서 잡힘

                db_session = await self._get_write_db()
                async with db_session.begin(): # 트랜잭션 시작 (SQLAlchemyInstrumentor가 감지 가능)
                    span.add_event("DatabaseTransactionStartedForPayment")
                    # 1. Payment 레코드 생성
                    payment = Payment(
                        order_id=payment_data.order_id,
                        amount=payment_data.amount,
                        currency=payment_data.currency,
                        payment_method=payment_data.payment_method,
                        payment_status=PaymentStatus.PENDING # 초기 상태
                        # stock_reserved는 Payment 모델에 필드가 있다면 설정
                    )
                    db_session.add(payment)
                    await db_session.flush() # payment_id 등 자동 생성 값 가져오기
                    
                    span.set_attribute("app.payment_id", str(payment.payment_id))
                    span.add_event("PaymentRecordCreatedInDB", {"payment.id": str(payment.payment_id)})

                    # 2. Outbox 이벤트 생성 (결제 성공 시 발행될 이벤트)
                    payment_event_payload = {
                        'type': "payment_success", # 또는 "payment_processed", "payment_pending_confirmation" 등
                        'payment_id': str(payment.payment_id),
                        'order_id': payment.order_id,
                        'amount': payment.amount,
                        'currency': payment.currency,
                        'payment_method': payment.payment_method.value,
                        'payment_status': PaymentStatus.PENDING.value, # 생성 시점의 상태
                        'created_at': datetime.utcnow().isoformat() # 일관성을 위해 payment.created_at 사용 고려
                    }

                    # 현재 활성화된 스팬의 컨텍스트를 가져옴
                    current_otel_span = trace.get_current_span()
                    # 주입할 컨텍스트 생성
                    context_to_propagate = trace.set_span_in_context(current_otel_span)
                    
                    carrier = {}  # W3C Trace Context 헤더를 담을 딕셔너리
                    # 전역 프로파게이터를 사용하여 컨텍스트 주입
                    propagator = propagate.get_global_textmap()
                    propagator.inject(carrier, context=context_to_propagate)

                    span.add_event("TraceContextInjectedToCarrierForOutbox", 
                               {"traceparent": carrier.get('traceparent'), "tracestate": carrier.get('tracestate')})

                    outbox_event = Outbox(
                        id=str(uuid.uuid4()),
                        aggregatetype="payment",
                        aggregateid=str(payment.payment_id),
                        type="payment_success", # Kafka 메시지 헤더의 eventType으로 사용될 수 있음
                        payload=payment_event_payload,
                        traceparent_for_header=carrier.get('traceparent'),
                        tracestate_for_header=carrier.get('tracestate')
                    )
                    db_session.add(outbox_event)
                    span.add_event("OutboxEventPreparedForPayment", {"outbox.event.type": "payment_success"})
                    
                    # 트랜잭션 커밋은 async with db_session.begin() 블록 종료 시 자동
                span.add_event("DatabaseTransactionCommittedForPayment")

                # refresh는 트랜잭션 외부 또는 다른 세션에서 하는 것이 일반적이나, 여기서는 같은 세션 사용
                # await db_session.refresh(payment) # 이미 커밋 후 payment 객체는 최신 상태일 수 있음
                # 대신, 명시적으로 다시 로드하여 최신 상태 확인 (필요한 경우)
                # refreshed_payment = await db_session.get(Payment, payment.payment_id)
                # 위 코드는 트랜잭션 커밋 후이므로, payment 객체는 이미 최신 상태
                
                logger.info(f"Payment created successfully: payment_id={payment.payment_id} for order_id={payment.order_id}")
                span.set_status(Status(StatusCode.OK))
                return self._convert_to_payment_response(payment) # payment 객체 직접 사용

            except Exception as e:
                error_message = f"Error creating payment for order {payment_data.order_id}: {str(e)}"
                logger.error(error_message, exc_info=True)
                span.record_exception(e)
                span.set_status(Status(StatusCode.ERROR, "FailedToCreatePayment"))
                # 여기서 db_session.rollback()은 async with begin()에 의해 자동 처리됨
                raise HTTPException(status_code=500, detail=error_message) # 또는 커스텀 예외

    async def get_payment(self, payment_id: int) -> Optional[PaymentResponse]:
        """ID로 특정 결제 정보를 조회합니다."""
        with tracer.start_as_current_span("PaymentService.get_payment") as span:
            span.set_attribute("app.payment_id", payment_id)
            logger.info(f"Fetching payment_id: {payment_id}")
            try:
                db = await self._get_read_db()
                payment = await db.get(Payment, payment_id) # SQLAlchemyInstrumentor가 계측

                if payment:
                    logger.info(f"Payment found: {payment_id}")
                    span.set_attribute("app.payment.found", True)
                    span.set_attribute("app.payment.status", payment.payment_status.value)
                    span.set_status(Status(StatusCode.OK))
                    return self._convert_to_payment_response(payment)
                else:
                    logger.warning(f"Payment not found: {payment_id}")
                    span.set_attribute("app.payment.found", False)
                    span.set_status(Status(StatusCode.OK, "PaymentNotFound")) # 데이터를 못 찾은 것은 서버 오류가 아님
                    return None
            except Exception as e:
                logger.error(f"Error getting payment {payment_id}: {str(e)}", exc_info=True)
                span.record_exception(e)
                span.set_status(Status(StatusCode.ERROR, "FailedToGetPayment"))
                raise HTTPException(status_code=500, detail=f"Failed to retrieve payment {payment_id}: {str(e)}")

    async def update_payment(self, payment_id: int, payment_update: PaymentUpdate) -> Optional[PaymentResponse]:
        """결제 정보를 업데이트합니다 (주로 상태 변경)."""
        with tracer.start_as_current_span("PaymentService.update_payment") as span:
            span.set_attribute("app.payment_id", payment_id)
            if payment_update.payment_status:
                span.set_attribute("app.payment.new_status", payment_update.payment_status.value)
            logger.info(f"Attempting to update payment_id: {payment_id} with data: {payment_update.dict(exclude_unset=True)}")
            
            db_session = await self._get_write_db()
            try:
                async with db_session.begin(): # 트랜잭션
                    span.add_event("DatabaseTransactionStartedForUpdate")
                    # get_payment 내부에서 read_db를 사용하므로, update 시에는 write_db에서 직접 조회
                    payment_to_update = await db_session.get(Payment, payment_id)

                    if not payment_to_update:
                        logger.warning(f"Payment not found for update: {payment_id}")
                        span.set_attribute("app.payment.found", False)
                        span.set_status(Status(StatusCode.OK, "PaymentNotFoundForUpdate"))
                        return None # 또는 HTTPException(404)
                    
                    span.set_attribute("app.payment.found", True)
                    span.set_attribute("app.payment.old_status", payment_to_update.payment_status.value)

                    update_data = payment_update.dict(exclude_unset=True)
                    for field, value in update_data.items():
                        # Enum 값을 실제 DB에 저장되는 값으로 변환해야 할 수 있음 (모델에서 처리 권장)
                        if isinstance(value, (PaymentStatus, PaymentMethod)):
                            setattr(payment_to_update, field, value) # SQLAlchemy가 Enum 변환 처리
                        else:
                            setattr(payment_to_update, field, value)
                    
                    payment_to_update.updated_at = datetime.utcnow()
                    # await db_session.commit() # async with begin() 사용 시 자동 커밋
                span.add_event("DatabaseTransactionCommittedForUpdate")

                # 업데이트된 객체를 refresh하여 최신 상태로 (특히 updated_at 등)
                await db_session.refresh(payment_to_update)
                
                logger.info(f"Payment updated successfully: {payment_id}")
                span.set_status(Status(StatusCode.OK))
                return self._convert_to_payment_response(payment_to_update)

            except Exception as e:
                logger.error(f"Error updating payment {payment_id}: {str(e)}", exc_info=True)
                span.record_exception(e)
                span.set_status(Status(StatusCode.ERROR, "FailedToUpdatePayment"))
                raise HTTPException(status_code=500, detail=f"Failed to update payment {payment_id}: {str(e)}")

    async def create_transaction(self, transaction_data: TransactionCreate) -> TransactionResponse:
        """결제 트랜잭션을 생성합니다."""
        with tracer.start_as_current_span("PaymentService.create_transaction") as span:
            span.set_attribute("app.payment_id", transaction_data.payment_id)
            span.set_attribute("app.transaction.type", transaction_data.transaction_type)
            span.set_attribute("app.transaction.status", transaction_data.status)
            logger.info(f"Creating transaction for payment_id: {transaction_data.payment_id}")

            db_session = await self._get_write_db()
            try:
                async with db_session.begin(): # 트랜잭션
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
                        # created_at은 모델에서 자동 생성
                    )
                    db_session.add(transaction)
                    await db_session.flush() # transaction.id 등 자동 생성 값 가져오기
                
                span.set_attribute("app.transaction_id", str(transaction.id))
                logger.info(f"Transaction created successfully with id: {transaction.id} for payment: {transaction_data.payment_id}")
                span.set_status(Status(StatusCode.OK))
                # from_orm을 위해 transaction 객체가 세션에 연결된 상태여야 함 (refresh 필요 시)
                # await db_session.refresh(transaction) # 이미 flush 후 객체 사용 가능
                return TransactionResponse.from_orm(transaction)
            except Exception as e:
                logger.error(f"Error creating transaction for payment {transaction_data.payment_id}: {str(e)}", exc_info=True)
                span.record_exception(e)
                span.set_status(Status(StatusCode.ERROR, "FailedToCreateTransaction"))
                raise HTTPException(status_code=500, detail=f"Failed to create transaction: {str(e)}")

    async def get_payment_transactions(self, payment_id: int) -> List[TransactionResponse]:
        """특정 결제의 모든 트랜잭션 목록을 조회합니다."""
        with tracer.start_as_current_span("PaymentService.get_payment_transactions") as span:
            span.set_attribute("app.payment_id", payment_id)
            logger.info(f"Fetching transactions for payment_id: {payment_id}")
            try:
                db = await self._get_read_db()
                result = await db.execute(
                    select(PaymentTransaction)
                    .where(PaymentTransaction.payment_id == payment_id)
                    .order_by(PaymentTransaction.created_at.asc()) # 시간순 정렬
                ) # SQLAlchemyInstrumentor가 계측
                transactions_db = result.scalars().all()
                
                transactions_response = []
                for t_db in transactions_db:
                    # JSON 문자열을 다시 dict로 변환 (스키마가 dict를 기대한다면)
                    # TransactionResponse.from_orm이 이를 처리할 수 있도록 스키마 정의 필요
                    # 또는 여기서 수동 변환
                    temp_response = TransactionResponse.from_orm(t_db)
                    if temp_response.request_data and isinstance(temp_response.request_data, str):
                        temp_response.request_data = json.loads(temp_response.request_data)
                    if temp_response.response_data and isinstance(temp_response.response_data, str):
                        temp_response.response_data = json.loads(temp_response.response_data)
                    transactions_response.append(temp_response)

                span.set_attribute("app.transactions.count", len(transactions_response))
                logger.info(f"Found {len(transactions_response)} transactions for payment: {payment_id}")
                span.set_status(Status(StatusCode.OK))
                return transactions_response
            except Exception as e:
                logger.error(f"Error getting transactions for payment {payment_id}: {str(e)}", exc_info=True)
                span.record_exception(e)
                span.set_status(Status(StatusCode.ERROR, "FailedToGetTransactions"))
                raise HTTPException(status_code=500, detail=f"Failed to retrieve transactions: {str(e)}")

    async def process_payment(
        self, order_id: str, amount: float, payment_method: PaymentMethod,
        payment_gateway: str, payment_data_for_pg: Dict[str, Any] # payment_data -> payment_data_for_pg
    ) -> PaymentWithTransactions:
        """결제 생성, 외부 PG 호출(시뮬레이션), 트랜잭션 기록, 상태 업데이트를 포함한 전체 결제 처리."""
        with tracer.start_as_current_span("PaymentService.process_payment") as span:
            span.set_attribute("app.order_id", order_id)
            span.set_attribute("app.payment.amount", amount)
            span.set_attribute("app.payment.method", payment_method.value)
            span.set_attribute("app.payment.gateway", payment_gateway)
            logger.info(f"Starting payment process for order_id: {order_id}")

            try:
                # 1. 결제 생성 (내부 호출, 자체 스팬 가짐)
                span.add_event("Step1_CreateInitialPaymentRecord")
                payment_create_schema = PaymentCreate(
                    order_id=order_id, amount=amount, currency="KRW", # 통화는 고정 또는 파라미터화
                    payment_method=payment_method
                )
                payment_response = await self.create_payment(payment_create_schema)
                # payment_response는 PaymentResponse 타입
                span.set_attribute("app.payment_id", payment_response.payment_id)

                # 2. 외부 결제 시스템 호출 (시뮬레이션)
                span.add_event("Step2_SimulateExternalPaymentGatewayCall_Start", 
                               {"pg.request_preview": str(payment_data_for_pg)[:128]})
                logger.info(f"Simulating call to payment gateway '{payment_gateway}' for payment_id: {payment_response.payment_id}")
                # 실제 PG 호출 시: HTTPXClientInstrumentor 등이 자동 계측 또는 수동 스팬 생성
                # await asyncio.sleep(0.1) # 네트워크 지연 시뮬레이션
                pg_simulated_response = {
                    "success": True, # 테스트를 위해 False로 변경 가능
                    "pg_transaction_id": f"pg_{payment_response.payment_id}_{uuid.uuid4().hex[:8]}",
                    "gateway_status": "APPROVED",
                    "response_code": "0000"
                }
                span.add_event("Step2_SimulateExternalPaymentGatewayCall_End", 
                               {"pg.response.success": pg_simulated_response["success"],
                                "pg.transaction_id": pg_simulated_response["pg_transaction_id"]})

                # 3. 결제 트랜잭션 생성 (내부 호출, 자체 스팬 가짐)
                span.add_event("Step3_CreatePaymentTransactionRecord")
                transaction_create_schema = TransactionCreate(
                    payment_id=payment_response.payment_id,
                    transaction_type="charge", # 또는 "authorization" 등
                    amount=amount,
                    status="success" if pg_simulated_response["success"] else "failed",
                    payment_gateway=payment_gateway,
                    pg_transaction_id=pg_simulated_response.get("pg_transaction_id"),
                    request_data=payment_data_for_pg, # PG 요청 원본
                    response_data=pg_simulated_response # PG 응답 원본
                )
                transaction_response = await self.create_transaction(transaction_create_schema)
                span.set_attribute("app.transaction_id", transaction_response.id)


                # 4. 결제 상태 업데이트 (내부 호출, 자체 스팬 가짐)
                span.add_event("Step4_UpdateFinalPaymentStatus")
                final_payment_status = PaymentStatus.PAID if pg_simulated_response["success"] else PaymentStatus.FAILED
                payment_update_schema = PaymentUpdate(
                    payment_status=final_payment_status,
                    external_payment_id=pg_simulated_response.get("pg_transaction_id"),
                    payment_date=datetime.utcnow() if pg_simulated_response["success"] else None
                )
                updated_payment_response = await self.update_payment(payment_response.payment_id, payment_update_schema)
                
                if not updated_payment_response: # 업데이트 실패 시 (예: payment_id 못찾음)
                    err_msg = f"Failed to update payment status after PG call for payment_id: {payment_response.payment_id}"
                    logger.error(err_msg)
                    span.set_status(Status(StatusCode.ERROR, err_msg))
                    raise HTTPException(status_code=500, detail=err_msg)

                span.set_attribute("app.payment.final_status", updated_payment_response.payment_status.value)

                # 5. 최종 응답 조합
                payment_with_transactions_response = PaymentWithTransactions(
                    **updated_payment_response.dict(),
                    transactions=[transaction_response] # 현재 트랜잭션만 포함
                )
                
                logger.info(f"Payment process completed for order_id: {order_id}, payment_id: {payment_response.payment_id}, status: {final_payment_status.value}")
                span.set_status(Status(StatusCode.OK))
                return payment_with_transactions_response
            
            except HTTPException as http_exc: # 내부 호출에서 발생한 HTTPException
                logger.error(f"HTTPException during payment processing for order {order_id}: {http_exc.detail}", exc_info=True)
                span.record_exception(http_exc) # 이미 자식 스팬에서 기록되었을 수 있음
                span.set_status(Status(StatusCode.ERROR, f"ProcessPaymentFailed_HTTPException: {http_exc.detail}"))
                raise
            except Exception as e:
                logger.error(f"Error processing payment for order {order_id}: {str(e)}", exc_info=True)
                span.record_exception(e)
                span.set_status(Status(StatusCode.ERROR, "FailedToProcessPayment_UnknownError"))
                # 결제 실패 시 보상 로직 (예: Outbox에 payment_process_failed 이벤트 기록) 고려 가능
                raise HTTPException(status_code=500, detail=f"Failed to process payment: {str(e)}")

    async def close(self):
        """데이터베이스 세션 연결을 닫습니다."""
        with tracer.start_as_current_span("PaymentService.close") as span:
            closed_any = False
            try:
                if self.write_db_session and not self.write_db_session.is_closed:
                    await self.write_db_session.close()
                    logger.info("Write DB session closed by PaymentService.")
                    span.add_event("WriteDBSessionClosed")
                    closed_any = True
                if self.read_db_session and not self.read_db_session.is_closed:
                    await self.read_db_session.close()
                    logger.info("Read DB session closed by PaymentService.")
                    span.add_event("ReadDBSessionClosed")
                    closed_any = True
                
                if not closed_any:
                    logger.info("No active DB sessions to close in PaymentService.")
                span.set_status(Status(StatusCode.OK))
            except Exception as e:
                logger.error(f"Error closing database sessions in PaymentService: {str(e)}", exc_info=True)
                span.record_exception(e)
                span.set_status(Status(StatusCode.ERROR, "FailedToCloseDBSessions"))
                # 이 예외를 다시 발생시킬지 여부는 정책에 따름