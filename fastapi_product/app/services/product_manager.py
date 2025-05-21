# product_manager.py

from app.config.kafka_consumer import KafkaConsumer
from app.services.product_service import ProductService
from app.config.database import WriteSessionLocal
from app.models.outbox import Outbox
import uuid
import json
from app.config.logging import logger
import asyncio
import datetime

from opentelemetry import trace, context as otel_context
from opentelemetry.trace import SpanKind, Status, StatusCode, Link # SpanKind 필요
from opentelemetry.semconv.trace import SpanAttributes


class ProductManager:
    def __init__(self):
        self.kafka_consumer: KafkaConsumer = None # 타입 명시
        self.max_retries = 3
        self.tracer = trace.get_tracer("app.product_manager.ProductManager", "0.1.0")

    async def initialize_kafka(self, bootstrap_servers: str, group_id: str):
        with self.tracer.start_as_current_span("product_manager.initialize_kafka") as span:
            span.set_attribute("kafka.bootstrap_servers", bootstrap_servers)
            span.set_attribute("kafka.group_id", group_id)
            try:
                # ProductManager가 구독할 토픽 리스트 정의
                # 예시: 실제 이벤트 핸들러와 매핑될 토픽들
                subscribed_topics = ['order_topic_for_success', 'order_topic_for_failure'] # 실제 토픽명으로 변경
                # 또는 핸들러 이름으로 토픽을 유추하거나, 설정에서 가져올 수 있음
                # self.kafka_consumer.register_handler 호출 시 토픽 정보도 같이 관리하는 방법도 있음

                self.kafka_consumer = KafkaConsumer(
                    bootstrap_servers=bootstrap_servers,
                    group_id=group_id,
                    topics=subscribed_topics # KafkaConsumer에 토픽 리스트 전달
                )

                # 핸들러 등록 (이벤트 타입과 실제 핸들러 메서드 매핑)
                # 여기서 'order_success'는 Kafka 메시지 헤더의 'eventType' 또는 페이로드의 'type'과 일치해야 함
                self.kafka_consumer.register_handler('order_success', self.handle_order_success)
                self.kafka_consumer.register_handler('order_failed', self.handle_order_failed)
                
                await self.kafka_consumer.start()
                logger.info(f"Kafka consumer initialized by ProductManager for group '{group_id}'.")
                span.set_status(Status(StatusCode.OK))
            except Exception as e:
                logger.error(f"ProductManager: Failed to initialize Kafka consumer: {e}", exc_info=True)
                span.record_exception(e)
                span.set_status(Status(StatusCode.ERROR, "Kafka initialization failed in ProductManager"))
                raise
    
    async def _process_event_with_retries(self, event_name: str, event_data: dict, handler_method, compensation_method=None):
        # 이 스팬은 KafkaConsumer.consume_messages 에서 만든 부모 CONSUMER 스팬의 자식으로 생성됨.
        # SpanKind.CONSUMER는 KafkaConsumer 쪽에서 설정했으므로, 여기서는 INTERNAL 이 적절.
        with self.tracer.start_as_current_span(
            f"product_manager.handle_event.{event_name}", # 스팬 이름 변경 (역할 명확화)
            kind=trace.SpanKind.INTERNAL # Kafka 메시지 수신 자체는 KafkaConsumer가 담당
        ) as span:
            # MessagingSpanAttributes 관련 코드는 KafkaConsumer로 이동했으므로 여기서는 제거.
            # 필요한 애플리케이션 레벨 속성만 설정.
            span.set_attribute("app.event_name_being_handled", event_name) # 처리할 이벤트 이름 명시
            order_id = event_data.get('order_id', event_data.get('original_order_id', 'unknown_order')) # 보상 이벤트도 고려
            span.set_attribute("app.order_id", order_id)
            # event_data 전체를 로깅하거나 속성으로 넣는 것은 크기/민감도 주의. 필요한 부분만.
            span.set_attribute("app.event_data_keys_preview", str(list(event_data.keys()))[:100])


            retry_count = 0
            last_exception = None
            # 루프 조건 수정: retry_count는 0부터 시작해서 max_retries까지 시도 (총 max_retries + 1번)
            while retry_count <= self.max_retries:
                current_attempt = retry_count + 1 # 실제 시도 횟수 (1부터 시작)
                span.set_attribute("app.retry_attempt", current_attempt)
                try:
                    logger.info(f"Processing '{event_name}' for order '{order_id}', attempt {current_attempt}/{self.max_retries + 1}.")
                    
                    # 핸들러 메서드에 현재 스팬(자식 스팬 만들 때 부모로 사용 가능) 전달
                    await handler_method(event_data, span) 
                    
                    span.set_status(Status(StatusCode.OK))
                    logger.info(f"Successfully processed '{event_name}' for order '{order_id}' on attempt {current_attempt}.")
                    return # 성공 시 루프 종료
                except ValueError as ve: # 데이터 유효성 검사 에러 (재시도 무의미)
                    error_msg = f"Data error processing '{event_name}' for order '{order_id}' (attempt {current_attempt}): {ve}"
                    logger.error(error_msg, exc_info=True)
                    span.record_exception(ve)
                    span.set_status(Status(StatusCode.ERROR, error_msg))
                    span.set_attribute("app.error.type", "validation_error")
                    if compensation_method:
                        # 보상 이벤트 생성 시에도 현재 스팬 컨텍스트가 전파됨
                        await compensation_method(event_data, f"Data error: {ve}")
                    return # 재시도 없이 종료
                except Exception as e: # 기타 재시도 가능한 에러
                    last_exception = e
                    retry_count += 1 # 다음 시도를 위해 증가
                    error_message = f"Error processing '{event_name}' for order '{order_id}' (attempt {current_attempt} failed, next: {retry_count+1 if retry_count <= self.max_retries else 'max_retries_exceeded'}): {e}"
                    logger.error(error_message, exc_info=True)
                    span.record_exception(e) # 각 재시도 실패 시 예외 기록
                    span.add_event("handler_retry_exception", {
                        "exception.message": str(e),
                        "retry.attempt_number_failed": current_attempt
                    })

                    if retry_count > self.max_retries: # 모든 재시도 소진
                        final_error_msg = f"CRITICAL: Failed to process '{event_name}' for order '{order_id}' after {self.max_retries + 1} attempts. Last error: {last_exception}"
                        logger.critical(final_error_msg)
                        span.set_status(Status(StatusCode.ERROR, final_error_msg))
                        span.set_attribute("app.error.type", "max_retries_exceeded")
                        if compensation_method:
                            await compensation_method(event_data, f"Max retries exceeded: {last_exception}")
                        return # 모든 재시도 실패, 루프 종료
                    
                    sleep_duration = 2 ** (retry_count -1) # 1, 2, 4... (첫 재시도(retry_count=1)에 1초)
                    span.add_event("retrying_handler", {"sleep_duration_seconds": sleep_duration, "next_retry_attempt_number": current_attempt +1})
                    logger.info(f"Retrying '{event_name}' for order '{order_id}' in {sleep_duration}s (attempt {current_attempt +1})...")
                    await asyncio.sleep(sleep_duration)

    # _handle_order_success_logic, _handle_order_failed_logic, create_compensation_event, stop 메서드는
    # 이전 답변과 유사하게 OTel 적용 (span.set_attribute, logger, record_exception, set_status 등)
    # 이 메서드들은 _process_event_with_retries 스팬의 자식으로 스팬을 만들 수 있음.
    # 예: _handle_order_success_logic 안의 for 루프에서 만드는 아이템별 스팬은 그대로 유효.
    # create_compensation_event 안의 스팬도 그대로 유효.
    
    # ... (이하 _handle_order_success_logic, _handle_order_failed_logic, create_compensation_event, stop 메서드 코드 - 이전 답변 참고하여 OTel 적용)
    # _handle_order_success_logic 예시 (큰 변화 없음, parent_span 활용)
    async def _handle_order_success_logic(self, event_data: dict, parent_span: trace.Span): # parent_span 인자 유지
        parent_span.set_attribute("app.items_count", len(event_data.get('items', [])))
        items = event_data.get('items', [])
        if not items:
            raise ValueError("No items found in order_success event")

        for item_idx, item in enumerate(items):
            # 이 스팬은 _process_event_with_retries 스팬의 자식이 됨
            with self.tracer.start_as_current_span(f"product_manager.handle_order_success.process_item_{item_idx}", kind=trace.SpanKind.INTERNAL) as item_span:
                product_id = item.get('product_id')
                quantity = item.get('quantity')
                
                item_span.set_attribute("app.item.product_id", product_id)
                item_span.set_attribute("app.item.quantity", quantity)

                if not product_id or not isinstance(quantity, (int, float)) or quantity <= 0:
                    logger.warning(f"Invalid item data in order_success: {item}. Skipping.")
                    item_span.set_status(Status(StatusCode.ERROR, "Invalid item data"))
                    item_span.set_attribute("app.item.status", "skipped_invalid_data")
                    continue
                
                product_service = ProductService()
                logger.info(f"Calling confirm_inventory for product {product_id}, quantity {quantity}")
                # product_service.confirm_inventory 내부에서도 OTel 스팬이 생성될 수 있음 (예: DB 작업)
                await product_service.confirm_inventory(product_id=product_id, quantity=quantity)
                logger.info(f"Confirmed inventory for product {product_id}, quantity {quantity}")
                item_span.set_status(Status(StatusCode.OK))
    
    # handle_order_success, handle_order_failed는 _process_event_with_retries를 호출하므로 큰 변경 없음
    async def handle_order_success(self, event_data: dict):
        await self._process_event_with_retries(
            event_name='order_success',
            event_data=event_data,
            handler_method=self._handle_order_success_logic,
            compensation_method=lambda data, reason: self.create_compensation_event(data, "order_success_processing_failed", reason)
        )

    async def _handle_order_failed_logic(self, event_data: dict, parent_span: trace.Span):
        parent_span.set_attribute("app.items_count", len(event_data.get('items', [])))
        items = event_data.get('items', [])
        if not items:
            raise ValueError("No items found in order_failed event")

        for item_idx, item in enumerate(items):
            with self.tracer.start_as_current_span(f"product_manager.handle_order_failed.process_item_{item_idx}", kind=trace.SpanKind.INTERNAL) as item_span:
                product_id = item.get('product_id')
                quantity = item.get('quantity')

                item_span.set_attribute("app.item.product_id", product_id)
                item_span.set_attribute("app.item.quantity", quantity)

                if not product_id or not isinstance(quantity, (int, float)) or quantity <= 0:
                    logger.warning(f"Invalid item data in order_failed: {item}. Skipping.")
                    item_span.set_status(Status(StatusCode.ERROR, "Invalid item data"))
                    item_span.set_attribute("app.item.status", "skipped_invalid_data")
                    continue
                
                product_service = ProductService()
                logger.info(f"Calling release_inventory for product {product_id}, quantity {quantity}")
                await product_service.release_inventory(product_id=product_id, quantity=quantity)
                logger.info(f"Released inventory for product {product_id}, quantity {quantity}")
                item_span.set_status(Status(StatusCode.OK))

    async def handle_order_failed(self, event_data: dict):
        await self._process_event_with_retries(
            event_name='order_failed',
            event_data=event_data,
            handler_method=self._handle_order_failed_logic,
            compensation_method=lambda data, reason: self.create_compensation_event(data, "order_failed_processing_failed", reason)
        )
    
    async def create_compensation_event(self, original_event: dict, failure_type: str, reason: str):
        with self.tracer.start_as_current_span("product_manager.create_compensation_event", kind=trace.SpanKind.INTERNAL) as span:
            # ... (이전 답변의 로직과 OTel 속성 설정 유지) ...
            order_id = original_event.get('order_id', original_event.get('original_order_id', 'unknown_order'))
            span.set_attribute("app.original_event.order_id", order_id)
            span.set_attribute("app.compensation.failure_type", failure_type)
            span.set_attribute("app.compensation.reason", reason)
            logger.info(f"Attempting to create compensation event for order '{order_id}' due to '{failure_type}': {reason}")
            try:
                async with WriteSessionLocal() as session:
                    async with session.begin():
                        items = original_event.get('items', [])
                        compensation_payload = {
                            'original_order_id': order_id,
                            'original_event_type': failure_type.split('_processing_failed')[0] if '_processing_failed' in failure_type else failure_type,
                            'failed_items': items,
                            'failure_reason': reason,
                            'compensation_event_type': f"{failure_type}_compensation_required",
                            'timestamp': datetime.datetime.now(datetime.timezone.utc).isoformat()
                        }
                        outbox_event_id = str(uuid.uuid4())
                        outbox_event = Outbox(
                            id=outbox_event_id,
                            aggregatetype="product_compensation", # 좀 더 구체적으로
                            aggregateid=str(order_id),
                            type=compensation_payload['compensation_event_type'],
                            payload=json.dumps(compensation_payload)
                        )
                        session.add(outbox_event)
                        await session.flush()
                        span.set_attribute("app.outbox_event.id", outbox_event_id)
                        span.set_attribute("app.outbox_event.type", outbox_event.type)
                        logger.info(f"Compensation event for order '{order_id}' (Outbox ID: {outbox_event_id}) added to outbox.")
                        span.set_status(Status(StatusCode.OK))
            except Exception as e:
                error_msg = f"CRITICAL: Failed to create compensation event for order '{order_id}': {e}"
                logger.critical(error_msg, exc_info=True)
                span.record_exception(e)
                span.set_status(Status(StatusCode.ERROR, "Failed to write compensation to outbox"))

    async def stop(self):
        if self.kafka_consumer:
            # KafkaConsumer.stop() 내부에도 이미 트레이싱이 적용되어 있음
            await self.kafka_consumer.stop()
        logger.info("ProductManager (and its KafkaConsumer) stopped.")