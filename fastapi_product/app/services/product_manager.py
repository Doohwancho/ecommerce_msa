# fastapi-product/app/services/product_manager.py
import asyncio
import datetime
import json
import logging
import os
import uuid
from typing import Callable, Dict # Optional 제거 (사용 안 됨)


from app.config.database import WriteSessionLocal # SQLAlchemyInstrumentor가 DB 세션 자동 계측
from app.config.kafka_consumer import ProductModuleKafkaConsumer # 수정된 컨슈머 클래스 임포트
# from app.config.logging import logger # 중앙 로깅 설정 사용 시
from app.models.outbox import Outbox
from app.services.product_service import ProductService

# OpenTelemetry API 임포트
from opentelemetry import propagate, trace
from opentelemetry.semconv.trace import SpanAttributes
from opentelemetry.trace import SpanKind, Status, StatusCode

logger = logging.getLogger(__name__)


class ProductManager:
    def __init__(self):
        self.kafka_consumer: ProductModuleKafkaConsumer | None = None # 타입 명시
        self.max_retries = 3
        self.retry_delay = 1  # seconds
        # Tracer는 __init__ 시점에 OTel 설정이 완료되었다고 가정하고 가져옴
        self.tracer = trace.get_tracer(
            "app.services.product_manager.ProductManager", "0.1.0"
        )
        logger.info("ProductManager instance created.")

    async def initialize_kafka(self, bootstrap_servers: str, group_id: str):
        with self.tracer.start_as_current_span("ProductManager.initialize_kafka") as span: # 스팬 이름 일관성
            span.set_attribute("app.kafka.bootstrap_servers", bootstrap_servers)
            span.set_attribute("app.kafka.consumer_group", group_id)
            try:
                # OrderModule의 Outbox에서 'aggregatetype="order"'로 발행된 이벤트가 오는 토픽
                # 보통 'order_success', 'order_failed' 이벤트가 여기로 옴
                order_module_events_topic = os.getenv("ORDER_MODULE_EVENTS_TOPIC", "dbserver.order") 
                subscribed_topics = [order_module_events_topic]
                span.set_attribute("app.kafka.subscribed_topics", ",".join(subscribed_topics))
                
                self.kafka_consumer = ProductModuleKafkaConsumer( # 클래스 이름 확인
                    bootstrap_servers=bootstrap_servers,
                    group_id=group_id,
                    topics=subscribed_topics # 생성자에 토픽 리스트 전달
                )

                # ProductModuleKafkaConsumer는 event_type만으로 핸들러를 구분 (topic은 생성 시 지정)
                self.kafka_consumer.register_handler(
                    event_type='order_success', # OrderModule Outbox의 'type' 필드와 일치
                    handler=self.handle_order_success 
                )
                self.kafka_consumer.register_handler(
                    event_type='order_failed',  # OrderModule Outbox의 'type' 필드와 일치
                    handler=self.handle_order_failed
                )
                
                await self.kafka_consumer.start()
                logger.info(f"ProductManager: Kafka consumer initialized for group '{group_id}', topics '{subscribed_topics}'.")
                span.set_status(Status(StatusCode.OK))
            except Exception as e:
                logger.error(f"ProductManager: Failed to initialize Kafka consumer: {e}", exc_info=True)
                if span.is_recording():
                    span.record_exception(e)
                    span.set_status(Status(StatusCode.ERROR, "Kafka init failed in ProductManager"))
                raise
    

    async def _process_event_with_retries(self, event_name: str, event_data: dict, handler_logic_method: Callable, compensation_method: Callable | None = None):
        # 이 스팬은 ProductModuleKafkaConsumer._consume_loop에서
        # AIOKafkaInstrumentor가 만든 부모 CONSUMER 스팬의 자식으로 자동 생성됨.
        # tracer = trace.get_tracer(__name__) # 필요 시 함수 내에서 다시 얻기
        with self.tracer.start_as_current_span(
            f"ProductManager.process.{event_name}", kind=SpanKind.INTERNAL
        ) as span:
            order_id = event_data.get("order_id", "unknown_order")
            span.set_attribute("app.event.name_handled", event_name)
            span.set_attribute("app.order_id", str(order_id))
            try:
                span.set_attribute("app.event.data_preview", json.dumps(event_data, ensure_ascii=False)[:256])
            except:
                span.set_attribute("app.event.data_preview", str(event_data)[:256])


            retry_count = 0
            last_exception = None
            while retry_count <= self.max_retries:
                current_attempt = retry_count + 1
                span.set_attribute("app.retry.attempt", current_attempt)
                try:
                    logger.info(
                        f"Processing '{event_name}' for order '{order_id}', attempt {current_attempt}/{self.max_retries + 1}."
                    )
                    # 핸들러 로직 호출 (이 안에서도 자체적인 자식 스팬 생성 가능)
                    await handler_logic_method(event_data) # parent_span 인자 제거
                    span.set_status(Status(StatusCode.OK))
                    logger.info(
                        f"Successfully processed '{event_name}' for order '{order_id}' on attempt {current_attempt}."
                    )
                    return  # 성공 시 루프 종료
                except ValueError as ve:  # 데이터 유효성 검사 에러 (재시도 무의미)
                    error_msg = f"Data error processing '{event_name}' for order '{order_id}' (attempt {current_attempt}): {ve}"
                    logger.error(error_msg, exc_info=True)
                    if span.is_recording():
                        span.record_exception(ve)
                        span.set_status(Status(StatusCode.ERROR, error_msg))
                        span.set_attribute("app.error.type", "validation_error")
                    if compensation_method:
                        await compensation_method(
                            event_data,
                            failure_type=f"{event_name}_data_validation_failed", # 명확한 실패 타입
                            reason=f"Data error: {ve}"
                        )
                    return  # 재시도 없이 종료
                except Exception as e:  # 기타 재시도 가능한 에러
                    last_exception = e
                    retry_count += 1
                    error_message = f"Error processing '{event_name}' for order '{order_id}' (attempt {current_attempt} failed, next: {retry_count +1 if retry_count <= self.max_retries else 'max_retries_exceeded'}): {e}"
                    logger.error(error_message, exc_info=True)
                    if span.is_recording():
                        span.record_exception(e)
                        span.add_event(
                            "handler_retry_exception",
                            {
                                "exception.message": str(e),
                                "retry.attempt_number_failed": current_attempt,
                            },
                        )

                    if retry_count > self.max_retries:
                        final_error_msg = f"CRITICAL: Failed to process '{event_name}' for order '{order_id}' after {self.max_retries + 1} attempts. Last error: {last_exception}"
                        logger.critical(final_error_msg)
                        if span.is_recording():
                            span.set_status(Status(StatusCode.ERROR, final_error_msg))
                            span.set_attribute("app.error.type", "max_retries_exceeded")
                        if compensation_method:
                            await compensation_method(
                                event_data,
                                failure_type=f"{event_name}_max_retries_exceeded", # 명확한 실패 타입
                                reason=f"Max retries exceeded: {last_exception}"
                            )
                        return  # 모든 재시도 실패, 루프 종료

                    sleep_duration = self.retry_delay * (2 ** (retry_count - 1))
                    logger.info(
                        f"Retrying '{event_name}' for order '{order_id}' in {sleep_duration}s (attempt {retry_count + 1})..."
                    )
                    if span.is_recording(): # 스팬이 살아있을 때만 이벤트 추가
                        span.add_event("retrying_handler_after_delay", {"delay_seconds": sleep_duration})
                    await asyncio.sleep(sleep_duration)

    async def _handle_order_success_logic(self, event_data: dict):
        handler_entry_span = trace.get_current_span()
        if handler_entry_span and handler_entry_span.is_recording():
            ctx = handler_entry_span.get_span_context()
            parent_id_str = f"{handler_entry_span.parent.span_id:x}" if handler_entry_span.parent else "None"
            logger.info(
                f"ProductManager.handle_order_success: ENTRY - TraceID={ctx.trace_id:x}, "
                f"SpanID={ctx.span_id:x}, ParentSpanID={parent_id_str}, IsRemote={ctx.is_remote}"
            )
            # 여기서 SpanID가 Jaeger UI에서 본 "dbserver.order receive" 스팬의 ID와 일치해야 함!
            # 그리고 TraceID는 order-service부터 쭉 이어져 온 그 ID여야 하고.
        else:
            # !!!!! 이 로그가 찍히면 컨텍스트 전파 실패 !!!!!
            logger.warning("ProductManager.handle_order_success: !!! No active/recording span at handler entry !!!")

        # 이 메서드는 _process_event_with_retries의 컨텍스트(스팬) 하에서 실행됨
        # tracer = trace.get_tracer(__name__) # 필요시 여기서 다시 얻기
        with self.tracer.start_as_current_span(
            "ProductManager._handle_order_success_logic"
        ) as span:
            items = event_data.get("items", [])
            order_id = event_data.get("order_id", "unknown_order_id")
            span.set_attribute("app.order_id", str(order_id))
            span.set_attribute("app.items_count", len(items))
            if not items:
                logger.warning(f"No items found in 'order_success' event for order {order_id}. Nothing to confirm.")
                span.set_status(Status(StatusCode.OK, "No items to confirm"))
                return # 아이템 없으면 처리할 것 없음 (에러는 아님)

            product_service = ProductService()  # ProductService 인스턴스화 (DI 고려)
            for item_idx, item_data in enumerate(items):
                # 각 아이템 처리를 위한 자식 스팬 생성
                with self.tracer.start_as_current_span("ProductManager._handle_order_success_logic_details") as span:
                    product_id = item_data.get("product_id")
                    quantity = item_data.get("quantity")
                    item_span.set_attribute("app.product_id", str(product_id))
                    item_span.set_attribute("app.quantity", quantity)

                    if not product_id or not isinstance(quantity, (int, float)) or quantity <= 0:
                        logger.warning(f"Invalid item data in order_success: {item_data}. Skipping.")
                        item_span.set_status(Status(StatusCode.ERROR, "Invalid item data for stock confirmation"))
                        continue

                    logger.info(f"Confirming inventory for product {product_id}, quantity {quantity} (Order: {order_id})")
                    # ProductService.confirm_inventory 내부에서도 자체 스팬 생성 권장
                    success = await product_service.confirm_inventory(
                        product_id=str(product_id), quantity=int(quantity)
                    )
                    if success:
                        logger.info(f"Inventory confirmed for product {product_id}, quantity {quantity}.")
                        item_span.set_status(Status(StatusCode.OK))
                    else:
                        # 이 경우 SAGA 보상 로직이 복잡해질 수 있음 (이미 주문/결제는 성공)
                        # 데이터 불일치 가능성이므로 심각하게 로깅하고 알림 필요.
                        logger.error(f"Failed to confirm inventory for product {product_id}, quantity {quantity} for SUCCESSFUL order {order_id}.")
                        item_span.set_status(Status(StatusCode.ERROR,"Inventory confirmation failed unexpectedly"))
                        # 여기서 전체 트랜잭션 실패로 간주하고 보상 이벤트를 발행해야 할 수도 있음

    async def handle_order_success(self, event_data: dict):
        await self._process_event_with_retries(
            event_name="order_success",
            event_data=event_data,
            handler_logic_method=self._handle_order_success_logic,
            compensation_method=self.create_compensation_event # 예시 보상 핸들러
        )

    async def _handle_order_failed_logic(self, event_data: dict):
        # tracer = trace.get_tracer(__name__)
        with self.tracer.start_as_current_span(
            "ProductManager._handle_order_failed_logic"
        ) as span:
            items = event_data.get("items", [])
            order_id = event_data.get("order_id", "unknown_order_id")
            span.set_attribute("app.order_id", str(order_id))
            span.set_attribute("app.items_count", len(items))

            if not items:
                logger.warning(f"No items found in 'order_failed' event for order {order_id}. Nothing to release.")
                span.set_status(Status(StatusCode.OK, "No items to release"))
                return

            product_service = ProductService()
            for item_idx, item_data in enumerate(items):
                with self.tracer.start_as_current_span(
                    f"release_inventory_item_{item_idx}"
                ) as item_span:
                    product_id = item_data.get("product_id")
                    quantity = item_data.get("quantity")
                    item_span.set_attribute("app.product_id", str(product_id))
                    item_span.set_attribute("app.quantity", quantity)

                    if not product_id or not isinstance(quantity, (int, float)) or quantity <= 0:
                        logger.warning(f"Invalid item data in order_failed: {item_data}. Skipping release.")
                        item_span.set_status(Status(StatusCode.ERROR, "Invalid item data for stock release"))
                        continue
                    
                    logger.info(f"Releasing reserved inventory for product {product_id}, quantity {quantity} (Order: {order_id})")
                    success = await product_service.release_inventory(
                        product_id=str(product_id), quantity=int(quantity)
                    )
                    if success:
                        logger.info(f"Inventory released for product {product_id}, quantity {quantity}.")
                        item_span.set_status(Status(StatusCode.OK))
                    else:
                        logger.error(f"Failed to release inventory for product {product_id}, quantity {quantity} for FAILED order {order_id}.")
                        item_span.set_status(Status(StatusCode.ERROR,"Inventory release failed"))


    async def handle_order_failed(self, event_data: dict):
        await self._process_event_with_retries(
            event_name="order_failed",
            event_data=event_data,
            handler_logic_method=self._handle_order_failed_logic,
            # order_failed 처리 실패 시 보상 로직은 보통 없음 (이미 실패 흐름)
            # 하지만 로깅/알림은 중요
            compensation_method=lambda data, type, reason: self._store_failed_event(type, data, reason) # 예시: 실패 이벤트 저장
        )

    async def create_compensation_event(self, original_event_data: dict, failure_type: str, reason: str):
        # tracer = trace.get_tracer(__name__)
        with self.tracer.start_as_current_span(
            "ProductManager.create_compensation_outbox_event"
        ) as span:
            order_id = original_event_data.get("order_id", "unknown")
            span.set_attribute("app.original_order_id", str(order_id))
            span.set_attribute("app.compensation.failure_type", failure_type)
            span.set_attribute("app.compensation.reason", reason)
            logger.info(f"ProductManager: Creating compensation event for order '{order_id}' due to '{failure_type}': {reason}")
            
            try:
                async with WriteSessionLocal() as session: # Product 모듈의 DB 세션 사용
                    async with session.begin():
                        compensation_payload = {
                            "type": f"{failure_type}_compensation_needed", # 보상 이벤트 타입
                            "original_order_id": str(order_id),
                            "reason_for_compensation": reason,
                            "original_event_preview": json.dumps(original_event_data, ensure_ascii=False)[:256],
                            "timestamp": datetime.datetime.utcnow().isoformat(timespec="microseconds") + "Z",
                        }

                        current_otel_span = trace.get_current_span()
                        context_to_propagate = trace.set_span_in_context(current_otel_span)
                        carrier = {}
                        propagator_instance = propagate.get_global_textmap()
                        propagator_instance.inject(carrier, context=context_to_propagate)
                        span.add_event("TraceContextInjectedToCarrierForCompensationOutbox", {"traceparent": carrier.get('traceparent')})

                        outbox_record = Outbox( # Product 모듈의 Outbox 모델 사용
                            id=str(uuid.uuid4()),
                            aggregatetype="product_compensation", # 또는 "order_compensation_from_product"
                            aggregateid=str(order_id), # 또는 새로운 보상 ID
                            type=compensation_payload["type"],
                            payload=json.dumps(compensation_payload), # JSON 문자열로 저장
                            traceparent_for_header=carrier.get("traceparent"),
                            tracestate_for_header=carrier.get("tracestate"),
                        )
                        session.add(outbox_record)
                        logger.info(f"Compensation event for order '{order_id}' added to ProductModule's Outbox.")
                        span.set_status(Status(StatusCode.OK))
            except Exception as e:
                error_msg = f"CRITICAL: Failed to create compensation event for order '{order_id}' in ProductModule: {e}"
                logger.critical(error_msg, exc_info=True)
                if span.is_recording():
                    span.record_exception(e)
                    span.set_status(Status(StatusCode.ERROR, "Failed to write compensation to ProductOutbox"))


    async def _store_failed_event(self, event_type: str, event_data: dict, error_msg: str):
        # 이 함수는 Product 모듈의 FailedEvent 모델을 사용해야 함 (별도 구현 필요 시)
        # tracer = trace.get_tracer(__name__)
        with self.tracer.start_as_current_span("ProductManager._store_failed_event_in_product_db") as span:
            logger.warning(f"ProductManager: Storing failed event of type '{event_type}'. Error: {error_msg}. Data: {str(event_data)[:200]}")
            # ... (Product 모듈 DB에 실패 이벤트 저장 로직) ...
            span.set_attribute("app.failed_event.type", event_type)

    async def stop(self):
        if self.kafka_consumer:
            await self.kafka_consumer.stop()
        logger.info("ProductManager (and its ProductModuleKafkaConsumer) stopped.")