from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from app.models.order import Order, OrderItem, OrderStatus
from app.models.outbox import Outbox
from app.models.failed_event import FailedEvent

from app.schemas.order import OrderCreate, OrderItemCreate, OrderUpdate
from app.grpc.product_client import ProductClient # GrpcInstrumentorClient가 자동 계측 가정
from app.grpc.user_client import UserClient # GrpcInstrumentorClient가 자동 계측 가정

from fastapi import HTTPException # BackgroundTasks는 현재 사용되지 않음
import asyncio
import logging
import datetime
import json
from typing import Optional
import uuid
# from sqlalchemy.orm import Session # 비동기 코드에서는 사용되지 않음
# from sqlalchemy.exc import SQLAlchemyError # SQLAlchemyInstrumentor가 오류 처리 도움
from app.config.database import WriteSessionLocal, ReadSessionLocal # SQLAlchemyInstrumentor가 자동 계측 가정
import os

# OpenTelemetry API 임포트
from opentelemetry import trace, propagate
from opentelemetry.trace import Status, StatusCode
from opentelemetry.semconv.trace import SpanAttributes # 시맨틱 컨벤션

# 로깅 설정
# logging.basicConfig(level=logging.INFO) # main 또는 설정 파일에서 한 번만 호출 권장
logger = logging.getLogger(__name__)
tracer = trace.get_tracer(__name__) # 모듈 수준 트레이서

