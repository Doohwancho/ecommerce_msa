from aiokafka import AIOKafkaConsumer
import asyncio
import json
from typing import Callable, Dict, Any

class KafkaConsumer:
    def __init__(self, bootstrap_servers: str, group_id: str):
        self.bootstrap_servers = bootstrap_servers
        self.group_id = group_id
        self.consumer = None
        self.handlers: Dict[str, Callable] = {}
    
    def register_handler(self, event_type: str, handler: Callable):
        """특정 이벤트 타입에 대한 핸들러 등록"""
        self.handlers[event_type] = handler
        
    async def start(self):
        self.consumer = AIOKafkaConsumer(
            'order',  # 실제 메시지가 있는 토픽으로 변경
            bootstrap_servers=self.bootstrap_servers,
            group_id=self.group_id,
            auto_offset_reset='earliest',  # 처음부터 읽기
            value_deserializer=lambda m: json.loads(m.decode('utf-8'))
        )
        await self.consumer.start()
        asyncio.create_task(self.consume_messages())  # 비동기 태스크로 실행
        
    async def consume_messages(self):
        try:
            async for msg in self.consumer:
                print(f"Received message: {msg.value}")  # 디버깅을 위한 로그 추가
                
                # Debezium 포맷의 메시지 처리
                payload = msg.value
                if isinstance(payload, dict) and 'schema' in payload and 'payload' in payload:
                    # Debezium 메시지 처리
                    try:
                        # JSON 문자열 파싱
                        event_data = json.loads(payload['payload'])
                        print(f"Parsed event data: {event_data}")
                        
                        # event_type 결정 (payload에 type 필드가 없으므로 상태로 판단)
                        event_type = 'order_created'  # 기본값
                        
                        if event_type in self.handlers:
                            await self.handlers[event_type](event_data)
                    except json.JSONDecodeError as e:
                        print(f"Error decoding JSON payload: {e}")
                else:
                    # 일반 메시지 처리
                    event_type = payload.get('type', 'order_created')  # 기본값 설정
                    if event_type in self.handlers:
                        await self.handlers[event_type](payload)
                    
        except Exception as e:
            print(f"Error consuming messages: {e}")
        finally:
            await self.stop()
            
    async def stop(self):
        if self.consumer:
            await self.consumer.stop()