# fastapi-order/app/config/kafka_consumer.py
from aiokafka import AIOKafkaConsumer
import asyncio
import json
import logging
from typing import Callable, Dict, List # List 추가

from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode # SpanKind는 자동 계측 시 직접 사용 줄임
from opentelemetry.semconv.trace import SpanAttributes # 필요시 표준 속성 사용

logger = logging.getLogger(__name__) # 모듈 로거

class OrderModuleKafkaConsumer:
    def __init__(self, bootstrap_servers: str, group_id: str):
        self.bootstrap_servers = bootstrap_servers
        self.group_id = group_id
        self.consumer: AIOKafkaConsumer = None
        # 토픽별, 이벤트 타입별 핸들러 저장: Dict[topic_name, Dict[event_type, handler_callable]]
        self.handlers: Dict[str, Dict[str, Callable]] = {}
        self.tracer = trace.get_tracer("app.config.order_kafka_consumer.OrderModuleKafkaConsumer", "0.1.0")
        self._running = False
        logger.info(f"OrderModuleKafkaConsumer initialized for group '{self.group_id}'")

    def register_handler(self, topic: str, event_type: str, handler: Callable):
        if topic not in self.handlers:
            self.handlers[topic] = {}
        self.handlers[topic][event_type] = handler
        logger.info(f"[{self.group_id}] Handler registered: topic='{topic}', event_type='{event_type}', handler='{handler.__name__}'")

    async def start(self):
        if self._running:
            logger.warning(f"[{self.group_id}] OrderModuleKafkaConsumer.start called but already running.")
            return

        subscribed_topics = list(self.handlers.keys())
        if not subscribed_topics:
            logger.warning(f"[{self.group_id}] No topics to subscribe to for OrderModule. Consumer not starting.")
            return

        with self.tracer.start_as_current_span(f"{self.group_id}.OrderModuleKafkaConsumer.start_instance") as span:
            span.set_attribute("app.kafka.consumer_group", self.group_id)
            span.set_attribute("app.kafka.bootstrap_servers", self.bootstrap_servers)
            span.set_attribute("app.kafka.subscribed_topics", ",".join(subscribed_topics))
            try:
                self.consumer = AIOKafkaConsumer(
                    *subscribed_topics, # 구독할 모든 토픽
                    bootstrap_servers=self.bootstrap_servers,
                    group_id=self.group_id,
                    auto_offset_reset='latest',
                    # value_deserializer: bytes -> str (JSON 파싱은 _consume_loop에서)
                    value_deserializer=lambda m: m.decode('utf-8', errors='replace') if isinstance(m, (bytes, bytearray)) else str(m),
                    enable_auto_commit=False # 수동 커밋
                )
                await self.consumer.start()
                self._running = True
                asyncio.create_task(self._consume_loop())
                logger.info(f"[{self.group_id}] Kafka consumer task created for topics: {subscribed_topics}.")
                span.set_status(Status(StatusCode.OK))
            except Exception as e:
                logger.error(f"[{self.group_id}] Failed to start OrderModuleKafkaConsumer: {e}", exc_info=True)
                if span.is_recording():
                    span.record_exception(e)
                    span.set_status(Status(StatusCode.ERROR, f"KafkaConsumerStartFailed: {str(e)}"))
                self._running = False
                raise

    async def _consume_loop(self):
        if not self.consumer:
            logger.error(f"[{self.group_id}] Consumer not initialized for OrderModule.")
            return

        logger.info(f"[{self.group_id}] Starting consumption loop for OrderModule, topics: {list(self.handlers.keys())}...")
        try:
            # AIOKafkaInstrumentor가 이 루프에서 각 메시지 수신 시 자동으로 CONSUMER 스팬을 생성하고,
            # 메시지 헤더에서 traceparent를 읽어 컨텍스트를 활성화합니다.
            async for msg in self.consumer:
                # 현재 스팬은 AIOKafkaInstrumentor가 만든 CONSUMER 스팬이어야 합니다.
                current_consumer_span = trace.get_current_span()
                
                logger.info(f"!!!!!!!!!! [{self.group_id}] ORDER-MODULE KAFKA MSG RECEIVED !!!!!!!!!!")
                logger.info(f"[{self.group_id}] Topic={msg.topic}, Offset={msg.offset}, Key={msg.key.decode('utf-8', errors='ignore') if msg.key else 'N/A'}")

                # AIOKafkaInstrumentor가 설정한 기본 속성에 추가적인 앱 레벨 속성을 더할 수 있습니다.
                if current_consumer_span.is_recording():
                    current_consumer_span.set_attribute(SpanAttributes.MESSAGING_MESSAGE_ID, str(msg.offset))
                    # 기타 필요한 속성 추가

                event_type_from_header = None
                header_log_for_debug = {}
                if msg.headers:
                    for key, value_bytes in msg.headers:
                        decoded_value = value_bytes.decode('utf-8', errors='replace') if value_bytes is not None else None
                        header_log_for_debug[key] = decoded_value
                        if key == 'eventType' and decoded_value: # Debezium SMT가 설정하는 표준 헤더명
                            event_type_from_header = decoded_value
                    logger.info(f"[{self.group_id}] Decoded Kafka Headers (OrderModule): {header_log_for_debug}")
                    if current_consumer_span.is_recording() and event_type_from_header:
                        current_consumer_span.set_attribute("app.kafka.header.eventType", event_type_from_header)
                
                raw_payload_str = msg.value # value_deserializer는 문자열로 변환
                actual_message_payload = None

                if isinstance(raw_payload_str, str):
                    logger.info(f"[{self.group_id}] Raw string payload from Kafka (repr): {repr(raw_payload_str)}")
                    try:
                        parsed_payload = json.loads(raw_payload_str)
                        if isinstance(parsed_payload, str): # 이중 인코딩 체크
                            logger.warning(f"[{self.group_id}] Payload from topic {msg.topic} was double-encoded. Second parse attempt.")
                            actual_message_payload = json.loads(parsed_payload)
                        else:
                            actual_message_payload = parsed_payload
                    except json.JSONDecodeError as e_json:
                        logger.error(f"[{self.group_id}] Failed to parse JSON from topic {msg.topic}. Raw: {raw_payload_str[:500]}, Error: {e_json}. Skipping.")
                        if current_consumer_span.is_recording(): current_consumer_span.set_status(Status(StatusCode.ERROR, "Payload JSON parse failed"))
                        await self.consumer.commit()
                        continue
                else: # value_deserializer가 문자열을 반환하지 않은 예외적 상황
                    logger.error(f"[{self.group_id}] Expected string payload from deserializer for topic {msg.topic}, got {type(raw_payload_str)}. Skipping.")
                    if current_consumer_span.is_recording(): current_consumer_span.set_status(Status(StatusCode.ERROR, "Payload not string from deserializer"))
                    await self.consumer.commit()
                    continue
                
                if not isinstance(actual_message_payload, dict):
                    logger.error(f"[{self.group_id}] Final payload is NOT dict ({type(actual_message_payload)}) for topic {msg.topic}. Skipping.")
                    if current_consumer_span.is_recording(): current_consumer_span.set_status(Status(StatusCode.ERROR, "Final payload not dict"))
                    await self.consumer.commit()
                    continue
                
                # 최종 이벤트 타입 결정
                final_event_type = event_type_from_header or actual_message_payload.get('type')
                
                if not final_event_type:
                    logger.error(f"[{self.group_id}] Could not determine event_type for topic {msg.topic}. Payload: {str(actual_message_payload)[:200]}. Skipping.")
                    if current_consumer_span.is_recording(): current_consumer_span.set_status(Status(StatusCode.ERROR, "EventType missing in message"))
                    await self.consumer.commit()
                    continue
                
                if current_consumer_span.is_recording():
                    current_consumer_span.set_attribute("app.event_type_resolved", final_event_type)
                    # AIOKafkaInstrumentor가 생성한 스팬의 이름을 더 구체적으로 업데이트 할 수 있습니다.
                    # current_consumer_span.update_name(f"{msg.topic} {final_event_type} process")

                topic_handlers = self.handlers.get(msg.topic)
                if not topic_handlers or final_event_type not in topic_handlers:
                    logger.warning(f"[{self.group_id}] No handler for topic '{msg.topic}', event_type '{final_event_type}'. Skipping.")
                    if current_consumer_span.is_recording(): current_consumer_span.set_status(Status(StatusCode.OK, f"NoHandlerFor_{final_event_type}"))
                    await self.consumer.commit()
                    continue
                
                handler_to_call = topic_handlers[final_event_type]

                logger.info(f"[{self.group_id}] Calling handler '{handler_to_call.__name__}' for event '{final_event_type}' from topic '{msg.topic}'...")
                try:
                    # 핸들러는 AIOKafkaInstrumentor가 활성화한 컨텍스트 내에서 실행됩니다.
                    # 핸들러 (예: OrderManager.handle_payment_success) 내부에서 생성하는 스팬은 자동으로 자식 스팬이 됩니다.
                    await handler_to_call(actual_message_payload) 
                    logger.info(f"[{self.group_id}] Handler for event '{final_event_type}' completed successfully.")
                    if current_consumer_span.is_recording():
                        current_consumer_span.set_status(Status(StatusCode.OK))
                except Exception as e_handler:
                    logger.error(f"[{self.group_id}] Error in handler '{handler_to_call.__name__}' for event '{final_event_type}': {e_handler}", exc_info=True)
                    if current_consumer_span.is_recording():
                        current_consumer_span.record_exception(e_handler)
                        current_consumer_span.set_status(Status(StatusCode.ERROR, f"HandlerFailed: {str(e_handler)}"))
                
                await self.consumer.commit() # 메시지 처리 후 수동 커밋
                logger.info(f"[{self.group_id}] Offset {msg.offset} committed for topic {msg.topic} after event '{final_event_type}'.")

        except asyncio.CancelledError:
            logger.info(f"Consume loop cancelled for group '{self.group_id}' in OrderModule.")
        except Exception as e_loop:
            logger.error(f"CRITICAL Kafka consumer loop error for group '{self.group_id}' in OrderModule: {e_loop}", exc_info=True)
            self._running = False
        finally:
            logger.info(f"Consume loop ending for group '{self.group_id}' in OrderModule.")
            if self._running:
                await self.stop()

    async def stop(self):
        if not self._running and not self.consumer:
            logger.info(f"[{self.group_id}] OrderModuleKafkaConsumer.stop called but not running or not initialized.")
            return
        
        tracer_for_stop = self.tracer # Use existing tracer
        with tracer_for_stop.start_as_current_span(f"{self.group_id}.OrderModuleKafkaConsumer.stop_instance") as span:
            # ... (이전 payment_kafka.py의 stop 메서드와 동일한 로직)
            try:
                current_running_status = self._running
                self._running = False 

                if self.consumer:
                    logger.info(f"[{self.group_id}] Stopping OrderModuleKafkaConsumer (was running: {current_running_status})...")
                    await self.consumer.stop()
                    logger.info(f"[{self.group_id}] OrderModuleKafkaConsumer stopped successfully.")
                    self.consumer = None 
                else:
                    logger.info(f"[{self.group_id}] OrderModuleKafkaConsumer was already None (was running: {current_running_status}).")
                
                span.set_status(Status(StatusCode.OK))
            except Exception as e:
                logger.error(f"[{self.group_id}] Error stopping OrderModuleKafkaConsumer: {e}", exc_info=True)
                if span.is_recording():
                    span.record_exception(e)
                    span.set_status(Status(StatusCode.ERROR, f"KafkaConsumerStopFailed: {str(e)}"))