class OrderManager:
    def __init__(self, session: Optional[AsyncSession] = None): # 명시적으로 AsyncSession 타입 힌트
        # 외부에서 세션을 주입받는 경우 해당 세션을 사용, 아니면 내부적으로 생성
        self.write_db_session_provided = session is not None
        self.current_write_db_session = session # 주입된 쓰기 세션
        self.current_read_db_session: Optional[AsyncSession] = None # 읽기 세션은 필요시 생성

        self.user_client = UserClient()
        self.product_client = ProductClient()
        self.max_retries = 3
        self.retry_delay = 1  # seconds
    
    async def _get_write_db(self) -> AsyncSession:
        """쓰기 전용 DB 세션을 가져오거나 생성합니다."""
        # 이 메서드 자체의 스팬은 매우 짧으므로 생략 가능. DB 작업은 SQLAlchemyInstrumentor가 계측.
        if self.current_write_db_session is None:
            self.current_write_db_session = WriteSessionLocal()
            if self.current_write_db_session is None: # WriteSessionLocal()이 None을 반환하는 경우는 거의 없음
                logger.error("Failed to create MySQL primary connection session.")
                raise Exception("MySQL primary connection failed")
        return self.current_write_db_session

    async def _get_read_db(self) -> AsyncSession:
        """읽기 전용 DB 세션을 가져오거나 생성합니다."""
        if self.current_read_db_session is None:
            self.current_read_db_session = ReadSessionLocal()
            if self.current_read_db_session is None:
                logger.error("Failed to create MySQL secondary connection session.")
                raise Exception("MySQL secondary connection failed")
        return self.current_read_db_session

    async def _store_failed_event(self, event_type: str, event_data: dict, error: str) -> None:
        """실패한 이벤트를 데이터베이스에 저장합니다."""
        with tracer.start_as_current_span("OrderManager._store_failed_event") as span:
            span.set_attribute("app.event.type", event_type)
            span.set_attribute("app.error.message", error[:1024]) # 오류 메시지 길이 제한
            try:
                event_data_json = json.dumps(event_data)
                span.set_attribute("app.event.data_size", len(event_data_json))
                
                failed_event = FailedEvent(
                    event_type=event_type,
                    event_data=event_data_json,
                    error_message=error,
                    status='pending'
                )
                db = await self._get_write_db()
                db.add(failed_event)
                await db.commit() # SQLAlchemyInstrumentor가 이 DB 작업 계측
                logger.info(f"Stored failed event in database: type={event_type}, error={error}")
                span.set_status(Status(StatusCode.OK))
            except Exception as e:
                logger.critical(f"Failed to store event in database: {str(e)}", exc_info=True)
                logger.critical(f"Critical event loss - Type: {event_type}, Data: {json.dumps(event_data)}, OriginalError: {error}")
                span.record_exception(e)
                span.set_status(Status(StatusCode.ERROR, "Failed to store event in DB"))
                # 여기서 예외를 다시 발생시키지 않으면 실패 이벤트 저장 실패가 호출자에게 알려지지 않음

    async def create_order(self, order_data: OrderCreate):
        """새로운 주문을 생성하고 Outbox 이벤트를 기록합니다."""
        with tracer.start_as_current_span("OrderManager.create_order") as span:
            span.set_attribute("app.user_id", order_data.user_id)
            span.set_attribute("app.item_count", len(order_data.items))
            
            reserved_items = []

            try:
                # Step 1: 사용자 존재 확인 (gRPC 호출)
                span.add_event("ValidatingUser")
                try:
                    user = await self.user_client.get_user(order_data.user_id)
                    if not user:
                        logger.error("User not found", extra={"user_id": order_data.user_id})
                        span.set_attribute("app.validation.error", "UserNotFound")
                        raise HTTPException(status_code=404, detail=f"User {order_data.user_id} not found")
                    span.add_event("UserValidated", {"user_id": order_data.user_id})
                except Exception as e:
                    logger.error("Error validating user", extra={
                        "user_id": order_data.user_id,
                        "error": str(e)
                    }, exc_info=True)
                    span.record_exception(e)
                    span.set_attribute("app.validation.error", "UserClientError")
                    raise HTTPException(status_code=400, detail=f"Invalid user ID or user service error: {str(e)}")

                # Step 2: 상품 가용성 체크, 예약 및 가격 계산
                total_amount = 0.0
                order_items_payload = []
                products_info_cache = {}

                for item_idx, item_data in enumerate(order_data.items):
                    with tracer.start_as_current_span(f"OrderManager.create_order.process_item_{item_idx}") as item_span:
                        item_span.set_attribute("app.product_id", item_data.product_id)
                        item_span.set_attribute("app.quantity", item_data.quantity)
                        
                        item_span.add_event("ReservingInventory")
                        success, message = await self.product_client.check_and_reserve_inventory(
                            item_data.product_id, item_data.quantity
                        )
                        if not success:
                            logger.error("Failed to reserve inventory", extra={
                                "product_id": item_data.product_id,
                                "quantity": item_data.quantity,
                                "error": message
                            })
                            item_span.set_attribute("app.inventory.error", message)
                            item_span.set_status(Status(StatusCode.ERROR, "InventoryReservationFailed"))
                            raise HTTPException(status_code=400, detail=f"Failed to reserve product {item_data.product_id}: {message}")
                        
                        reserved_items.append((item_data.product_id, item_data.quantity))
                        item_span.add_event("InventoryReserved")

                        item_span.add_event("FetchingProductDetails")
                        product = await self.product_client.get_product(item_data.product_id)
                        if not product:
                            logger.error("Product not found", extra={"product_id": item_data.product_id})
                            raise HTTPException(status_code=404, detail=f"Product {item_data.product_id} not found")
                        
                        products_info_cache[item_data.product_id] = {'product': product}
                        item_span.add_event("ProductDetailsFetched", {"price": product.price})

                        total_amount += product.price * item_data.quantity
                        order_items_payload.append({
                            'product_id': item_data.product_id,
                            'quantity': item_data.quantity,
                            'price': product.price
                        })
                        item_span.set_status(Status(StatusCode.OK))
                
                span.set_attribute("app.order.calculated_total_amount", total_amount)

                # Step 3: 트랜잭션 시작 및 DB 작업
                db = await self._get_write_db()
                async with db.begin():
                    span.add_event("DatabaseTransactionStarted")
                    
                    order = Order(
                        user_id=order_data.user_id,
                        status=OrderStatus.PENDING,
                        total_amount=total_amount,
                    )
                    db.add(order)
                    await db.flush()
                    span.set_attribute("app.order_id", str(order.order_id))
                    span.add_event("OrderRecordFlushed", {"order.id_assigned": str(order.order_id)})

                    for item_data in order_data.items:
                        product_info = products_info_cache[item_data.product_id]
                        order_item = OrderItem(
                            order_id=order.order_id,
                            product_id=item_data.product_id,
                            quantity=item_data.quantity,
                            price_at_order=product_info['product'].price
                        )
                        db.add(order_item)
                    
                    current_otel_span = trace.get_current_span()
                    context_to_propagate = trace.set_span_in_context(current_otel_span)
                    carrier = {}
                    propagator = propagate.get_global_textmap()
                    propagator.inject(carrier, context=context_to_propagate)

                    span.add_event("TraceContextInjectedToCarrierForOutbox", 
                               {"traceparent": carrier.get('traceparent'), "tracestate": carrier.get('tracestate')})

                    order_created_event_payload = {
                        'type': "order_created",
                        'order_id': str(order.order_id),
                        'user_id': order.user_id,
                        'total_amount': total_amount,
                        'status': OrderStatus.PENDING.value,
                        'items': order_items_payload,
                        'created_at': datetime.datetime.utcnow().isoformat(),
                    }

                    outbox_event = Outbox(
                        id=str(uuid.uuid4()),
                        aggregatetype="order",
                        aggregateid=str(order.order_id),
                        type="order_created",
                        payload=order_created_event_payload,
                        traceparent_for_header=carrier.get('traceparent'), 
                        tracestate_for_header=carrier.get('tracestate')
                    )
                    db.add(outbox_event)
                    span.add_event("OutboxEventPrepared", {"outbox.event.type": "order_created"})

                span.add_event("DatabaseTransactionCommitted")
                logger.info("Order created successfully", extra={
                    "order_id": str(order.order_id),
                    "user_id": order_data.user_id,
                    "total_amount": total_amount,
                    "item_count": len(order_data.items)
                })
                span.set_status(Status(StatusCode.OK))
                return {
                    "order_id": str(order.order_id),
                    "status": "PENDING",
                    "message": "Order created successfully and pending payment."
                }

            except HTTPException as http_exc:
                logger.error("HTTP error in create_order", extra={
                    "error": http_exc.detail,
                    "user_id": order_data.user_id
                })
                span.record_exception(http_exc)
                span.set_status(Status(StatusCode.ERROR, http_exc.detail))
                if reserved_items:
                    span.add_event("RollingBackReservedInventory", {"item_count": len(reserved_items)})
                    for prod_id, qty in reserved_items:
                        try:
                            await self.product_client.cancel_inventory_reservation(prod_id, qty)
                        except Exception as e:
                            logger.error("Failed to cancel inventory reservation", extra={
                                "product_id": prod_id,
                                "quantity": qty,
                                "error": str(e)
                            })
                raise
            except Exception as e:
                logger.error("Failed to create order", extra={
                    "user_id": order_data.user_id,
                    "error": str(e)
                }, exc_info=True)
                span.record_exception(e)
                span.set_status(Status(StatusCode.ERROR, "FailedToCreateOrder_UnknownError"))
                if reserved_items:
                    span.add_event("RollingBackReservedInventoryDueToError", {"item_count": len(reserved_items)})
                    for prod_id, qty in reserved_items:
                        try:
                            await self.product_client.cancel_inventory_reservation(prod_id, qty)
                        except Exception as comp_e:
                            logger.error("Failed to compensate inventory", extra={
                                "product_id": prod_id,
                                "quantity": qty,
                                "error": str(comp_e)
                            })
                            span.add_event("InventoryCompensationFailed", {"product_id": prod_id, "error": str(comp_e)})
                raise HTTPException(status_code=500, detail=f"Failed to create order: {str(e)}")

    async def handle_payment_success(self, event_data: dict):
        """결제 성공 이벤트를 처리합니다. (Kafka 핸들러에서 호출됨)"""
        try:
            with tracer.start_as_current_span("OrderManager.handle_payment_success") as span:
                original_event_data_str = json.dumps(event_data) # 로깅 및 실패 시 저장용
                span.set_attribute("app.event.type", "payment_success")
                span.set_attribute("app.event.data_preview", original_event_data_str[:256])

                current_otel_span_for_outbox = trace.get_current_span()
                context_to_propagate_for_outbox = trace.set_span_in_context(current_otel_span_for_outbox)
                carrier_for_outbox = {}
                propagator_instance = propagate.get_global_textmap() # 전역 설정된 W3C 전파기 사용
                propagator_instance.inject(carrier_for_outbox, context=context_to_propagate_for_outbox)
                span.add_event("TraceContextInjectedToCarrierForOrderOutbox", 
                               {"traceparent": carrier_for_outbox.get('traceparent')})


                order_id = event_data.get('order_id')
                payment_id = event_data.get('payment_id')
                span.set_attribute("app.order_id", str(order_id))
                if payment_id:
                    span.set_attribute("app.payment_id", str(payment_id))
                
                if not order_id:
                    err_msg = "Missing order_id in payment_success event"
                    logger.error(f"{err_msg}: {event_data}")
                    span.set_status(Status(StatusCode.ERROR, err_msg))
                    await self._store_failed_event('payment_success_parsing', event_data, err_msg)
                    return

                logger.info(f"Processing payment success for order_id: {order_id}")
                
                retry_count = 0
                while retry_count <= self.max_retries: # <= 로 변경하여 max_retries 포함 (0부터 시작)
                    span.add_event(f"ProcessingAttempt", {"retry.count": retry_count})

                    try:
                        db = await self._get_write_db()
                        async with db.begin(): # 트랜잭션
                            # 1. 주문 조회
                            query = select(Order).options(selectinload(Order.items)).where(Order.order_id == int(order_id))
                            result = await db.execute(query)
                            order = result.scalar_one_or_none()
                            
                            if not order:
                                raise ValueError(f"Order {order_id} not found for payment success")
                            
                            # 이미 처리된 주문인지 확인 (멱등성)
                            if order.status == OrderStatus.COMPLETED:
                                logger.info(f"Order {order_id} already completed. Idempotency check passed.")
                                span.add_event("OrderAlreadyCompleted")
                                span.set_status(Status(StatusCode.OK, "Already completed"))
                                return

                            # 2. 주문 상태 업데이트
                            order.status = OrderStatus.COMPLETED
                            order.updated_at = datetime.datetime.utcnow()
                            span.add_event("OrderStatusUpdatedToCompleted")

                            # 3. Outbox 이벤트 (order_success) 생성
                            order_items_payload = [{'product_id': item.product_id, 'quantity': item.quantity, 'price': item.price_at_order} for item in order.items]
                            order_success_event_payload = {
                                'type': "order_success",
                                'order_id': str(order.order_id),
                                'user_id': order.user_id,
                                'status': OrderStatus.COMPLETED.value,
                                'items': order_items_payload,
                                'payment_id': payment_id,
                                'amount': event_data.get('amount'),
                                'payment_method': event_data.get('payment_method', 'unknown'),
                                'payment_status': 'completed',
                                'created_at': datetime.datetime.utcnow().isoformat()
                            }
                            outbox_event = Outbox(
                                id=str(uuid.uuid4()), aggregatetype="order", aggregateid=str(order.order_id),
                                type="order_success", payload=order_success_event_payload,
                                traceparent_for_header=carrier_for_outbox.get('traceparent'),
                                tracestate_for_header=carrier_for_outbox.get('tracestate')
                            )
                            db.add(outbox_event)
                            span.add_event("OutboxEventOrderSuccessPrepared")
                        
                        logger.info(f"Successfully processed payment_success for order {order_id}")
                        span.set_status(Status(StatusCode.OK))
                        return # 성공 시 루프 종료

                    except ValueError as ve: # 주문 못찾는 경우 등, 재시도 불필요
                        logger.error(f"ValueError during payment success for order {order_id}: {str(ve)}", exc_info=True)
                        span.record_exception(ve)
                        span.set_status(Status(StatusCode.ERROR, f"ValueError: {str(ve)}"))
                        await self._store_failed_event('payment_success_processing_error', event_data, f"ValueError: {str(ve)}")
                        return # 루프 종료
                    except Exception as e:
                        logger.error(f"Error processing payment success (attempt {retry_count+1}/{self.max_retries+1}) for order {order_id}: {str(e)}", exc_info=True)
                        span.record_exception(e) # 각 재시도 시 예외 기록
                        retry_count += 1
                        if retry_count > self.max_retries:
                            logger.error(f"Failed to process payment_success after {self.max_retries+1} attempts for order {order_id}.")
                            span.set_status(Status(StatusCode.ERROR, "MaxRetriesExceeded"))
                            # 최종 실패 시 보상 이벤트 생성 또는 실패 이벤트 저장
                            await self.create_compensation_event(event_data, "order_update_to_completed_failed") # 보상 이벤트 타입 명확히
                            # 또는 await self._store_failed_event('payment_success_max_retries', event_data, str(e))
                            return # 루프 종료
                        await asyncio.sleep(self.retry_delay * (2 ** (retry_count -1 ))) # Exponential backoff
        except Exception as e: # 최상위 예외 처리 (파싱 등 초기 오류)
            logger.error(f"Unhandled error in handle_payment_success for event: {original_event_data_str}: {str(e)}", exc_info=True)
            span.record_exception(e)
            span.set_status(Status(StatusCode.ERROR, "OuterExceptionInHandlePaymentSuccess"))
            await self._store_failed_event('payment_success_unhandled_error', json.loads(original_event_data_str), str(e))

    async def handle_payment_failed(self, event_data: dict):
        """결제 실패 이벤트를 처리합니다. (Kafka 핸들러에서 호출됨)"""
        with tracer.start_as_current_span("OrderManager.handle_payment_failed") as span:
            original_event_data_str = json.dumps(event_data)
            span.set_attribute("app.event.type", "payment_failed")
            span.set_attribute("app.event.data_preview", original_event_data_str[:256])

            current_otel_span = trace.get_current_span()
            context_to_propagate = trace.set_span_in_context(current_otel_span)
            carrier = {}
            propagator_instance = propagate.get_global_textmap()
            propagator_instance.inject(carrier, context=context_to_propagate)
            span.add_event("TraceContextInjectedToCarrierForOrderFailedOutbox", {"traceparent": carrier.get('traceparent')})

            parsed_event_data = event_data # 이미 wrapper에서 파싱되었을 수 있으나, 여기서 다시 확인/처리

            try:
                # Debezium 메시지 처리 (필요한 경우) / event_data가 이미 payload일 수 있음
                if 'payload' in parsed_event_data and isinstance(parsed_event_data['payload'], (dict, str)):
                    payload_content = parsed_event_data['payload']
                    if isinstance(payload_content, str):
                        payload_content = json.loads(payload_content)
                    parsed_event_data = payload_content # 실제 처리할 데이터
                
                order_id = parsed_event_data.get('order_id')
                # items = parsed_event_data.get('items', []) # 재고 복원에 사용될 수 있음

                span.set_attribute("app.order_id", str(order_id))
                if not order_id:
                    err_msg = "Missing order_id in payment_failed event"
                    logger.error(f"{err_msg}: {parsed_event_data}")
                    span.set_status(Status(StatusCode.ERROR, err_msg))
                    await self._store_failed_event('payment_failed_parsing', event_data, err_msg)
                    return

                logger.info(f"Processing payment failure for order_id: {order_id}")
                db = await self._get_write_db()
                async with db.begin():
                    query = select(Order).options(selectinload(Order.items)).where(Order.order_id == int(order_id))
                    result = await db.execute(query)
                    order = result.scalar_one_or_none()

                    if not order:
                        logger.warning(f"Order {order_id} not found for payment failure. Possibly already handled or invalid.")
                        span.set_status(Status(StatusCode.OK, "OrderNotFound_PotentiallyHandled")) # 에러는 아닐 수 있음
                        return

                    if order.status == OrderStatus.CANCELLED:
                        logger.info(f"Order {order_id} already cancelled. Idempotency check passed.")
                        span.add_event("OrderAlreadyCancelled")
                        span.set_status(Status(StatusCode.OK, "Already cancelled"))
                        return

                    order.status = OrderStatus.CANCELLED
                    order.updated_at = datetime.datetime.utcnow()
                    span.add_event("OrderStatusUpdatedToCancelled")

                    # Outbox 이벤트 (order_failed) 생성
                    order_items_payload = [{'product_id': item.product_id, 'quantity': item.quantity, 'price': item.price_at_order} for item in order.items]
                    order_failed_event_payload = {
                        'type': "order_failed",
                        'order_id': str(order.order_id),
                        'user_id': order.user_id,
                        'status': OrderStatus.CANCELLED.value,
                        'reason': parsed_event_data.get('reason', 'Payment failed'),
                        'items': order_items_payload, # 주문 취소 시 복원해야 할 아이템 정보
                        'created_at': datetime.datetime.utcnow().isoformat()
                    }
                    outbox_event = Outbox(
                        id=str(uuid.uuid4()), aggregatetype="order", aggregateid=str(order.order_id),
                        type="order_failed", payload=order_failed_event_payload,
                        traceparent_for_header=carrier.get('traceparent'), 
                        tracestate_for_header=carrier.get('tracestate')
                    )
                    db.add(outbox_event)
                    span.add_event("OutboxEventOrderFailedPrepared")

                    # 중요: 결제 실패 시 예약된 재고를 다시 복원하는 로직 필요.
                    # 이 로직은 ProductClient를 통해 호출되어야 하며, 각 아이템에 대해 실행.
                    # 예: for item in order.items:
                    # await self.product_client.cancel_inventory_reservation(item.product_id, item.quantity)
                    # 이 부분은 현재 코드에 명시적으로 없으므로, 추가 구현 필요 시 고려.
                    # 여기서는 Outbox 이벤트만 생성하고, 재고 복원은 다른 서비스(예: Product 서비스가 order_failed 이벤트 구독)에서 처리한다고 가정.
                
                logger.info(f"Successfully processed payment_failed for order {order_id}, status set to CANCELLED.")
                span.set_status(Status(StatusCode.OK))

            except json.JSONDecodeError as je:
                logger.error(f"JSONDecodeError in handle_payment_failed for event: {original_event_data_str}: {str(je)}", exc_info=True)
                span.record_exception(je)
                span.set_status(Status(StatusCode.ERROR, "JSONDecodeError"))
                await self._store_failed_event('payment_failed_json_parsing', json.loads(original_event_data_str), str(je))
            except Exception as e:
                logger.error(f"Unhandled error in handle_payment_failed for event: {original_event_data_str}: {str(e)}", exc_info=True)
                span.record_exception(e)
                span.set_status(Status(StatusCode.ERROR, "UnhandledExceptionInHandlePaymentFailed"))
                await self._store_failed_event('payment_failed_unhandled_error', json.loads(original_event_data_str), str(e))

    async def create_compensation_event(self, original_event: dict, compensation_type: str):
        """보상 이벤트를 Outbox에 기록합니다."""
        with tracer.start_as_current_span("OrderManager.create_compensation_event") as span:
            order_id = original_event.get('order_id')
            span.set_attribute("app.order_id", str(order_id))
            span.set_attribute("app.compensation.type", compensation_type)
            logger.info(f"Creating compensation event '{compensation_type}' for order {order_id}")
            try:
                db = await self._get_write_db()
                async with db.begin():
                    compensation_event_payload = {
                        'type': compensation_type, # 예: "order_update_to_completed_failed"
                        'order_id': str(order_id),
                        'original_event_preview': json.dumps(original_event)[:256], # 원본 이벤트 요약
                        'reason': f'Compensation for {compensation_type}',
                        'timestamp': datetime.datetime.utcnow().isoformat()
                    }
                    outbox_event = Outbox(
                        id=str(uuid.uuid4()),
                        aggregatetype="order_compensation", # 별도 aggregate type 또는 order 사용
                        aggregateid=str(order_id),
                        type=compensation_type, 
                        payload=compensation_event_payload
                    )
                    db.add(outbox_event)
                    logger.info(f"Compensation event '{compensation_type}' for order {order_id} added to outbox.")
                    span.set_status(Status(StatusCode.OK))
            except Exception as e:
                logger.critical(f"Failed to create compensation event for order {order_id}: {str(e)}", exc_info=True)
                span.record_exception(e)
                span.set_status(Status(StatusCode.ERROR, "FailedToCreateCompensationEvent"))
                # 보상 이벤트 생성 실패는 매우 심각한 상황, 별도 알림 필요

    async def get_order(self, order_id: int) -> Optional[Order]: # Optional 추가
        """특정 주문 정보를 조회합니다."""
        with tracer.start_as_current_span("OrderManager.get_order") as span:
            span.set_attribute("app.order_id", order_id)
            logger.info(f"Fetching order {order_id}")
            try:
                db = await self._get_read_db()
                query = select(Order).options(selectinload(Order.items)).where(Order.order_id == order_id)
                result = await db.execute(query) # SQLAlchemyInstrumentor가 계측
                order = result.scalar_one_or_none()
                
                if not order:
                    logger.warning(f"Order {order_id} not found")
                    span.set_attribute("app.order.found", False)
                    # HTTPException 대신 None을 반환하고 호출부에서 처리하도록 변경 가능
                    # 여기서는 기존 로직을 따라 HTTPException 발생시킴
                    # raise HTTPException(status_code=404, detail=f"Order {order_id} not found")
                    span.set_status(Status(StatusCode.OK, "OrderNotFound")) # 기술적으로는 에러가 아님
                    return None 
                
                span.set_attribute("app.order.found", True)
                span.set_attribute("app.order.status", order.status.value)
                span.set_status(Status(StatusCode.OK))
                return order
            except Exception as e:
                logger.error(f"Error fetching order {order_id}: {str(e)}", exc_info=True)
                span.record_exception(e)
                span.set_status(Status(StatusCode.ERROR, "FailedToFetchOrder"))
                raise # 또는 HTTPException으로 변환하여 발생
    
    async def get_user_orders(self, user_id: str) -> list[Order]:
        """특정 사용자의 모든 주문 목록을 조회합니다."""
        with tracer.start_as_current_span("OrderManager.get_user_orders") as span:
            span.set_attribute("app.user_id", user_id)
            logger.info(f"Fetching orders for user {user_id}")
            try:
                db = await self._get_read_db()
                query = select(Order).options(selectinload(Order.items)).where(Order.user_id == user_id)
                result = await db.execute(query) # SQLAlchemyInstrumentor가 계측
                orders = result.scalars().all()
                span.set_attribute("app.order_count", len(orders))
                span.set_status(Status(StatusCode.OK))
                return orders
            except Exception as e:
                logger.error(f"Error fetching orders for user {user_id}: {str(e)}", exc_info=True)
                span.record_exception(e)
                span.set_status(Status(StatusCode.ERROR, "FailedToFetchUserOrders"))
                raise
    
    async def update_order_status(self, order_id: int, status: OrderStatus) -> Order:
        """주문의 상태를 변경합니다."""
        with tracer.start_as_current_span("OrderManager.update_order_status") as span:
            span.set_attribute("app.order_id", order_id)
            span.set_attribute("app.order.new_status", status.value)
            logger.info(f"Updating status for order {order_id} to {status}")
            try:
                db = await self._get_write_db()
                async with db.begin(): # 명시적 트랜잭션
                    # get_order를 호출하면 중복 스팬이 생길 수 있으므로, 직접 조회 또는 내부 로직 사용
                    order_query = select(Order).where(Order.order_id == order_id)
                    result = await db.execute(order_query)
                    order = result.scalar_one_or_none()

                    if not order:
                        raise HTTPException(status_code=404, detail=f"Order {order_id} not found for status update")
                    
                    order.status = status
                    order.updated_at = datetime.datetime.utcnow()
                    # await db.commit() # async with db.begin() 사용 시 자동 커밋
                
                # Outbox 이벤트 생성 (예: order_status_updated) - 필요시 추가
                # ... 

                span.set_status(Status(StatusCode.OK))
                return order
            except HTTPException as http_exc:
                span.record_exception(http_exc)
                span.set_status(Status(StatusCode.ERROR, http_exc.detail))
                raise
            except Exception as e:
                logger.error(f"Error updating status for order {order_id}: {str(e)}", exc_info=True)
                span.record_exception(e)
                span.set_status(Status(StatusCode.ERROR, "FailedToUpdateOrderStatus"))
                raise

    # update_order, delete_order 등 다른 public 메서드도 유사한 방식으로 트레이싱 적용 가능
    
    async def close(self):
        """DB 세션 및 gRPC 클라이언트 연결을 정리합니다."""
        with tracer.start_as_current_span("OrderManager.close") as span:
            closed_resources = []
            try:
                if self.current_write_db_session and not self.write_db_session_provided: # 주입되지 않은 세션만 닫음
                    await self.current_write_db_session.close()
                    closed_resources.append("WriteDBSession")
                if self.current_read_db_session:
                    await self.current_read_db_session.close()
                    closed_resources.append("ReadDBSession")
                
                # gRPC 클라이언트 close 메서드가 비동기이고 필요하다면 호출
                # UserClient와 ProductClient에 비동기 close 메서드가 있다고 가정
                await self.user_client.close() # 자동 계측 (GrpcInstrumentorClient)
                closed_resources.append("UserClient")
                await self.product_client.close() # 자동 계측 (GrpcInstrumentorClient)
                closed_resources.append("ProductClient")

                logger.info(f"OrderManager resources closed: {', '.join(closed_resources)}")
                span.set_attribute("app.closed_resources", ", ".join(closed_resources))
                span.set_status(Status(StatusCode.OK))
            except Exception as e:
                logger.error(f"Error during OrderManager close: {str(e)}", exc_info=True)
                span.record_exception(e)
                span.set_status(Status(StatusCode.ERROR, "FailedToCloseResources"))

    async def update_order(self, order_id: int, order_update: OrderUpdate) -> Order: # order_id 타입을 int로 가정
        with tracer.start_as_current_span("OrderManager.update_order") as span:
            span.set_attribute("app.order_id", order_id)
            logger.info(f"Updating order {order_id}")
            try:
                db = await self._get_write_db()
                async with db.begin():
                    order = await self.get_order_within_session(db, order_id) # 세션 내에서 조회하는 헬퍼 사용
                    if not order:
                        raise HTTPException(status_code=404, detail=f"Order {order_id} not found for update")

                    update_data = order_update.dict(exclude_unset=True)
                    span.set_attribute("app.update_fields_count", len(update_data))
                    for field, value in update_data.items():
                        setattr(order, field, value)
                    order.updated_at = datetime.datetime.utcnow()
                
                # Outbox 이벤트 생성 (예: order_general_updated) - 필요시 추가

                span.set_status(Status(StatusCode.OK))
                return order
            except HTTPException as http_exc:
                span.record_exception(http_exc)
                span.set_status(Status(StatusCode.ERROR, http_exc.detail))
                raise
            except Exception as e:
                logger.error(f"Error updating order {order_id}: {str(e)}", exc_info=True)
                span.record_exception(e)
                span.set_status(Status(StatusCode.ERROR, "FailedToUpdateOrder"))
                raise

    async def delete_order(self, order_id: int): # order_id 타입을 int로 가정
        with tracer.start_as_current_span("OrderManager.delete_order") as span:
            span.set_attribute("app.order_id", order_id)
            logger.info(f"Deleting order {order_id}")
            try:
                db = await self._get_write_db()
                async with db.begin():
                    order = await self.get_order_within_session(db, order_id) # 세션 내에서 조회
                    if not order:
                        raise HTTPException(status_code=404, detail=f"Order {order_id} not found for deletion")
                    await db.delete(order) # SQLAlchemyInstrumentor가 계측
                
                # Outbox 이벤트 생성 (예: order_deleted) - 필요시 추가

                span.set_status(Status(StatusCode.OK))
            except HTTPException as http_exc:
                span.record_exception(http_exc)
                span.set_status(Status(StatusCode.ERROR, http_exc.detail))
                raise
            except Exception as e:
                logger.error(f"Error deleting order {order_id}: {str(e)}", exc_info=True)
                span.record_exception(e)
                span.set_status(Status(StatusCode.ERROR, "FailedToDeleteOrder"))
                raise

    async def get_order_within_session(self, db: AsyncSession, order_id: int) -> Optional[Order]:
        """(Helper) Pro_vide_d session to fetch an order with items."""
        # 이 헬퍼는 외부 호출이 아닌, 이미 스팬이 활성화된 컨텍스트 내에서 사용됨
        # 별도 스팬을 만들 수도 있지만, SQLAlchemyInstrumentor가 DB 쿼리를 계측하므로 생략 가능
        query = select(Order).options(selectinload(Order.items)).where(Order.order_id == order_id)
        result = await db.execute(query)
        return result.scalar_one_or_none()