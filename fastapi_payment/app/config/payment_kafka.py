from aiokafka import AIOKafkaConsumer
import asyncio
import json
from typing import Callable, Dict, Any # Any는 사용되지 않으므로 제거 가능
import logging

# OpenTelemetry API 임포트
from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode
from opentelemetry.semconv.trace import SpanAttributes # 시맨틱 컨벤션 사용 권장

# 로깅 설정 (애플리케이션 진입점에서 한 번 설정하는 것이 일반적)
# logging.basicConfig(level=logging.INFO) # otel.py에서 OTel 로깅 핸들러가 설정될 수 있으므로 중복 주의
logger = logging.getLogger(__name__)
# tracer 인스턴스는 클래스 외부 또는 __init__에서 가져올 수 있습니다.
# 여기서는 각 메서드에서 필요시 현재 스팬을 가져오거나, __init__에서 tracer를 설정합니다.


class KafkaConsumer:
    def __init__(self, bootstrap_servers: str, group_id: str, topic: str = 'order'): # 구독할 토픽을 명시적으로 받도록 변경
        self.bootstrap_servers = bootstrap_servers
        self.group_id = group_id
        self.topic_to_subscribe = topic # 구독할 토픽 저장
        self.consumer: AIOKafkaConsumer = None # 타입 힌트 명시
        self.handlers: Dict[str, Callable] = {}
        self.tracer = trace.get_tracer(__name__, "0.1.0") # 클래스 버전 등 명시 가능
        self._running = False # 소비자 실행 상태 플래그

    def register_handler(self, event_type: str, handler: Callable):
        """특정 이벤트 타입에 대한 핸들러 등록"""
        self.handlers[event_type] = handler
        logger.info(f"Handler registered for event_type: {event_type}")
        
    async def start(self):
        """Kafka 소비자를 시작하고 메시지 소비 태스크를 생성합니다."""
        if self._running:
            logger.warning("KafkaConsumer is already running.")
            return

        with self.tracer.start_as_current_span("PaymentKafkaConsumer.start") as span:
            span.set_attribute(SpanAttributes.MESSAGING_SYSTEM, "kafka")
            span.set_attribute(SpanAttributes.MESSAGING_KAFKA_CONSUMER_GROUP, self.group_id)
            span.set_attribute("app.kafka.bootstrap_servers", self.bootstrap_servers)
            span.set_attribute("app.kafka.subscribed_topic", self.topic_to_subscribe)
            try:
                self.consumer = AIOKafkaConsumer(
                    self.topic_to_subscribe, # 생성자에서 받은 토픽 사용
                    bootstrap_servers=self.bootstrap_servers,
                    group_id=self.group_id,
                    auto_offset_reset='latest',
                    value_deserializer=lambda m: json.loads(m.decode('utf-8')),
                    enable_auto_commit=False # 수동 커밋 또는 핸들러 성공 후 커밋 권장
                )
                await self.consumer.start()
                self._running = True
                asyncio.create_task(self.consume_messages()) # 비동기 태스크로 실행
                logger.info(f"Kafka consumer started for group '{self.group_id}', subscribed to topic '{self.topic_to_subscribe}'.")
                span.set_status(Status(StatusCode.OK))
            except Exception as e:
                logger.error(f"Failed to start Kafka consumer: {e}", exc_info=True)
                span.record_exception(e)
                span.set_status(Status(StatusCode.ERROR, f"KafkaConsumerStartFailed: {str(e)}"))
                self._running = False # 시작 실패 시 상태 업데이트
                raise # 시작 실패는 심각한 문제이므로 예외를 다시 발생시킬 수 있음

    async def consume_messages(self):
        """메시지를 지속적으로 소비하고 처리합니다."""
        if not self.consumer:
            logger.error("Consumer not initialized. Call start() first.")
            return

        try:
            # AIOKafkaInstrumentor가 이 루프에서 각 메시지 수신 시 자동으로 CONSUMER 스팬을 생성하고 활성화합니다.
            async for msg in self.consumer:
                # 자동 생성된 현재 스팬(CONSUMER 스팬) 가져오기
                current_span = trace.get_current_span()
                if not current_span.is_recording(): # 샘플링되지 않은 경우 아무것도 하지 않음
                    # 핸들러는 호출해야 할 수 있으나, 스팬 관련 작업은 생략
                    # 여기서는 일단 단순하게 처리
                    pass # 또는 아래 로직을 그대로 실행하되, set_attribute 등만 is_recording 블록 안으로

                event_type = None # 루프마다 초기화
                try:
                    logger.info(f"Received Kafka message from topic: {msg.topic}, partition: {msg.partition}, offset: {msg.offset}")
                    
                    # 자동 생성된 CONSUMER 스팬에 기본 메시지 정보 추가
                    if current_span.is_recording():
                        current_span.set_attribute(SpanAttributes.MESSAGING_MESSAGE_ID, str(msg.offset))
                        current_span.set_attribute(SpanAttributes.MESSAGING_KAFKA_PARTITION, msg.partition)
                        if msg.key:
                            current_span.set_attribute(SpanAttributes.MESSAGING_KAFKA_MESSAGE_KEY, msg.key.decode() if isinstance(msg.key, bytes) else str(msg.key))
                        # AIOKafkaInstrumentor가 SpanAttributes.MESSAGING_DESTINATION (topic) 등도 설정해줄 것임

                    # 1. 메시지 헤더에서 eventType 확인
                    if hasattr(msg, 'headers') and msg.headers:
                        for key, value in msg.headers:
                            if key == 'eventType': # Debezium Outbox SMT 등에 의해 설정된 헤더
                                event_type = value.decode('utf-8')
                                logger.info(f"Found event_type in message header: {event_type}")
                                if current_span.is_recording():
                                    current_span.set_attribute("app.event.type_source", "header")
                                break
                    
                    # 2. payload 처리 (msg.value는 이미 JSON 객체로 역직렬화됨)
                    message_dict = msg.value 
                    
                    if not isinstance(message_dict, dict):
                        err_msg = f"Deserialized message is not a dictionary: {type(message_dict)}"
                        logger.error(err_msg)
                        if current_span.is_recording():
                            current_span.set_attribute("app.message.parsing_error", "NotADictionary")
                            current_span.set_status(Status(StatusCode.ERROR, err_msg))
                        await self.consumer.commit() # 오류 발생 시에도 커밋 (재처리 방지)
                        continue
                    
                    # Debezium Outbox 패턴을 사용한다면, message_dict 자체가 Outbox SMT에 의해 변환된 최종 payload일 수 있음
                    # 또는 message_dict 내에 'payload' 필드가 있고, 그 안에 실제 데이터가 문자열화된 JSON으로 있을 수 있음
                    # 현재 코드는 message_dict['payload']를 가정하고 있음
                    
                    actual_payload = None
                    if 'payload' in message_dict:
                        payload_content = message_dict['payload']
                        if current_span.is_recording():
                             current_span.set_attribute("app.payload.raw_type", str(type(payload_content)))

                        if isinstance(payload_content, str):
                            try:
                                actual_payload = json.loads(payload_content)
                                logger.info("Successfully parsed string payload to JSON")
                                if current_span.is_recording():
                                    current_span.add_event("StringPayloadParsed")
                            except json.JSONDecodeError as je:
                                err_msg = f"Failed to parse string payload: {str(je)}"
                                logger.error(err_msg, exc_info=True)
                                if current_span.is_recording():
                                    current_span.record_exception(je)
                                    current_span.set_attribute("app.message.parsing_error", "PayloadJSONDecodeError")
                                    current_span.set_status(Status(StatusCode.ERROR, err_msg))
                                await self.consumer.commit()
                                continue
                        elif isinstance(payload_content, dict):
                            actual_payload = payload_content # 이미 dict 형태
                            logger.info("Payload is already a dictionary.")
                        else:
                            err_msg = f"Unexpected 'payload' field type: {type(payload_content)}"
                            logger.error(err_msg)
                            if current_span.is_recording():
                                current_span.set_attribute("app.message.parsing_error", "UnexpectedPayloadType")
                                current_span.set_status(Status(StatusCode.ERROR, err_msg))
                            await self.consumer.commit()
                            continue
                    else: # 'payload' 필드가 없는 경우, message_dict 전체를 페이로드로 간주할 수 있음 (상황에 따라)
                        logger.warning("No 'payload' field in message, considering entire message as payload.")
                        actual_payload = message_dict # 또는 에러 처리

                    if actual_payload is None:
                        err_msg = "Payload could not be determined."
                        logger.error(err_msg)
                        if current_span.is_recording():
                             current_span.set_status(Status(StatusCode.ERROR, err_msg))
                        await self.consumer.commit()
                        continue

                    if current_span.is_recording():
                        # 페이로드 미리보기 (민감 정보 주의, 길이 제한)
                        try:
                            payload_preview = json.dumps(actual_payload, ensure_ascii=False)[:256]
                            current_span.set_attribute("app.message.payload_preview", payload_preview)
                        except TypeError: # Not serializable
                            current_span.set_attribute("app.message.payload_preview", str(actual_payload)[:256])


                    # 헤더에서 event_type을 못 찾았으면, 파싱된 페이로드에서 'type' 필드 확인
                    if not event_type and isinstance(actual_payload, dict) and 'type' in actual_payload:
                        event_type = actual_payload['type']
                        logger.info(f"Found event_type in parsed payload: {event_type}")
                        if current_span.is_recording():
                            current_span.set_attribute("app.event.type_source", "payload_field")
                    
                    if not event_type:
                        err_msg = f"No event_type found in message. Headers: {msg.headers}, Payload Preview: {str(actual_payload)[:100]}"
                        logger.error(err_msg)
                        if current_span.is_recording():
                            current_span.set_attribute("app.event.type_missing", True)
                            current_span.set_status(Status(StatusCode.ERROR, "EventTypeMissing"))
                        await self.consumer.commit()
                        continue
                    
                    if current_span.is_recording():
                        current_span.set_attribute("app.event.type", event_type) # 최종 결정된 이벤트 타입

                    # 핸들러 호출
                    if event_type in self.handlers:
                        logger.info(f"Calling handler for event_type: {event_type}")
                        # 핸들러 실행. 핸들러 내부에서 추가적인 자식 스팬 생성 가능.
                        await self.handlers[event_type](actual_payload)
                        logger.info(f"Handler processing completed for event_type: {event_type}")
                        # 성공 시 스팬 상태는 자동으로 OK가 되거나, AIOKafkaInstrumentor가 처리.
                        # 명시적으로 OK를 설정해도 무방.
                        if current_span.is_recording():
                            current_span.set_status(Status(StatusCode.OK))
                    else:
                        logger.warning(f"No handler registered for event_type: {event_type}")
                        if current_span.is_recording():
                            current_span.set_attribute("app.handler.not_found", True)
                            current_span.set_status(Status(StatusCode.OK, f"NoHandlerForEventType_{event_type}")) # 에러는 아님

                    await self.consumer.commit() # 메시지 처리 완료 후 커밋
                
                except Exception as e_proc: # 메시지 처리 로직 내의 예외
                    logger.error(f"Error processing message (event_type: {event_type or 'unknown'}): {str(e_proc)}", exc_info=True)
                    if current_span.is_recording():
                        current_span.record_exception(e_proc)
                        current_span.set_status(Status(StatusCode.ERROR, f"MessageHandlerError: {str(e_proc)}"))
                    try: # 오류 발생 시에도 커밋 시도
                        await self.consumer.commit()
                    except Exception as e_commit:
                        logger.error(f"Failed to commit offset after error: {e_commit}", exc_info=True)
                        # 커밋 실패 시 추가적인 오류 처리 로직 (예: 재시도, 로깅) 필요 가능성
            
        except asyncio.CancelledError:
            logger.info("Consume messages task was cancelled.")
            # 이 경우, 외부에서 stop()이 호출되었을 가능성이 높음.
        except Exception as e_loop: # 소비자 루프 자체의 심각한 오류 (예: Kafka 연결 끊김)
            logger.error(f"Kafka consumer loop error: {str(e_loop)}", exc_info=True)
            # 이 경우 현재 스팬 컨텍스트가 없을 수 있으므로, 별도 처리.
            # 소비자 재시작 로직 등이 필요할 수 있음.
            self._running = False # 실행 상태 업데이트
        finally:
            # consume_messages 태스크가 종료될 때 stop을 호출하는 것은
            # 외부에서 명시적으로 stop을 호출하는 로직과 충돌할 수 있습니다.
            # 일반적으로는 애플리케이션 종료 시 외부에서 stop()을 한 번 호출하는 것이 좋습니다.
            # 만약 여기서 stop을 호출해야 한다면, 이미 중지된 상태인지 확인 필요.
            logger.info("Consume_messages loop finished or encountered an error.")
            if self._running: # 아직 실행 중으로 표시되어 있다면 (예: 루프 내 오류로 종료)
                 await self.stop() # 정상 종료가 아닌 경우 stop 호출

    async def stop(self):
        """Kafka 소비자를 중지합니다."""
        if not self._running and not self.consumer: # 이미 중지되었거나 시작되지 않은 경우
            logger.info("KafkaConsumer is not running or not initialized.")
            return

        with self.tracer.start_as_current_span("PaymentKafkaConsumer.stop") as span:
            try:
                if self.consumer:
                    logger.info(f"Stopping Kafka consumer for group '{self.group_id}'...")
                    await self.consumer.stop()
                    logger.info("Kafka consumer stopped successfully.")
                self._running = False
                self.consumer = None # 리소스 정리
                span.set_status(Status(StatusCode.OK))
            except Exception as e:
                logger.error(f"Error stopping Kafka consumer: {e}", exc_info=True)
                span.record_exception(e)
                span.set_status(Status(StatusCode.ERROR, f"KafkaConsumerStopFailed: {str(e)}"))