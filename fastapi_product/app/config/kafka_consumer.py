# fastapi-product/app/config/kafka_consumer.py
from aiokafka import AIOKafkaConsumer
import asyncio
import json
import logging
from typing import Callable, Dict, List

from opentelemetry import trace, propagate # propagate 임포트
from opentelemetry.trace import Status, StatusCode, SpanKind # SpanKind 사용
from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator
from opentelemetry.semconv.trace import SpanAttributes

logger = logging.getLogger(__name__)

class ProductModuleKafkaConsumer:
    def __init__(self, bootstrap_servers: str, group_id: str, topics: List[str]):
        self.bootstrap_servers = bootstrap_servers
        self.group_id = group_id
        self.topics_to_subscribe = topics
        self.consumer: AIOKafkaConsumer = None
        self.handlers: Dict[str, Callable] = {} # event_type -> handler
        self.tracer = trace.get_tracer("app.config.product_kafka_consumer.ProductModuleKafkaConsumer", "0.1.0")
        self._running = False
        logger.info(f"ProductModuleKafkaConsumer initialized for group '{self.group_id}' to subscribe to {self.topics_to_subscribe}")

    def register_handler(self, event_type: str, handler: Callable):
        self.handlers[event_type] = handler
        logger.info(f"[{self.group_id}] Handler registered for event_type='{event_type}', handler='{handler.__name__}'")

    async def start(self):
        if self._running:
            logger.warning(f"[{self.group_id}] ProductModuleKafkaConsumer.start called but already running.")
            return
        if not self.topics_to_subscribe:
            logger.warning(f"[{self.group_id}] No topics to subscribe to. Consumer not starting.")
            return

        with self.tracer.start_as_current_span(f"{self.group_id}.ProductModuleKafkaConsumer.start_instance") as span:
            span.set_attribute("app.kafka.consumer_group", self.group_id)
            span.set_attribute("app.kafka.subscribed_topics", ",".join(self.topics_to_subscribe))
            try:
                self.consumer = AIOKafkaConsumer(
                    *self.topics_to_subscribe,
                    bootstrap_servers=self.bootstrap_servers,
                    group_id=self.group_id,
                    auto_offset_reset='latest',
                    value_deserializer=lambda m: m.decode('utf-8', errors='replace') if isinstance(m, (bytes, bytearray)) else str(m), # bytes -> str
                    enable_auto_commit=False
                )
                await self.consumer.start()
                self._running = True
                asyncio.create_task(self._consume_loop())
                logger.info(f"[{self.group_id}] Kafka consumer task created for topics: {self.topics_to_subscribe}.")
                span.set_status(Status(StatusCode.OK))
            except Exception as e:
                logger.error(f"[{self.group_id}] Failed to start ProductModuleKafkaConsumer: {e}", exc_info=True)
                if span.is_recording(): span.record_exception(e); span.set_status(Status(StatusCode.ERROR, str(e)))
                self._running = False
                raise

    async def _consume_loop(self):
        if not self.consumer:
            logger.error(f"[{self.group_id}] Consumer not initialized for ProductModule.")
            return

        logger.info(f"[{self.group_id}] Starting consumption loop for ProductModule, topics: {self.topics_to_subscribe}...")
        propagator = TraceContextTextMapPropagator() # 컨텍스트 추출기

        try:
            async for msg in self.consumer:
                logger.info(f"!!!!!!!!!! [{self.group_id}] PRODUCT-MODULE KAFKA MSG RECEIVED !!!!!!!!!!")
                logger.info(f"[{self.group_id}] Topic={msg.topic}, Offset={msg.offset}")

                carrier = {}
                header_log_for_debug = {}
                if msg.headers:
                    for key, value_bytes in msg.headers:
                        decoded_value = value_bytes.decode('utf-8', errors='replace') if value_bytes is not None else None
                        header_log_for_debug[key] = decoded_value
                        if key.lower() == 'traceparent' and decoded_value:
                            carrier['traceparent'] = decoded_value
                        elif key.lower() == 'tracestate' and decoded_value:
                            carrier['tracestate'] = decoded_value
                    logger.info(f"[{self.group_id}] Decoded Kafka Headers (ProductModule): {header_log_for_debug}")
                    if 'traceparent' not in carrier:
                        logger.warning(f"[{self.group_id}] 'traceparent' header NOT FOUND in ProductModule. New trace will start.")
                else:
                    logger.warning(f"[{self.group_id}] NO KAFKA HEADERS found in ProductModule. New trace will start.")

                # Kafka 메시지 헤더에서 부모 컨텍스트 추출
                parent_context = propagator.extract(carrier=carrier)
                
                raw_payload_str = msg.value # value_deserializer가 bytes -> str로 변환한 상태
                actual_payload_to_handle = None

                # JSON 문자열을 dict로 파싱 (이중 인코딩 가능성 처리)
                if isinstance(raw_payload_str, str):
                    logger.info(f"[{self.group_id}] Raw string payload from Kafka (repr): {repr(raw_payload_str)}")
                    try:
                        parsed_payload = json.loads(raw_payload_str)
                        if isinstance(parsed_payload, str): # 이중 인코딩 체크
                            logger.warning(f"[{self.group_id}] Payload from topic {msg.topic} was double-encoded. Second parse.")
                            actual_payload_to_handle = json.loads(parsed_payload)
                        else:
                            actual_payload_to_handle = parsed_payload
                    except json.JSONDecodeError as e_json:
                        logger.error(f"[{self.group_id}] Failed to parse JSON from topic {msg.topic}. Error: {e_json}. Skipping.")
                        await self.consumer.commit()
                        continue
                else:
                    logger.error(f"[{self.group_id}] Expected string payload but got {type(raw_payload_str)}. Skipping.")
                    await self.consumer.commit()
                    continue
                
                if not isinstance(actual_payload_to_handle, dict):
                    logger.error(f"[{self.group_id}] Final payload is NOT dict ({type(actual_payload_to_handle)}). Skipping.")
                    await self.consumer.commit()
                    continue
                
                event_type_from_header = header_log_for_debug.get('eventType')
                final_event_type = event_type_from_header or actual_payload_to_handle.get('type')
                
                if not final_event_type:
                    logger.error(f"[{self.group_id}] Could not determine event_type for {msg.topic}. Skipping.")
                    await self.consumer.commit()
                    continue

                # AIOKafkaInstrumentor가 만든 CONSUMER 스팬을 기대하는 대신,
                # 여기서 명시적으로 컨텍스트를 사용하여 새 스팬을 시작.
                # 이 스팬이 사실상의 CONSUMER + PROCESS 스팬 역할을 함.
                with self.tracer.start_as_current_span(
                    name=f"{msg.topic} {final_event_type} process", # Jaeger UI에 표시될 스팬 이름
                    context=parent_context, # Kafka 헤더에서 추출한 컨텍스트를 부모로!
                    kind=SpanKind.CONSUMER, # 이 작업은 메시지를 소비해서 처리하는 것
                    attributes={
                        SpanAttributes.MESSAGING_SYSTEM: "kafka",
                        SpanAttributes.MESSAGING_DESTINATION_NAME: msg.topic,
                        SpanAttributes.MESSAGING_DESTINATION_KIND: "topic",
                        SpanAttributes.MESSAGING_OPERATION: "process", # "receive"는 계측기가, 이건 "process"
                        SpanAttributes.MESSAGING_MESSAGE_ID: str(msg.offset),
                        SpanAttributes.MESSAGING_KAFKA_PARTITION: msg.partition,
                        SpanAttributes.MESSAGING_KAFKA_CONSUMER_GROUP: self.group_id,
                        "app.event_type": final_event_type,
                        "app.message.key": msg.key.decode('utf-8', errors='ignore') if msg.key else None,
                    }
                ) as current_processing_span: # 이 스팬이 이제 활성화된 부모 스팬!
                    try:
                        try:
                            current_processing_span.set_attribute("app.message.payload_preview", json.dumps(actual_payload_to_handle, ensure_ascii=False)[:256])
                        except:
                            current_processing_span.set_attribute("app.message.payload_preview", str(actual_payload_to_handle)[:256])

                        logger.info(f"[{self.group_id}] Resolved final_event_type: '{final_event_type}' for message at offset {msg.offset}")

                        handler_to_call = self.handlers.get(final_event_type)
                        if handler_to_call:
                            logger.info(f"[{self.group_id}] Calling handler '{handler_to_call.__name__}' for event '{final_event_type}'...")
                            # 핸들러(ProductManager의 메서드)는 이 current_processing_span의 컨텍스트를 이어받음
                            await handler_to_call(actual_payload_to_handle)
                            logger.info(f"[{self.group_id}] Handler for event '{final_event_type}' completed successfully.")
                            current_processing_span.set_status(Status(StatusCode.OK))
                        else:
                            logger.warning(f"[{self.group_id}] No handler for event_type '{final_event_type}' (Topic: {msg.topic}). Skipping.")
                            current_processing_span.set_status(Status(StatusCode.OK, f"NoHandlerFor_{final_event_type}"))
                        
                    except Exception as e_handler:
                        logger.error(f"[{self.group_id}] Error in handler or processing for event '{final_event_type}': {e_handler}", exc_info=True)
                        if current_processing_span.is_recording():
                            current_processing_span.record_exception(e_handler)
                            current_processing_span.set_status(Status(StatusCode.ERROR, f"ProcessingFailed: {str(e_handler)}"))
                    
                    await self.consumer.commit()
                    logger.info(f"[{self.group_id}] Offset {msg.offset} committed for topic {msg.topic}.")

        except asyncio.CancelledError:
            logger.info(f"Consume loop cancelled for group '{self.group_id}' in ProductModule.")
        except Exception as e_loop: # 루프 자체의 심각한 에러 (예: Kafka 연결 끊김)
            logger.error(f"CRITICAL Kafka consumer loop error for group '{self.group_id}' in ProductModule: {e_loop}", exc_info=True)
            self._running = False # 루프 중단 표시
            # 이런 경우, 애플리케이션 레벨에서 재시작 로직이 필요할 수 있음
        finally:
            logger.info(f"Consume loop ending for group '{self.group_id}' in ProductModule.")
            if self._running: # 예외로 루프가 종료되었으나, 외부에서 stop()이 명시적으로 호출되지 않은 경우
                logger.warning(f"[{self.group_id}] ProductModule consume_messages loop exited unexpectedly. Attempting to stop consumer.")
                await self.stop() # 자원 정리

    async def stop(self):
        # ... (stop 메서드는 이전과 동일하게 유지, self.tracer 사용)
        if not self._running and not self.consumer:
            logger.info(f"[{self.group_id}] ProductModuleKafkaConsumer.stop called but not running or not initialized.")
            return
        
        tracer_for_stop = self.tracer
        with tracer_for_stop.start_as_current_span(f"{self.group_id}.ProductModuleKafkaConsumer.stop_instance") as span:
            try:
                current_running_status = self._running
                self._running = False 

                if self.consumer:
                    logger.info(f"[{self.group_id}] Stopping ProductModuleKafkaConsumer (was running: {current_running_status})...")
                    await self.consumer.stop()
                    logger.info(f"[{self.group_id}] ProductModuleKafkaConsumer stopped successfully.")
                    self.consumer = None 
                else:
                    logger.info(f"[{self.group_id}] ProductModuleKafkaConsumer was already None (was running: {current_running_status}).")
                
                span.set_status(Status(StatusCode.OK))
            except Exception as e:
                logger.error(f"[{self.group_id}] Error stopping ProductModuleKafkaConsumer: {e}", exc_info=True)
                if span.is_recording():
                    span.record_exception(e)
                    span.set_status(Status(StatusCode.ERROR, f"KafkaConsumerStopFailed: {str(e)}"))