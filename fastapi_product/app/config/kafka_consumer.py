from aiokafka import AIOKafkaConsumer
import asyncio
import json
import logging
from typing import Callable, Dict, Any, List

# OTel imports
from opentelemetry import trace, context as otel_context
# 'propagate' 모듈을 직접 임포트하는 것은 맞음
from opentelemetry import propagate
from opentelemetry.trace import SpanKind, Status, StatusCode
from opentelemetry.semconv.trace import SpanAttributes # 이전 결정대로 SpanAttributes 사용

logger = logging.getLogger(__name__)

class KafkaConsumer:
    def __init__(self, bootstrap_servers: str, group_id: str, topics: List[str]):
        self.bootstrap_servers = bootstrap_servers
        self.group_id = group_id
        self.topics = topics
        self.consumer: AIOKafkaConsumer = None
        self.handlers: Dict[str, Callable] = {}
        self.tracer = trace.get_tracer("app.config.KafkaConsumer", "0.1.0")
        # 전역 전파기를 클래스 초기화 시점에 가져와서 멤버 변수로 저장 시도
        try:
            self.otel_propagator = propagate.get_global_textmap()
            logger.info(f"Successfully fetched global textmap propagator: {type(self.otel_propagator)}")
        except AttributeError:
            logger.error("CRITICAL: `propagate.get_global_textmap_propagator()` not found! Falling back to NOOP or manual context. Check OTel API version.", exc_info=True)
            # 이 경우, 전파가 안 될 수 있으므로 대체 로직이나 명시적인 에러 처리가 필요할 수 있음
            # 가장 간단한 대안은 NoOpPropagator를 쓰거나, 아예 전파를 시도하지 않는 것.
            # 하지만 이러면 분산 트레이싱이 깨짐! 버전 문제가 확실함.
            from opentelemetry.propagators.noop import NoOpTextMapPropagator
            self.otel_propagator = NoOpTextMapPropagator()


    def register_handler(self, event_type: str, handler: Callable):
        self.handlers[event_type] = handler
        logger.info(f"Registered handler for event_type: {event_type}")
        
    async def start(self):
        # ... (start 메서드 내용은 이전과 동일하게 유지, OTel 적용 부분 포함) ...
        with self.tracer.start_as_current_span("kafka_consumer.start_and_subscribe") as span:
            span.set_attribute("app.kafka.bootstrap_servers", self.bootstrap_servers)
            span.set_attribute("app.kafka.group_id", self.group_id)
            span.set_attribute("app.kafka.subscribed_topics", ",".join(self.topics))
            try:
                self.consumer = AIOKafkaConsumer(
                    bootstrap_servers=self.bootstrap_servers,
                    group_id=self.group_id,
                    auto_offset_reset='latest',
                    value_deserializer=lambda m: json.loads(m.decode('utf-8')),
                    enable_auto_commit=True 
                )
                await self.consumer.start()
                self.consumer.subscribe(topics=self.topics)

                logger.info(f"Kafka consumer started for group '{self.group_id}'. Subscribed to: {self.topics}")
                asyncio.create_task(self.consume_messages())
                span.set_status(Status(StatusCode.OK))
            except Exception as e:
                logger.error(f"Kafka consumer startup failed: {e}", exc_info=True)
                span.record_exception(e)
                span.set_status(Status(StatusCode.ERROR, "Kafka consumer startup failed"))
                raise
            
    async def consume_messages(self):
        if not self.consumer:
            logger.error("Kafka consumer not initialized.")
            return

        # otel_propagator를 __init__에서 가져온 self.otel_propagator 사용
        # otel_propagator = propagate.get_global_textmap_propagator() # 이 줄을 self.otel_propagator로 대체

        try:
            async for msg in self.consumer:
                carrier = {}
                if msg.headers:
                    for key, value in msg.headers:
                        # self.otel_propagator.fields를 사용해야 함
                        if key in self.otel_propagator.fields: 
                            carrier[key] = value.decode('utf-8') if value else ""
                
                # self.otel_propagator를 사용
                extracted_context = self.otel_propagator.extract(carrier)
                
                with self.tracer.start_as_current_span(
                    f"{msg.topic} process", 
                    context=extracted_context,
                    kind=trace.SpanKind.CONSUMER
                ) as span:
                    # ... (이전 답변의 스팬 속성 설정 및 메시지 처리 로직은 동일하게 유지) ...
                    # 예시:
                    if hasattr(SpanAttributes, "MESSAGING_SYSTEM"):
                        span.set_attribute(SpanAttributes.MESSAGING_SYSTEM, "kafka")
                    else:
                        span.set_attribute("messaging.system", "kafka")
                    # ... (기타 속성들) ...

                    logger.info(f"Processing Kafka message: Topic={msg.topic}, Partition={msg.partition}, Offset={msg.offset}, Key={msg.key.decode('utf-8') if msg.key else None}")
                    span.add_event("message_received_for_processing", {
                        "topic": msg.topic, "partition": msg.partition, "offset": msg.offset
                    })
                    
                    try:
                        event_type = None
                        if msg.headers:
                            for key_h, value_h in msg.headers:
                                if key_h == 'eventType':
                                    event_type = value_h.decode('utf-8')
                                    span.set_attribute("app.kafka.header.eventType", event_type)
                                    logger.info(f"Event type from header: {event_type}")
                                    break
                        
                        message_payload = msg.value
                        
                        if not isinstance(message_payload, dict):
                            err_msg = f"Message value is not a dictionary: {type(message_payload)}"
                            logger.error(err_msg)
                            span.set_status(Status(StatusCode.ERROR, err_msg))
                            span.set_attribute("app.message.parsing_error", "Not a dictionary")
                            continue

                        actual_payload_to_handle = message_payload
                        if 'schema' in message_payload and 'payload' in message_payload: # Debezium
                            payload_data = message_payload['payload']
                            span.set_attribute("app.debezium_payload_type", str(type(payload_data)))
                            if isinstance(payload_data, str):
                                try:
                                    actual_payload_to_handle = json.loads(payload_data)
                                    span.add_event("debezium_string_payload_parsed")
                                except json.JSONDecodeError as je:
                                    logger.error(f"Failed to parse Debezium string payload: {str(je)}", exc_info=True)
                                    span.record_exception(je)
                                    span.set_status(Status(StatusCode.ERROR, "Debezium payload JSON decode error"))
                                    continue
                            else:
                                actual_payload_to_handle = payload_data
                        
                        if not event_type and isinstance(actual_payload_to_handle, dict):
                            event_type = actual_payload_to_handle.get('type')
                            if event_type:
                                span.set_attribute("app.payload.event_type", event_type)
                                logger.info(f"Event type from payload: {event_type}")
                        
                        if not event_type:
                            err_msg = f"No event_type found in message for topic {msg.topic}"
                            logger.error(err_msg)
                            span.set_status(Status(StatusCode.ERROR, err_msg))
                            span.set_attribute("app.message.event_type_missing", True)
                            continue
                        
                        span.set_attribute("app.event_type_resolved", event_type)

                        if event_type in self.handlers:
                            logger.info(f"Calling handler for event_type: {event_type}")
                            await self.handlers[event_type](actual_payload_to_handle)
                            logger.info(f"Handler completed for event_type: {event_type}")
                            span.set_status(Status(StatusCode.OK))
                        else:
                            logger.warning(f"No handler registered for event_type: {event_type}")
                            span.set_attribute("app.handler.not_found", True)
                            span.set_status(Status(StatusCode.OK, f"No handler for {event_type}"))

                    except Exception as e_proc:
                        proc_error_msg = f"Error processing message (event_type '{event_type or 'unknown'}'): {str(e_proc)}"
                        logger.error(proc_error_msg, exc_info=True)
                        span.record_exception(e_proc)
                        span.set_status(Status(StatusCode.ERROR, proc_error_msg))
        
        except Exception as e_consumer_loop:
            logger.error(f"Kafka consumer loop critical error: {str(e_consumer_loop)}", exc_info=True)
        finally:
            logger.info("Kafka consumer loop ended. Stopping consumer.")
            await self.stop()
            
    async def stop(self):
        # ... (stop 메서드 내용은 이전과 동일하게 유지, OTel 적용 부분 포함) ...
        if self.consumer:
            with self.tracer.start_as_current_span("kafka_consumer.stop") as span:
                try:
                    await self.consumer.stop()
                    logger.info("Kafka consumer stopped")
                    span.set_status(Status(StatusCode.OK))
                except Exception as e:
                    logger.error(f"Kafka consumer stop error: {e}", exc_info=True)
                    span.record_exception(e)
                    span.set_status(Status(StatusCode.ERROR, "Kafka consumer stop error"))