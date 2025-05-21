# app/config/kafka_consumer.py
from aiokafka import AIOKafkaConsumer
import json
import asyncio
import logging
from typing import Dict, Callable, Any # Optional 제거 (사용 안됨)
# import queue # threading.Queue를 사용 중이므로 이 줄은 제거하거나 threading.Queue로 명확히
import threading # _consume_loop가 async이므로 threading.Queue는 여기서는 부적합할 수 있음. asyncio.Queue 고려.
                  # 현재 _consume_loop는 message_queue를 직접 사용하지 않고 바로 처리함. process_messages가 사용.
                  # process_messages 메서드가 실제로 사용되는지, _consume_loop와 어떻게 연동되는지 확인 필요.
                  # 여기서는 _consume_loop에 직접 OpenTelemetry 적용.

from opentelemetry import trace
# Semantic Conventions를 사용하면 더 명확합니다.
# from opentelemetry.semconv.trace import SpanAttributes # 예시

logger = logging.getLogger(__name__)

class OrderKafkaConsumer:
    def __init__(self, bootstrap_servers: str, group_id: str):
        self.bootstrap_servers = bootstrap_servers
        self.group_id = group_id
        self.consumer = None
        self.handlers: Dict[str, Dict[str, Callable]] = {}  # topic -> {event_type -> handler}
        self.running = False
        # self.consumer_thread = None # _consume_loop가 async이므로 별도 스레드 관리는 필요 없어 보임
        # self.message_queue = queue.Queue() # _consume_loop에서 직접 처리하므로 일단 주석 처리

    def register_handler(self, topic: str, handler: Callable, event_type: str = None):
        if topic not in self.handlers:
            self.handlers[topic] = {}
        self.handlers[topic][event_type] = handler
        logger.info(f"Registered handler for topic: {topic}, event_type: {event_type}")

    async def _get_consumer(self):
        return AIOKafkaConsumer(
            *self.handlers.keys(),
            bootstrap_servers=self.bootstrap_servers,
            group_id=self.group_id,
            auto_offset_reset='latest',
            enable_auto_commit=False, # 수동 커밋 사용
            value_deserializer=lambda x: json.loads(x.decode('utf-8')),
            # AIOKafkaInstrumentor가 컨텍스트 전파를 위해 헤더를 사용합니다.
            # key_deserializer도 필요하다면 설정
        )

    async def _consume_loop(self):
        self.consumer = await self._get_consumer()
        await self.consumer.start()
        logger.info(f"Kafka consumer started. Subscribed to topics: {list(self.handlers.keys())}")

        try:
            async for message in self.consumer: # AIOKafkaInstrumentor가 이 루프의 각 메시지에 대해 스팬을 시작/종료
                if not self.running:
                    break
                
                # 현재 활성화된 스팬 (AIOKafkaInstrumentor가 생성) 가져오기
                current_span = trace.get_current_span()

                topic = message.topic
                event_type = None # 여기서 초기화

                try:
                    logger.info(f"Received message from topic: {topic}")
                    # 스팬에 기본 메시지 정보 추가
                    if current_span.is_recording():
                        current_span.set_attribute("messaging.system", "kafka")
                        current_span.set_attribute("messaging.destination.name", topic) # Kafka 토픽 이름
                        current_span.set_attribute("messaging.message.id", str(message.offset)) # 메시지 오프셋
                        current_span.set_attribute("messaging.kafka.consumer.group", self.group_id)
                        current_span.set_attribute("messaging.kafka.partition", message.partition)
                        if message.key:
                            current_span.set_attribute("messaging.kafka.message.key", message.key.decode() if isinstance(message.key, bytes) else str(message.key))

                    # 1. 메시지 헤더에서 eventType 확인
                    if message.headers:
                        for key, value in message.headers:
                            if key == 'eventType': # Debezium 또는 다른 프로듀서가 설정한 헤더
                                event_type = value.decode('utf-8')
                                logger.info(f"Found event_type in message header: {event_type}")
                                if current_span.is_recording():
                                    current_span.set_attribute("app.event_type_source", "header")
                                break
                    
                    # 2. 메시지 본문 처리 (Debezium payload 등)
                    msg_value = message.value # 이미 JSON 객체로 역직렬화됨
                    
                    if not isinstance(msg_value, dict):
                        logger.error(f"Message value is not a dictionary: {type(msg_value)}")
                        await self.consumer.commit({message.topic: message.offset}) # 특정 메시지만 커밋 (aiokafka 방식 확인 필요)
                                                                                    # 또는 전체 배치를 커밋하는 로직에 따라 조정
                        # AIOKafkaConsumer.commit()는 인자 없이 호출 시 마지막으로 반환된 모든 메시지 커밋
                        await self.consumer.commit() 
                        continue

                    payload_data_str = msg_value.get('payload') # Debezium 메시지라면 'payload' 필드가 있을 것
                    parsed_payload = None

                    if payload_data_str is None:
                        logger.warning("Message does not contain 'payload' field. Treating message value as payload.")
                        # 페이로드가 없는 단순 JSON 메시지일 수 있음. 이 경우 msg_value 자체를 payload로 간주할 수 있음.
                        parsed_payload = msg_value # 또는 에러 처리
                    elif isinstance(payload_data_str, str):
                        try:
                            parsed_payload = json.loads(payload_data_str)
                            logger.info(f"Successfully parsed payload string to JSON")
                        except json.JSONDecodeError as e:
                            logger.error(f"Failed to parse payload string: {str(e)}")
                            if current_span.is_recording():
                                current_span.record_exception(e)
                                current_span.set_status(trace.Status(trace.StatusCode.ERROR, "Payload JSONDecodeError"))
                            await self.consumer.commit()
                            continue
                    elif isinstance(payload_data_str, dict): # payload가 이미 객체인 경우
                        parsed_payload = payload_data_str
                        logger.info("Payload is already a dictionary.")
                    else:
                        logger.error(f"Payload is not a string or dict: {type(payload_data_str)}")
                        if current_span.is_recording():
                             current_span.set_status(trace.Status(trace.StatusCode.ERROR, "Invalid payload type"))
                        await self.consumer.commit()
                        continue

                    # Debezium 관련 속성 추가 (parsed_payload가 Debezium 구조를 따른다고 가정)
                    if isinstance(parsed_payload, dict) and current_span.is_recording():
                        if "op" in parsed_payload: # Debezium operation (c, u, d, r)
                            current_span.set_attribute("debezium.operation", parsed_payload["op"])
                        if "source" in parsed_payload and isinstance(parsed_payload["source"], dict):
                            source_info = parsed_payload["source"]
                            if "db" in source_info:
                                current_span.set_attribute("debezium.source.db", source_info["db"])
                            if "table" in source_info:
                                current_span.set_attribute("debezium.source.table", source_info["table"])
                            if "connector" in source_info: # Debezium connector 이름
                                current_span.set_attribute("debezium.source.connector", source_info["connector"])
                    
                    # 3. 이벤트 타입 결정 (헤더에 없었을 경우 payload에서)
                    if not event_type and isinstance(parsed_payload, dict) and 'type' in parsed_payload:
                        event_type = parsed_payload['type']
                        logger.info(f"Found event_type in payload: {event_type}")
                        if current_span.is_recording():
                            current_span.set_attribute("app.event_type_source", "payload")
                    
                    if not event_type:
                        logger.error(f"No event_type found in message for topic {topic}")
                        if current_span.is_recording():
                            current_span.set_status(trace.Status(trace.StatusCode.ERROR, "Missing event_type"))
                        await self.consumer.commit()
                        continue
                    
                    if current_span.is_recording():
                        current_span.set_attribute("app.event_type", event_type) # 최종 결정된 event_type
                        current_span.set_attribute("app.handler.topic", topic) # 핸들러 정보 명시

                    # 4. 핸들러 실행
                    if event_type in self.handlers.get(topic, {}):
                        handler = self.handlers[topic][event_type]
                        logger.info(f"Executing handler for topic {topic}, event_type {event_type}")
                        await handler(parsed_payload) # 핸들러 내에서 추가적인 자식 스팬 생성 가능
                        logger.info(f"Successfully processed message from topic {topic}, event_type {event_type}")
                        # 성공 시 스팬 상태는 기본적으로 OK (별도 설정 불필요)
                    else:
                        logger.warning(f"No handler registered for event_type: {event_type} in topic: {topic}")
                        if current_span.is_recording():
                             current_span.set_status(trace.Status(trace.StatusCode.UNSET, f"No handler for event_type {event_type}"))


                    await self.consumer.commit() # 성공적으로 처리 후 커밋

                except Exception as e:
                    logger.error(f"Error processing message from topic {topic}: {str(e)}", exc_info=True)
                    if current_span.is_recording():
                        current_span.record_exception(e) # 예외 기록
                        current_span.set_status(trace.Status(trace.StatusCode.ERROR, str(e))) # 스팬 상태 ERROR로 설정
                    
                    # 오류 발생 시에도 커밋 (재처리 방지 또는 오류 큐 등으로 보내는 로직 고려)
                    # 현재 로직은 오류 발생 시에도 커밋합니다. 필요에 따라 조정하세요.
                    if self.consumer and message: # consumer와 message가 유효한지 확인
                         await self.consumer.commit()
        
        except Exception as e:
            logger.error(f"Critical error in Kafka consumer loop: {str(e)}", exc_info=True)
            # 여기서 발생하는 예외는 루프 자체의 문제일 수 있으므로, 현재 스팬 컨텍스트가 없을 수 있음.
            # 필요하다면 새로운 스팬을 만들어 에러 기록.
        finally:
            if self.consumer:
                await self.consumer.stop()
                logger.info("Kafka consumer closed")

    async def start(self):
        if not self.handlers:
            logger.warning("No handlers registered. Consumer not started.")
            return
        
        self.running = True
        asyncio.create_task(self._consume_loop()) # 비동기 소비 루프 시작
        logger.info("Kafka consumer task created")

    async def stop(self):
        self.running = False
        # _consume_loop의 finally 블록에서 consumer.stop()이 호출되므로 여기서 중복 호출하지 않아도 될 수 있음.
        # 하지만 명시적으로 호출하는 것이 안전할 수 있습니다.
        if self.consumer and self.consumer._running: # consumer가 실행 중일 때만 stop 시도
             try:
                 await self.consumer.stop()
             except Exception as e:
                 logger.error(f"Error stopping kafka consumer: {e}", exc_info=True)
        logger.info("Kafka consumer stop requested")

    # process_messages 메서드는 현재 _consume_loop와 직접 연동되지 않는 것으로 보입니다.
    # 만약 이 메서드를 통해 메시지를 처리한다면, 해당 부분에도 컨텍스트 전파 및 스팬 관리가 필요합니다.
    # 여기서는 _consume_loop에 집중했습니다.
    async def process_messages(self):
        # 이 메서드가 사용된다면, message_queue에 넣을 때와 꺼낼 때 컨텍스트 전파 필요
        logger.warning("process_messages method is not directly integrated with OpenTelemetry in this example.")
        # ... 기존 코드 ...
        pass