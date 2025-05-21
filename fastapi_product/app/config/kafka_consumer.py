# ver2. AIOKafkaInstrumentor를 써서 otel-tracing을 자동 계측한 버전 
from aiokafka import AIOKafkaConsumer
import asyncio
import json
import logging
from typing import Callable, Dict, Any, List

# OTel imports
from opentelemetry import trace
# from opentelemetry import context as otel_context # 직접 사용할 일 없을 수 있음
# from opentelemetry import propagate # 수동 전파 제거로 인해 필요 없음
from opentelemetry.trace import SpanKind, Status, StatusCode # Status, StatusCode는 여전히 사용
from opentelemetry.semconv.trace import SpanAttributes # 시맨틱 컨벤션 사용

logger = logging.getLogger(__name__)

class KafkaConsumer:
    def __init__(self, bootstrap_servers: str, group_id: str, topics: List[str]):
        self.bootstrap_servers = bootstrap_servers
        self.group_id = group_id
        self.topics = topics
        self.consumer: AIOKafkaConsumer = None
        self.handlers: Dict[str, Callable] = {}
        # Tracer는 사용자 정의 스팬(start, stop 등)을 위해 유지할 수 있습니다.
        # 또는, 메시지 처리 스팬에 속성을 추가할 때도 tracer를 통해 현재 스팬을 가져올 수 있습니다.
        self.tracer = trace.get_tracer("app.product_module.KafkaConsumer", "0.1.0") # Tracer 이름은 적절히 지정

        # 수동 프로파게이터 설정 로직 제거
        # self.otel_propagator = propagate.get_global_textmap() ...

    def register_handler(self, event_type: str, handler: Callable):
        self.handlers[event_type] = handler
        logger.info(f"Registered handler for event_type: {event_type}")

    async def start(self):
        # 이 스팬은 KafkaConsumer의 시작 과정을 추적합니다. 메시지 처리 스팬과는 별개입니다.
        with self.tracer.start_as_current_span("kafka_consumer.start_and_subscribe") as span:
            span.set_attribute(SpanAttributes.MESSAGING_SYSTEM, "kafka") # 시맨틱 컨벤션 사용
            span.set_attribute(SpanAttributes.MESSAGING_KAFKA_CONSUMER_GROUP, self.group_id)
            span.set_attribute("app.kafka.bootstrap_servers", self.bootstrap_servers) # 사용자 정의 속성
            span.set_attribute("app.kafka.subscribed_topics", ",".join(self.topics)) # 사용자 정의 속성
            try:
                self.consumer = AIOKafkaConsumer(
                    bootstrap_servers=self.bootstrap_servers,
                    group_id=self.group_id,
                    auto_offset_reset='latest',
                    value_deserializer=lambda m: json.loads(m.decode('utf-8')),
                    enable_auto_commit=True # 이 모듈은 자동 커밋 사용
                    # AIOKafkaInstrumentor가 자동으로 AIOKafkaConsumer의 동작을 계측합니다.
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

        # 수동 컨텍스트 추출 및 스팬 시작 로직 제거
        # carrier = {} ...
        # extracted_context = self.otel_propagator.extract(carrier) ...
        # with self.tracer.start_as_current_span(..., context=extracted_context, kind=SpanKind.CONSUMER) as span: ...

        try:
            # AIOKafkaInstrumentor가 이 루프에서 각 메시지 수신 시 자동으로 CONSUMER 스팬을 생성하고 활성화합니다.
            async for msg in self.consumer:
                # 자동 생성된 현재 스팬 가져오기
                current_span = trace.get_current_span()

                # AIOKafkaInstrumentor가 기본 속성(예: messaging.system, messaging.destination.name 등)을 설정합니다.
                # 여기에 추가적인 사용자 정의 속성을 설정합니다.
                if current_span.is_recording(): # 스팬이 샘플링되어 실제로 기록되는 경우에만 속성 설정
                    current_span.set_attribute(SpanAttributes.MESSAGING_MESSAGE_ID, str(msg.offset))
                    current_span.set_attribute(SpanAttributes.MESSAGING_KAFKA_MESSAGE_KEY, msg.key.decode() if msg.key else "None")
                    current_span.set_attribute(SpanAttributes.MESSAGING_KAFKA_PARTITION, msg.partition)
                    # SpanAttributes.MESSAGING_OPERATION은 "receive" 등으로 자동 설정될 수 있음

                    logger.info(f"Processing Kafka message: Topic={msg.topic}, Partition={msg.partition}, Offset={msg.offset}, Key={msg.key.decode('utf-8') if msg.key else None}")
                    current_span.add_event("message_received_for_processing", {
                        "topic": msg.topic, "partition": msg.partition, "offset": msg.offset
                    })

                try:
                    event_type = None
                    if msg.headers:
                        for key_h, value_h in msg.headers:
                            if key_h == 'eventType':
                                event_type = value_h.decode('utf-8')
                                if current_span.is_recording():
                                    current_span.set_attribute("app.kafka.header.eventType", event_type)
                                logger.info(f"Event type from header: {event_type}")
                                break

                    message_payload = msg.value # 이미 JSON 객체로 역직렬화됨

                    if not isinstance(message_payload, dict):
                        err_msg = f"Message value is not a dictionary: {type(message_payload)}"
                        logger.error(err_msg)
                        if current_span.is_recording():
                            current_span.set_status(Status(StatusCode.ERROR, err_msg))
                            current_span.set_attribute("app.message.parsing_error", "Not a dictionary")
                        continue # 다음 메시지 처리

                    actual_payload_to_handle = message_payload
                    if 'schema' in message_payload and 'payload' in message_payload: # Debezium 메시지 형식 가정
                        payload_data = message_payload['payload']
                        if current_span.is_recording():
                            current_span.set_attribute("app.debezium_payload_type", str(type(payload_data)))
                        if isinstance(payload_data, str):
                            try:
                                actual_payload_to_handle = json.loads(payload_data)
                                if current_span.is_recording():
                                    current_span.add_event("debezium_string_payload_parsed")
                            except json.JSONDecodeError as je:
                                logger.error(f"Failed to parse Debezium string payload: {str(je)}", exc_info=True)
                                if current_span.is_recording():
                                    current_span.record_exception(je)
                                    current_span.set_status(Status(StatusCode.ERROR, "Debezium payload JSON decode error"))
                                continue # 다음 메시지 처리
                        elif isinstance(payload_data, dict): # payload가 이미 dict인 경우
                             actual_payload_to_handle = payload_data
                        else: # 예기치 않은 payload 타입
                            logger.error(f"Unexpected Debezium payload type: {type(payload_data)}")
                            if current_span.is_recording():
                                current_span.set_status(Status(StatusCode.ERROR, f"Unexpected Debezium payload type: {type(payload_data)}"))
                            continue


                    if not event_type and isinstance(actual_payload_to_handle, dict):
                        event_type = actual_payload_to_handle.get('type')
                        if event_type and current_span.is_recording():
                            current_span.set_attribute("app.payload.event_type", event_type)
                            logger.info(f"Event type from payload: {event_type}")

                    if not event_type:
                        err_msg = f"No event_type found in message for topic {msg.topic}"
                        logger.error(err_msg)
                        if current_span.is_recording():
                            current_span.set_status(Status(StatusCode.ERROR, err_msg))
                            current_span.set_attribute("app.message.event_type_missing", True)
                        continue # 다음 메시지 처리

                    if current_span.is_recording():
                        current_span.set_attribute("app.event_type_resolved", event_type) # 최종 결정된 이벤트 타입

                    if event_type in self.handlers:
                        logger.info(f"Calling handler for event_type: {event_type}")
                        # 핸들러 실행. 핸들러 내부에서 추가적인 자식 스팬을 생성할 수 있습니다.
                        await self.handlers[event_type](actual_payload_to_handle)
                        logger.info(f"Handler completed for event_type: {event_type}")
                        if current_span.is_recording():
                            # 명시적으로 OK를 설정할 수도 있지만, 예외가 발생하지 않으면 기본적으로 OK 상태가 됩니다.
                            # 자동 커밋이므로 핸들러 완료가 반드시 성공적인 처리를 의미하지 않을 수 있으나,
                            # 핸들러에서 예외가 발생하지 않았다면 OK로 간주합니다.
                            current_span.set_status(Status(StatusCode.OK))
                    else:
                        logger.warning(f"No handler registered for event_type: {event_type}")
                        if current_span.is_recording():
                            current_span.set_attribute("app.handler.not_found", True)
                            # 핸들러가 없는 것은 에러는 아니지만, 정보성으로 UNSET 또는 OK와 함께 메시지 추가 가능
                            current_span.set_status(Status(StatusCode.OK, f"No handler for {event_type}"))


                except Exception as e_proc:
                    proc_error_msg = f"Error processing message (event_type '{event_type or 'unknown'}'): {str(e_proc)}"
                    logger.error(proc_error_msg, exc_info=True)
                    if current_span.is_recording():
                        current_span.record_exception(e_proc)
                        current_span.set_status(Status(StatusCode.ERROR, proc_error_msg))
                # enable_auto_commit=True 이므로, 명시적인 commit 호출은 없습니다.

        except Exception as e_consumer_loop:
            logger.error(f"Kafka consumer loop critical error: {str(e_consumer_loop)}", exc_info=True)
            # 이 레벨의 에러는 현재 메시지 스팬 컨텍스트 외부일 수 있으므로, 별도 스팬을 고려하거나 로깅에만 의존.
        finally:
            logger.info("Kafka consumer loop ended. Stopping consumer.")
            await self.stop() # stop 메서드 내부에서 자체 스팬 관리

    async def stop(self):
        if self.consumer:
            # 이 스팬은 KafkaConsumer의 중지 과정을 추적합니다.
            with self.tracer.start_as_current_span("kafka_consumer.stop") as span:
                try:
                    await self.consumer.stop()
                    logger.info("Kafka consumer stopped")
                    span.set_status(Status(StatusCode.OK))
                except Exception as e:
                    logger.error(f"Kafka consumer stop error: {e}", exc_info=True)
                    span.record_exception(e)
                    span.set_status(Status(StatusCode.ERROR, "Kafka consumer stop error"))


# ver1. otel-tracing시 수동으로 propagate 써서 계측한 버전 
# from aiokafka import AIOKafkaConsumer
# import asyncio
# import json
# import logging
# from typing import Callable, Dict, Any, List

# # OTel imports
# from opentelemetry import trace, context as otel_context
# # 'propagate' 모듈을 직접 임포트하는 것은 맞음
# from opentelemetry import propagate
# from opentelemetry.trace import SpanKind, Status, StatusCode
# from opentelemetry.semconv.trace import SpanAttributes # 이전 결정대로 SpanAttributes 사용

# logger = logging.getLogger(__name__)

# class KafkaConsumer:
#     def __init__(self, bootstrap_servers: str, group_id: str, topics: List[str]):
#         self.bootstrap_servers = bootstrap_servers
#         self.group_id = group_id
#         self.topics = topics
#         self.consumer: AIOKafkaConsumer = None
#         self.handlers: Dict[str, Callable] = {}
#         self.tracer = trace.get_tracer("app.config.KafkaConsumer", "0.1.0")
#         # 전역 전파기를 클래스 초기화 시점에 가져와서 멤버 변수로 저장 시도
#         try:
#             self.otel_propagator = propagate.get_global_textmap()
#             logger.info(f"Successfully fetched global textmap propagator: {type(self.otel_propagator)}")
#         except AttributeError:
#             logger.error("CRITICAL: `propagate.get_global_textmap_propagator()` not found! Falling back to NOOP or manual context. Check OTel API version.", exc_info=True)
#             # 이 경우, 전파가 안 될 수 있으므로 대체 로직이나 명시적인 에러 처리가 필요할 수 있음
#             # 가장 간단한 대안은 NoOpPropagator를 쓰거나, 아예 전파를 시도하지 않는 것.
#             # 하지만 이러면 분산 트레이싱이 깨짐! 버전 문제가 확실함.
#             from opentelemetry.propagators.noop import NoOpTextMapPropagator
#             self.otel_propagator = NoOpTextMapPropagator()


#     def register_handler(self, event_type: str, handler: Callable):
#         self.handlers[event_type] = handler
#         logger.info(f"Registered handler for event_type: {event_type}")
        
#     async def start(self):
#         # ... (start 메서드 내용은 이전과 동일하게 유지, OTel 적용 부분 포함) ...
#         with self.tracer.start_as_current_span("kafka_consumer.start_and_subscribe") as span:
#             span.set_attribute("app.kafka.bootstrap_servers", self.bootstrap_servers)
#             span.set_attribute("app.kafka.group_id", self.group_id)
#             span.set_attribute("app.kafka.subscribed_topics", ",".join(self.topics))
#             try:
#                 self.consumer = AIOKafkaConsumer(
#                     bootstrap_servers=self.bootstrap_servers,
#                     group_id=self.group_id,
#                     auto_offset_reset='latest',
#                     value_deserializer=lambda m: json.loads(m.decode('utf-8')),
#                     enable_auto_commit=True 
#                 )
#                 await self.consumer.start()
#                 self.consumer.subscribe(topics=self.topics)

#                 logger.info(f"Kafka consumer started for group '{self.group_id}'. Subscribed to: {self.topics}")
#                 asyncio.create_task(self.consume_messages())
#                 span.set_status(Status(StatusCode.OK))
#             except Exception as e:
#                 logger.error(f"Kafka consumer startup failed: {e}", exc_info=True)
#                 span.record_exception(e)
#                 span.set_status(Status(StatusCode.ERROR, "Kafka consumer startup failed"))
#                 raise
            
#     async def consume_messages(self):
#         if not self.consumer:
#             logger.error("Kafka consumer not initialized.")
#             return

#         # otel_propagator를 __init__에서 가져온 self.otel_propagator 사용
#         # otel_propagator = propagate.get_global_textmap_propagator() # 이 줄을 self.otel_propagator로 대체

#         try:
#             async for msg in self.consumer:
#                 carrier = {}
#                 if msg.headers:
#                     for key, value in msg.headers:
#                         # self.otel_propagator.fields를 사용해야 함
#                         if key in self.otel_propagator.fields: 
#                             carrier[key] = value.decode('utf-8') if value else ""
                
#                 # self.otel_propagator를 사용
#                 extracted_context = self.otel_propagator.extract(carrier)
                
#                 with self.tracer.start_as_current_span(
#                     f"{msg.topic} process", 
#                     context=extracted_context,
#                     kind=trace.SpanKind.CONSUMER
#                 ) as span:
#                     # ... (이전 답변의 스팬 속성 설정 및 메시지 처리 로직은 동일하게 유지) ...
#                     # 예시:
#                     if hasattr(SpanAttributes, "MESSAGING_SYSTEM"):
#                         span.set_attribute(SpanAttributes.MESSAGING_SYSTEM, "kafka")
#                     else:
#                         span.set_attribute("messaging.system", "kafka")
#                     # ... (기타 속성들) ...

#                     logger.info(f"Processing Kafka message: Topic={msg.topic}, Partition={msg.partition}, Offset={msg.offset}, Key={msg.key.decode('utf-8') if msg.key else None}")
#                     span.add_event("message_received_for_processing", {
#                         "topic": msg.topic, "partition": msg.partition, "offset": msg.offset
#                     })
                    
#                     try:
#                         event_type = None
#                         if msg.headers:
#                             for key_h, value_h in msg.headers:
#                                 if key_h == 'eventType':
#                                     event_type = value_h.decode('utf-8')
#                                     span.set_attribute("app.kafka.header.eventType", event_type)
#                                     logger.info(f"Event type from header: {event_type}")
#                                     break
                        
#                         message_payload = msg.value
                        
#                         if not isinstance(message_payload, dict):
#                             err_msg = f"Message value is not a dictionary: {type(message_payload)}"
#                             logger.error(err_msg)
#                             span.set_status(Status(StatusCode.ERROR, err_msg))
#                             span.set_attribute("app.message.parsing_error", "Not a dictionary")
#                             continue

#                         actual_payload_to_handle = message_payload
#                         if 'schema' in message_payload and 'payload' in message_payload: # Debezium
#                             payload_data = message_payload['payload']
#                             span.set_attribute("app.debezium_payload_type", str(type(payload_data)))
#                             if isinstance(payload_data, str):
#                                 try:
#                                     actual_payload_to_handle = json.loads(payload_data)
#                                     span.add_event("debezium_string_payload_parsed")
#                                 except json.JSONDecodeError as je:
#                                     logger.error(f"Failed to parse Debezium string payload: {str(je)}", exc_info=True)
#                                     span.record_exception(je)
#                                     span.set_status(Status(StatusCode.ERROR, "Debezium payload JSON decode error"))
#                                     continue
#                             else:
#                                 actual_payload_to_handle = payload_data
                        
#                         if not event_type and isinstance(actual_payload_to_handle, dict):
#                             event_type = actual_payload_to_handle.get('type')
#                             if event_type:
#                                 span.set_attribute("app.payload.event_type", event_type)
#                                 logger.info(f"Event type from payload: {event_type}")
                        
#                         if not event_type:
#                             err_msg = f"No event_type found in message for topic {msg.topic}"
#                             logger.error(err_msg)
#                             span.set_status(Status(StatusCode.ERROR, err_msg))
#                             span.set_attribute("app.message.event_type_missing", True)
#                             continue
                        
#                         span.set_attribute("app.event_type_resolved", event_type)

#                         if event_type in self.handlers:
#                             logger.info(f"Calling handler for event_type: {event_type}")
#                             await self.handlers[event_type](actual_payload_to_handle)
#                             logger.info(f"Handler completed for event_type: {event_type}")
#                             span.set_status(Status(StatusCode.OK))
#                         else:
#                             logger.warning(f"No handler registered for event_type: {event_type}")
#                             span.set_attribute("app.handler.not_found", True)
#                             span.set_status(Status(StatusCode.OK, f"No handler for {event_type}"))

#                     except Exception as e_proc:
#                         proc_error_msg = f"Error processing message (event_type '{event_type or 'unknown'}'): {str(e_proc)}"
#                         logger.error(proc_error_msg, exc_info=True)
#                         span.record_exception(e_proc)
#                         span.set_status(Status(StatusCode.ERROR, proc_error_msg))
        
#         except Exception as e_consumer_loop:
#             logger.error(f"Kafka consumer loop critical error: {str(e_consumer_loop)}", exc_info=True)
#         finally:
#             logger.info("Kafka consumer loop ended. Stopping consumer.")
#             await self.stop()
            
#     async def stop(self):
#         # ... (stop 메서드 내용은 이전과 동일하게 유지, OTel 적용 부분 포함) ...
#         if self.consumer:
#             with self.tracer.start_as_current_span("kafka_consumer.stop") as span:
#                 try:
#                     await self.consumer.stop()
#                     logger.info("Kafka consumer stopped")
#                     span.set_status(Status(StatusCode.OK))
#                 except Exception as e:
#                     logger.error(f"Kafka consumer stop error: {e}", exc_info=True)
#                     span.record_exception(e)
#                     span.set_status(Status(StatusCode.ERROR, "Kafka consumer stop error"))