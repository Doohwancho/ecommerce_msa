from aiokafka import AIOKafkaConsumer
import asyncio
import json
from typing import Callable, Dict
import logging

from opentelemetry import trace, propagate
from opentelemetry.trace import Status, StatusCode, SpanKind
from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator
from opentelemetry.semconv.trace import SpanAttributes

logger = logging.getLogger(__name__)

class KafkaConsumer:
    def __init__(self, bootstrap_servers: str, group_id: str, topic: str = 'dbserver.order'):
        self.bootstrap_servers = bootstrap_servers
        self.group_id = group_id
        self.topic_to_subscribe = topic
        self.consumer: AIOKafkaConsumer = None
        self.handlers: Dict[str, Callable] = {}
        self.tracer = trace.get_tracer("app.config.payment_kafka.KafkaConsumer", "0.1.0")
        self._running = False
        logger.info(f"KafkaConsumer initialized for group '{self.group_id}' to subscribe to topic '{self.topic_to_subscribe}'")

    def register_handler(self, event_type: str, handler: Callable):
        self.handlers[event_type] = handler
        logger.info(f"[{self.group_id}] Handler registered: event_type='{event_type}', handler='{handler.__name__}'")

    async def start(self):
        if self._running:
            logger.warning(f"[{self.group_id}] KafkaConsumer.start called but already running.")
            return

        with self.tracer.start_as_current_span(f"{self.group_id}.KafkaConsumer.start_consumer_instance") as span:
            span.set_attribute(SpanAttributes.MESSAGING_SYSTEM, "kafka")
            # ... (기타 속성 설정은 이전과 동일)
            try:
                logger.info(f"[{self.group_id}] Attempting to create AIOKafkaConsumer for topic '{self.topic_to_subscribe}'...")
                self.consumer = AIOKafkaConsumer(
                    self.topic_to_subscribe,
                    bootstrap_servers=self.bootstrap_servers,
                    group_id=self.group_id,
                    auto_offset_reset='latest',
                    # value_deserializer는 bytes -> str 만 수행하도록 변경
                    value_deserializer=lambda m: m.decode('utf-8', errors='replace') if isinstance(m, (bytes, bytearray)) else str(m),
                    enable_auto_commit=False
                )
                await self.consumer.start()
                self._running = True
                asyncio.create_task(self.consume_messages())
                logger.info(f"[{self.group_id}] Kafka consumer task created and started for topic '{self.topic_to_subscribe}'.")
                span.set_status(Status(StatusCode.OK))
            except Exception as e:
                logger.error(f"[{self.group_id}] Failed to start Kafka consumer: {e}", exc_info=True)
                # ... (스팬 에러 처리)
                self._running = False
                raise

    async def consume_messages(self):
        if not self.consumer:
            logger.error(f"[{self.group_id}] Consumer not initialized. Cannot consume messages.")
            return

        logger.info(f"[{self.group_id}] Starting message consumption loop for topic '{self.topic_to_subscribe}'...")
        propagator = TraceContextTextMapPropagator()

        try:
            async for msg in self.consumer:
                logger.info(f"!!!!!!!!!! [{self.group_id}] KAFKA MESSAGE RECEIVED (RAW) !!!!!!!!!!")
                logger.info(f"[{self.group_id}] Raw msg details: Topic={msg.topic}, Partition={msg.partition}, Offset={msg.offset}, Key={msg.key}")

                carrier = {}
                header_log = {}
                if msg.headers:
                    for key, value_bytes in msg.headers:
                        decoded_value = None
                        if value_bytes is not None:
                            decoded_value = value_bytes.decode('utf-8', errors='replace')
                        else:
                            logger.warning(f"[{self.group_id}] Header '{key}' has a None value.")
                        header_log[key] = decoded_value
                        if key.lower() == 'traceparent' and decoded_value:
                            carrier['traceparent'] = decoded_value
                        elif key.lower() == 'tracestate' and decoded_value:
                            carrier['tracestate'] = decoded_value
                    logger.info(f"[{self.group_id}] Decoded Kafka Message Headers: {header_log}")
                    if 'traceparent' not in carrier:
                        logger.warning(f"[{self.group_id}] 'traceparent' not found or is null in carrier from message headers.")
                else:
                    logger.warning(f"[{self.group_id}] NO KAFKA MESSAGE HEADERS FOUND.")

                parent_context = propagator.extract(carrier=carrier)
                
                # msg.value는 value_deserializer에 의해 이제 항상 str (JSON 형식의 문자열)일 것으로 기대됨
                raw_payload_str = msg.value

                # !!!!! 여기서 actual_message_payload를 dict로 변환 시도 !!!!!
                actual_message_payload = None
                if isinstance(raw_payload_str, str):
                    # repr() 로그 추가!
                    logger.info(f"[{self.group_id}] Raw string payload from Kafka (repr): {repr(raw_payload_str)}")
                    try:
                        # 첫 번째 파싱 시도
                        parsed_payload = json.loads(raw_payload_str)
                        
                        # 만약 첫 번째 파싱 결과가 또 문자열이라면 (이중 인코딩 의심)
                        if isinstance(parsed_payload, str):
                            logger.warning(f"[{self.group_id}] Payload was a double-encoded string. Attempting second parse. String after first parse: {parsed_payload[:200]}...")
                            actual_message_payload = json.loads(parsed_payload) # 두 번째 파싱
                        else:
                            actual_message_payload = parsed_payload # 첫 번째 파싱으로 dict/list 등이 나왔으면 그걸 사용
                            
                    except json.JSONDecodeError as e_json:
                        logger.error(f"[{self.group_id}] Failed to parse JSON string payload. Raw string: {raw_payload_str[:500]}, Error: {e_json}. Skipping message.")
                        await self.consumer.commit()
                        continue
                else:
                    logger.error(f"[{self.group_id}] Expected string payload from deserializer, but got {type(raw_payload_str)}. Skipping. Value: {raw_payload_str}")
                    await self.consumer.commit()
                    continue
                
                # 최종적으로 dict인지 확인
                logger.info(f"[{self.group_id}] Final processed message payload type: {type(actual_message_payload)}. Preview: {str(actual_message_payload)[:500]}...")

                if not isinstance(actual_message_payload, dict):
                    logger.error(f"[{self.group_id}] Message payload is NOT a dict after processing, it's {type(actual_message_payload)}. Skipping. Value: {actual_message_payload}")
                    await self.consumer.commit()
                    continue
                
                # ... (이벤트 타입 결정 및 핸들러 호출 로직은 이전과 거의 동일, 스팬 생성 부분 포함) ...
                event_type_from_header = header_log.get('eventType')
                final_event_type = event_type_from_header
                if not final_event_type:
                    final_event_type = actual_message_payload.get('type')
                    if final_event_type:
                        logger.info(f"[{self.group_id}] Using eventType from payload 'type' field: '{final_event_type}'")
                
                if not final_event_type:
                    logger.error(f"[{self.group_id}] Could not determine event_type. Skipping message.")
                    await self.consumer.commit()
                    continue

                with self.tracer.start_as_current_span(
                    f"message.process.{final_event_type}",
                    context=parent_context,
                    kind=SpanKind.CONSUMER,
                    attributes={
                        SpanAttributes.MESSAGING_SYSTEM: "kafka",
                        # ... (기타 속성은 이전과 동일)
                        "app.event.type": final_event_type,
                    }
                ) as processing_span:
                    try:
                        processing_span.set_attribute("app.message.payload_preview", json.dumps(actual_message_payload, ensure_ascii=False)[:256])
                    except:
                        processing_span.set_attribute("app.message.payload_preview", str(actual_message_payload)[:256])

                    logger.info(f"[{self.group_id}] Resolved final_event_type: '{final_event_type}' for message at offset {msg.offset}")

                    if final_event_type in self.handlers:
                        handler_to_call = self.handlers[final_event_type]
                        logger.info(f"[{self.group_id}] Found handler '{handler_to_call.__name__}'. Calling handler for event_type: '{final_event_type}'...")
                        try:
                            await handler_to_call(actual_message_payload)
                            logger.info(f"[{self.group_id}] Handler '{handler_to_call.__name__}' for event_type '{final_event_type}' completed successfully.")
                            if processing_span.is_recording():
                                processing_span.set_status(Status(StatusCode.OK))
                        except Exception as e_handler:
                            logger.error(f"[{self.group_id}] Error in handler '{handler_to_call.__name__}': {e_handler}", exc_info=True)
                            if processing_span.is_recording():
                                processing_span.record_exception(e_handler)
                                processing_span.set_status(Status(StatusCode.ERROR, f"HandlerExecutionFailed: {str(e_handler)}"))
                    else:
                        logger.warning(f"[{self.group_id}] No handler registered for event_type: '{final_event_type}'. Skipping.")
                        if processing_span.is_recording():
                            processing_span.set_status(Status(StatusCode.OK, f"NoHandlerForEventType_{final_event_type}"))
                    
                    await self.consumer.commit()
                    logger.info(f"[{self.group_id}] Offset {msg.offset} committed for topic {msg.topic} after processing event '{final_event_type}'.")

        except asyncio.CancelledError:
            logger.info(f"Consume messages task for group '{self.group_id}' was cancelled.")
        except Exception as e_loop:
            logger.error(f"CRITICAL Kafka consumer loop error for group '{self.group_id}': {e_loop}", exc_info=True)
            self._running = False
        finally:
            logger.info(f"Consume_messages loop for group '{self.group_id}' is ending.")
            if self._running:
                logger.warning(f"[{self.group_id}] Consume_messages loop exited unexpectedly. Attempting to stop consumer.")
                await self.stop()

    async def stop(self):
        # ... (stop 메소드는 이전과 동일하게 유지)
        if not self._running and not self.consumer:
            logger.info(f"[{self.group_id}] KafkaConsumer.stop called but not running or not initialized.")
            return
        
        with self.tracer.start_as_current_span(f"{self.group_id}.KafkaConsumer.stop_consumer_instance") as span:
            try:
                current_running_status = self._running
                self._running = False

                if self.consumer:
                    logger.info(f"[{self.group_id}] Stopping Kafka consumer (was running: {current_running_status})...")
                    await self.consumer.stop()
                    logger.info(f"[{self.group_id}] Kafka consumer stopped successfully.")
                    self.consumer = None
                else:
                    logger.info(f"[{self.group_id}] Kafka consumer was already None (was running: {current_running_status}).")
                
                span.set_status(Status(StatusCode.OK))
            except Exception as e:
                logger.error(f"[{self.group_id}] Error stopping Kafka consumer: {e}", exc_info=True)
                if span.is_recording():
                    span.record_exception(e)
                    span.set_status(Status(StatusCode.ERROR, f"KafkaConsumerStopFailed: {str(e)}"))