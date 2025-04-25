from aiokafka import AIOKafkaConsumer
import asyncio
import json
import logging
from typing import Callable, Dict, Any

logger = logging.getLogger(__name__)

class KafkaConsumer:
    def __init__(self, bootstrap_servers: str, group_id: str):
        self.bootstrap_servers = bootstrap_servers
        self.group_id = group_id
        self.consumer = None
        self.handlers: Dict[str, Callable] = {}
    
    def register_handler(self, event_type: str, handler: Callable):
        """특정 이벤트 타입에 대한 핸들러 등록"""
        self.handlers[event_type] = handler
        logger.info(f"Registered handler for event_type: {event_type}")
        
    async def start(self):
        self.consumer = AIOKafkaConsumer(
            'order',  # 실제 메시지가 있는 토픽으로 변경
            bootstrap_servers=self.bootstrap_servers,
            group_id=self.group_id,
            auto_offset_reset='latest',  # 가장 최근 메시지부터 읽기
            value_deserializer=lambda m: json.loads(m.decode('utf-8'))
        )
        await self.consumer.start()
        logger.info("Kafka consumer started")
        asyncio.create_task(self.consume_messages())  # 비동기 태스크로 실행
        
    async def consume_messages(self):
        try:
            async for msg in self.consumer:
                logger.info(f"Received Kafka message from topic: {msg.topic}")
                
                try:
                    # 1. 메시지 헤더에서 eventType 확인
                    event_type = None
                    
                    # 메시지 헤더가 있는지 확인
                    if hasattr(msg, 'headers') and msg.headers:
                        for key, value in msg.headers:
                            if key == 'eventType':
                                event_type = value.decode('utf-8')
                                logger.info(f"Found event_type in message header: {event_type}")
                                break
                    
                    # 2. 메시지 본문 처리
                    message = msg.value
                    
                    # 메시지가 딕셔너리인지 확인
                    if not isinstance(message, dict):
                        logger.error(f"Message is not a dictionary: {type(message)}")
                        continue
                    
                    # 3. Debezium 메시지 형식 확인
                    if 'schema' in message and 'payload' in message:
                        # Payload 필드가 있는지 확인
                        payload_data = message['payload']
                        logger.info(f"Payload data type: {type(payload_data)}")
                        
                        # payload가 문자열이면 JSON으로 파싱
                        if isinstance(payload_data, str):
                            try:
                                parsed_payload = json.loads(payload_data)
                                logger.info(f"Successfully parsed payload string to JSON")
                            except json.JSONDecodeError as e:
                                logger.error(f"Failed to parse payload string: {str(e)}")
                                continue
                        else:
                            # 페이로드가 이미 객체인 경우
                            parsed_payload = payload_data
                    else:
                        # Debezium 형식이 아닌 경우
                        parsed_payload = message
                    
                    # 4. 이벤트 타입 결정
                    # 헤더에서 이벤트 타입을 찾지 못한 경우에만 payload에서 확인
                    if not event_type and isinstance(parsed_payload, dict):
                        # payload에서 'type' 필드 확인
                        if 'type' in parsed_payload:
                            event_type = parsed_payload['type']
                            logger.info(f"Found event_type in payload: {event_type}")
                    
                    # 이벤트 타입 결정 실패 시 에러 로깅 후 건너뜀
                    if not event_type:
                        logger.error(f"No event_type found in message for topic {msg.topic}")
                        continue
                    
                    # 5. 핸들러 확인 및 실행
                    if event_type in self.handlers:
                        logger.info(f"Calling handler for event_type: {event_type}")
                        await self.handlers[event_type](parsed_payload)
                        logger.info(f"Handler processing completed for event_type: {event_type}")
                    else:
                        logger.warning(f"No handler registered for event_type: {event_type}")
                
                except Exception as e:
                    logger.error(f"Error processing message: {str(e)}", exc_info=True)
                    
        except Exception as e:
            logger.error(f"Consumer error: {str(e)}", exc_info=True)
        finally:
            await self.stop()
            
    async def stop(self):
        if self.consumer:
            await self.consumer.stop()
            logger.info("Kafka consumer stopped")