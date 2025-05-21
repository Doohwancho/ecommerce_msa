# app/config/kafka_consumer.py
from aiokafka import AIOKafkaConsumer
import json
import asyncio
import logging
from functools import partial
from typing import Dict, Callable, Any, Optional
import threading
import queue

logger = logging.getLogger(__name__)

class OrderKafkaConsumer:
    def __init__(self, bootstrap_servers: str, group_id: str):
        self.bootstrap_servers = bootstrap_servers
        self.group_id = group_id
        self.consumer = None
        self.handlers: Dict[str, Dict[str, Callable]] = {}  # topic -> {event_type -> handler}
        self.running = False
        self.consumer_thread = None
        self.message_queue = queue.Queue()  # 메시지를 저장할 큐
        
    def register_handler(self, topic: str, handler: Callable, event_type: str = None):
        """등록된 토픽과 이벤트 타입에 대한 핸들러 함수를 등록합니다."""
        if topic not in self.handlers:
            self.handlers[topic] = {}
        self.handlers[topic][event_type] = handler
        logger.info(f"Registered handler for topic: {topic}, event_type: {event_type}")
        
    async def _get_consumer(self):
        """AIOKafkaConsumer 인스턴스를 생성하고 반환합니다."""
        return AIOKafkaConsumer(
            *self.handlers.keys(),  # 등록된 모든 핸들러의 토픽을 구독
            bootstrap_servers=self.bootstrap_servers,
            group_id=self.group_id,
            auto_offset_reset='latest',
            enable_auto_commit=False,
            value_deserializer=lambda x: json.loads(x.decode('utf-8'))
        )

    async def _consume_loop(self):
        """Kafka 소비 루프 - 비동기로 실행됩니다."""
        self.consumer = await self._get_consumer()
        await self.consumer.start()
        logger.info(f"Kafka consumer started. Subscribed to topics: {list(self.handlers.keys())}")
        
        try:
            async for message in self.consumer:
                if not self.running:
                    break
                    
                topic = message.topic
                if topic in self.handlers:
                    try:
                        logger.info(f"Received message from topic: {topic}")
                        
                        # 1. 메시지 헤더에서 eventType 확인
                        event_type = None
                        
                        # 메시지 헤더가 있는지 확인
                        if message.headers:
                            for key, value in message.headers:
                                if key == 'eventType':
                                    event_type = value.decode('utf-8')
                                    logger.info(f"Found event_type in message header: {event_type}")
                                    break
                        
                        # 2. 메시지 본문 처리
                        msg_value = message.value
                        
                        # 메시지가 딕셔너리인지 확인
                        if not isinstance(msg_value, dict):
                            logger.error(f"Message is not a dictionary: {type(msg_value)}")
                            await self.consumer.commit()
                            continue
                        
                        # payload 필드 확인
                        if 'payload' not in msg_value:
                            logger.error("Message does not contain 'payload' field")
                            await self.consumer.commit()
                            continue
                        
                        # payload 처리
                        payload_data = msg_value['payload']
                        logger.info(f"Payload data type: {type(payload_data)}")
                        
                        # payload가 문자열이면 JSON으로 파싱
                        if isinstance(payload_data, str):
                            try:
                                parsed_payload = json.loads(payload_data)
                                logger.info(f"Successfully parsed payload string to JSON")
                            except json.JSONDecodeError as e:
                                logger.error(f"Failed to parse payload string: {str(e)}")
                                await self.consumer.commit()
                                continue
                        else:
                            logger.error(f"Payload is not a string: {type(payload_data)}")
                            await self.consumer.commit()
                            continue
                        
                        # 3. 이벤트 타입 결정
                        # 헤더에서 이벤트 타입을 찾지 못한 경우에만 payload에서 확인
                        if not event_type and isinstance(parsed_payload, dict) and 'type' in parsed_payload:
                            event_type = parsed_payload['type']
                            logger.info(f"Found event_type in payload: {event_type}")
                        
                        # 이벤트 타입 결정 실패 시 에러 로깅 후 건너뜀
                        if not event_type:
                            logger.error(f"No event_type found in message for topic {topic}")
                            await self.consumer.commit()
                            continue
                        
                        # 4. 핸들러 실행
                        if event_type in self.handlers[topic]:
                            handler = self.handlers[topic][event_type]
                            try:
                                await handler(parsed_payload)
                                logger.info(f"Successfully processed message from topic {topic}, event_type {event_type}")
                            except Exception as e:
                                logger.error(f"Error in handler for topic {topic}, event_type {event_type}: {str(e)}")
                        else:
                            logger.warning(f"No handler registered for event_type: {event_type} in topic: {topic}")
                        
                        # 메시지 처리 완료 후 커밋
                        await self.consumer.commit()
                        
                    except Exception as e:
                        logger.error(f"Error processing message from topic {topic}: {str(e)}", exc_info=True)
                        # 오류가 있어도 커밋
                        await self.consumer.commit()
        except Exception as e:
            logger.error(f"Error in Kafka consumer loop: {str(e)}", exc_info=True)
        finally:
            if self.consumer:
                await self.consumer.stop()
                logger.info("Kafka consumer closed")
    
    # 다른 메서드는 동일하게 유지
    async def process_messages(self):
        """메인 이벤트 루프에서 메시지를 처리합니다."""
        # 기존 코드 유지
        while self.running:
            try:
                # 큐에서 메시지를 가져옵니다 (논블로킹)
                while not self.message_queue.empty():
                    topic, event_type, data = self.message_queue.get_nowait()
                    handler = self.handlers.get(topic, {}).get(event_type)
                    
                    if handler:
                        try:
                            await handler(data)
                            logger.info(f"Successfully processed message from topic {topic}, event_type {event_type}")
                        except Exception as e:
                            logger.error(f"Error in handler for topic {topic}, event_type {event_type}: {str(e)}")
                    else:
                        logger.warning(f"No handler found for topic: {topic}, event_type: {event_type}")
                    
                    self.message_queue.task_done()
                
                # 잠시 대기 후 다음 처리
                await asyncio.sleep(0.1)
            except queue.Empty:
                # 큐가 비어있으면 다음 처리로 넘어감
                await asyncio.sleep(0.1)
            except Exception as e:
                logger.error(f"Error processing messages: {str(e)}")
                await asyncio.sleep(1)  # 오류 시 더 긴 대기
    
    async def start(self):
        """Kafka 소비자를 시작합니다."""
        if not self.handlers:
            logger.warning("No handlers registered. Consumer not started.")
            return
            
        self.running = True
        # 비동기 소비 루프 시작
        asyncio.create_task(self._consume_loop())
        logger.info("Kafka consumer started")
    
    async def stop(self):
        """Kafka 소비자를 종료합니다."""
        self.running = False
        if self.consumer:
            await self.consumer.stop()
            logger.info("Kafka consumer stopped")