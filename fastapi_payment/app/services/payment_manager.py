from app.config.payment_kafka import KafkaConsumer # OTel 트레이싱이 적용된 KafkaConsumer
from app.services.payment_service import PaymentService
from app.config.payment_database import WriteSessionLocal # SQLAlchemyInstrumentor가 자동 계측
from app.schemas.payment_schemas import PaymentCreate, PaymentMethod
from app.models.outbox import Outbox # Outbox 모델
import uuid
import json
from app.config.payment_logging import logger # 기존 로거 사용
import asyncio
import datetime

# OpenTelemetry API 임포트
from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode, SpanKind
from opentelemetry.semconv.trace import SpanAttributes # 시맨틱 컨벤션 사용 권장

# 모듈 수준 트레이서
tracer = trace.get_tracer(__name__, "0.1.0") # 계측기 이름 및 버전 명시

class PaymentManager:
    def __init__(self):
        self.kafka_consumer: KafkaConsumer | None = None # 타입 힌트 명시
        self.max_retries = 3
        # self.tracer는 모듈 수준 tracer 사용

    async def initialize_kafka(self, bootstrap_servers: str, group_id: str, topic: str = 'order'):
        """Kafka Consumer를 초기화하고 시작합니다."""
        with tracer.start_as_current_span("PaymentManager.initialize_kafka") as span:
            span.set_attribute(SpanAttributes.MESSAGING_SYSTEM, "kafka")
            span.set_attribute("app.kafka.bootstrap_servers", bootstrap_servers)
            span.set_attribute("app.kafka.group_id", group_id)
            span.set_attribute("app.kafka.subscribed_topic", topic)
            
            logger.info(f"Initializing Kafka consumer for group: {group_id}, topic: {topic}")
            try:
                self.kafka_consumer = KafkaConsumer(
                    bootstrap_servers=bootstrap_servers,
                    group_id=group_id,
                    topic=topic # KafkaConsumer가 토픽을 받도록 수정되었다고 가정
                )
                span.add_event("KafkaConsumerInstanceCreated")

                # 이벤트 핸들러 등록
                self.kafka_consumer.register_handler('order_created', self.handle_order_created)
                span.add_event("EventHandlerRegistered", {"event.type": "order_created"})
                
                # Kafka 소비자 시작 (KafkaConsumer.start 내부에 자체 스팬이 있을 것임)
                await self.kafka_consumer.start()
                span.add_event("KafkaConsumerStarted")
                
                logger.info(f"PaymentManager Kafka consumer initialized and started successfully.")
                span.set_status(Status(StatusCode.OK))
            except Exception as e:
                logger.error(f"Failed to initialize Kafka for PaymentManager: {e}", exc_info=True)
                span.record_exception(e)
                span.set_status(Status(StatusCode.ERROR, "KafkaInitializationFailed"))
                raise # 초기화 실패는 심각하므로 예외 전파

    async def handle_order_created(self, event_data: dict):
        """'order_created' 이벤트를 처리하여 결제를 생성합니다."""
        # 이 함수는 KafkaConsumer에 의해 호출되며, 이미 부모 Kafka CONSUMER 스팬 컨텍스트 내에서 실행됩니다.
        # 여기서는 이 비즈니스 로직 처리를 위한 자식 스팬을 생성합니다.
        with tracer.start_as_current_span("PaymentManager.handle_order_created", kind=SpanKind.CONSUMER) as span: # 명시적 SpanKind
            span.set_attribute("app.event.type", "order_created")
            # 원본 event_data의 일부를 로깅 또는 속성으로 (민감 정보 주의)
            try:
                span.set_attribute("app.event.data_preview", json.dumps(event_data, ensure_ascii=False)[:256])
            except Exception:
                span.set_attribute("app.event.data_preview", str(event_data)[:256])


            retry_count = 0
            actual_payload = None # 루프 외부에서 선언하여 보상 이벤트에서 사용 가능하도록

            while retry_count < self.max_retries:
                span.add_event(f"ProcessingAttempt", {"retry.count": retry_count + 1, "max.retries": self.max_retries})
                try:
                    logger.info(f"Processing order_created event (attempt {retry_count + 1}): {event_data.get('order_id', 'N/A')}")
                    
                    # Debezium 형식에서 실제 payload 추출 (상세 로직)
                    current_payload_data = event_data # 현재 시도의 페이로드 데이터
                    span.add_event("ExtractingPayloadFromDebezium")
                    if isinstance(current_payload_data, dict):
                        # Debezium outbox SMT를 사용한 경우, 'payload' 필드 자체가 최종 페이로드일 수 있음
                        # 또는 Debezium CDC 이벤트의 표준 구조 ('payload.after.payload')를 따를 수 있음
                        if 'payload' in current_payload_data and isinstance(current_payload_data['payload'], dict) and \
                           'after' in current_payload_data['payload'] and isinstance(current_payload_data['payload']['after'], dict) and \
                           'payload' in current_payload_data['payload']['after']:
                            # Debezium CDC outbox 이벤트의 내부 payload 필드 (이중 payload 구조)
                            after_data = current_payload_data['payload']['after']
                            inner_payload_str = after_data['payload']
                            if isinstance(inner_payload_str, str):
                                try:
                                    actual_payload = json.loads(inner_payload_str)
                                    span.add_event("DebeziumInnerPayloadParsed", {"source": "payload.after.payload_string"})
                                except json.JSONDecodeError as je:
                                    logger.error(f"Failed to parse inner Debezium payload string: {je}")
                                    span.record_exception(je)
                                    raise ValueError(f"Invalid inner payload JSON format: {str(je)}")
                            elif isinstance(inner_payload_str, dict): # 이미 객체인 경우
                                actual_payload = inner_payload_str
                                span.add_event("DebeziumInnerPayloadIsObject", {"source": "payload.after.payload_object"})
                            else:
                                raise ValueError("Unexpected type for Debezium inner payload field.")
                        elif 'payload' in current_payload_data and isinstance(current_payload_data['payload'], (dict,str)):
                            # Outbox SMT가 이미 'payload'를 최종 데이터로 만든 경우
                            payload_content = current_payload_data['payload']
                            if isinstance(payload_content, str):
                                try:
                                    actual_payload = json.loads(payload_content)
                                    span.add_event("DebeziumPayloadParsed", {"source": "payload_string"})
                                except json.JSONDecodeError as je:
                                    logger.error(f"Failed to parse Debezium payload string: {je}")
                                    span.record_exception(je)
                                    raise ValueError(f"Invalid payload JSON format: {str(je)}")
                            else: # dict
                                actual_payload = payload_content
                                span.add_event("DebeziumPayloadIsObject", {"source": "payload_object"})
                        else: # Debezium 형식이 아니거나 예상치 못한 구조
                            actual_payload = current_payload_data # 원본 데이터를 페이로드로 간주
                            span.add_event("UsingRawEventDataAsPayload")
                    else: # dict가 아닌 경우
                         actual_payload = current_payload_data # 그대로 사용 또는 오류 처리
                         logger.warning(f"Event data is not a dict, using as is: {type(current_payload_data)}")

                    if not isinstance(actual_payload, dict): # 최종 페이로드가 dict가 아니면 오류
                        raise ValueError(f"Processed payload is not a dictionary: {type(actual_payload)}")

                    logger.info(f"Extracted payload for payment processing: {actual_payload.get('order_id', 'N/A')}")
                    span.set_attribute("app.payload.extracted", True)
                    try:
                        span.set_attribute("app.payload.preview", json.dumps(actual_payload,ensure_ascii=False)[:256])
                    except: pass


                    # 필수 데이터 필드 검증
                    order_id = actual_payload.get('order_id')
                    total_amount = actual_payload.get('total_amount')
                    items = actual_payload.get('items', [])
                    
                    if not order_id or total_amount is None or not items:
                        err_msg = f"Missing required fields in extracted payload: order_id={order_id}, total_amount={total_amount}, items_present={bool(items)}"
                        logger.error(err_msg)
                        span.set_attribute("app.validation.error", err_msg)
                        raise ValueError(err_msg)
                    
                    span.set_attribute("app.order_id", str(order_id))
                    span.set_attribute("app.order.total_amount", float(total_amount))
                    span.set_attribute("app.order.item_count", len(items))

                    # 테스트용 quantity (실제 로직에서는 더 견고하게 처리)
                    test_quantity = items[0].get('quantity', 0) if items else 0
                    
                    payment_data = PaymentCreate(
                        order_id=str(order_id), # 스키마에 맞게 타입 변환
                        amount=float(total_amount),
                        currency="KRW",
                        payment_method=PaymentMethod.CREDIT_CARD, # 예시, 실제로는 주문 정보에서 가져와야 할 수 있음
                        stock_reserved=test_quantity 
                    )
                    span.add_event("PaymentDataPreparedForService")
                    
                    # DB 세션을 사용하여 PaymentService 호출
                    # SQLAlchemyInstrumentor가 DB 작업 자동 계측
                    async with WriteSessionLocal() as session:
                        payment_service = PaymentService(session) # PaymentService 내부도 트레이싱되면 좋음
                        payment = await payment_service.create_payment(payment_data)
                    
                    logger.info(f"Payment created successfully for order_id: {payment.order_id}, payment_id: {payment.payment_id}")
                    span.set_attribute("app.payment_id", str(payment.id))
                    span.set_attribute("app.payment.status", payment.status.value)
                    span.set_status(Status(StatusCode.OK))
                    return  # 성공적으로 처리, 루프 종료

                except ValueError as ve: # 데이터 검증 또는 파싱 실패 (재시도 불필요)
                    logger.error(f"ValueError processing order_created event (order_id: {actual_payload.get('order_id', 'N/A') if actual_payload else 'N/A'}): {str(ve)}", exc_info=True)
                    span.record_exception(ve)
                    span.set_status(Status(StatusCode.ERROR, f"DataValidationError: {str(ve)}"))
                    # 실패한 이벤트 저장 또는 DLQ 전송 등의 로직 추가 가능
                    # await self._store_failed_event('order_created_validation_error', event_data, str(ve))
                    return # 재시도 루프 종료
                except Exception as e: # 그 외 예외 (네트워크, DB 등 일시적일 수 있음)
                    retry_count += 1
                    logger.error(f"Error processing order_created event (attempt {retry_count}/{self.max_retries}, order_id: {actual_payload.get('order_id', 'N/A') if actual_payload else 'N/A'}): {str(e)}", exc_info=True)
                    span.record_exception(e) # 각 재시도 시 예외 기록
                    
                    if retry_count >= self.max_retries:
                        logger.error(f"All retries failed for order_created event (order_id: {actual_payload.get('order_id', 'N/A') if actual_payload else 'N/A'}). Initiating compensation.")
                        span.set_status(Status(StatusCode.ERROR, "MaxRetriesExceeded_OrderCreated"))
                        if actual_payload: # 페이로드가 성공적으로 추출된 경우에만 보상 시도
                             await self.create_compensation_event(actual_payload, "order_processing_failed_after_retries")
                        else: # 페이로드 추출 실패 시 원본 이벤트로 보상 또는 실패 저장
                             await self._store_failed_event('order_created_max_retries_no_payload', event_data, str(e))
                        return # 재시도 루프 종료
                    
                    # 재시도 전 대기
                    delay = 2 ** (retry_count -1) # 1, 2, 4... 초
                    span.add_event("RetryDelay", {"delay_seconds": delay})
                    await asyncio.sleep(delay)
            
            # 루프를 빠져나왔다면 (성공 또는 모든 재시도 실패 후)
            if retry_count >= self.max_retries and span.get_status().status_code != StatusCode.OK :
                 logger.warning(f"Event processing for order_created failed permanently for event related to order: {actual_payload.get('order_id', 'N/A') if actual_payload else 'N/A'}")
                 # 스팬 상태는 이미 ERROR로 설정되었을 것임

    async def create_compensation_event(self, original_event_payload: dict, reason_type: str):
        """Outbox 패턴을 사용하여 보상 이벤트를 생성합니다."""
        # 이 메서드는 이미 부모 스팬(예: handle_order_created)의 컨텍스트 내에서 실행될 수 있음
        # 자체적인 스팬을 만들어 보상 이벤트 생성 과정을 명확히 추적
        with tracer.start_as_current_span("PaymentManager.create_compensation_event") as span:
            order_id = original_event_payload.get('order_id')
            span.set_attribute("app.order_id", str(order_id))
            span.set_attribute("app.compensation.reason_type", reason_type)
            logger.info(f"Creating compensation event for order {order_id}, reason_type: {reason_type}")

            try:
                # DB 세션 사용 (SQLAlchemyInstrumentor가 DB 작업 자동 계측)
                async with WriteSessionLocal() as session:
                    async with session.begin(): # 명시적 트랜잭션
                        items_for_compensation = original_event_payload.get('items', [])
                        
                        compensation_event_payload = {
                            'type': "payment_processing_failed", # 보상 이벤트의 타입
                            'order_id': str(order_id),
                            'items_to_revert_stock': items_for_compensation, # 재고 복원을 위한 정보
                            'reason': reason_type, # 예: 'order_processing_failed_after_retries'
                            'original_event_preview': json.dumps(original_event_payload, ensure_ascii=False)[:128],
                            'timestamp': datetime.datetime.utcnow().isoformat()
                        }
                        
                        outbox_event = Outbox(
                            id=str(uuid.uuid4()),
                            aggregatetype="payment_compensation", # 또는 "order" 등 상황에 맞게
                            aggregateid=str(order_id),
                            type="payment_processing_failed", # Kafka 메시지 헤더의 eventType
                            payload=compensation_event_payload
                        )
                        session.add(outbox_event)
                        # await session.commit() # async with session.begin() 사용 시 자동 커밋
                
                logger.info(f"Compensation event for order {order_id} (reason: {reason_type}) added to outbox.")
                span.set_status(Status(StatusCode.OK))
            except Exception as e:
                logger.critical(f"Failed to create compensation event for order {order_id}: {str(e)}", exc_info=True)
                span.record_exception(e)
                span.set_status(Status(StatusCode.ERROR, "CompensationEventCreationFailed"))
                # 보상 이벤트 생성 실패는 매우 심각. 별도 알림/모니터링 필요.

    async def stop(self):
        """Kafka Consumer를 중지합니다."""
        if self.kafka_consumer:
            with tracer.start_as_current_span("PaymentManager.stop_kafka") as span:
                logger.info("Stopping PaymentManager's Kafka consumer...")
                try:
                    await self.kafka_consumer.stop() # KafkaConsumer.stop 내부에 자체 스팬이 있을 것임
                    logger.info("PaymentManager's Kafka consumer stopped successfully.")
                    span.set_status(Status(StatusCode.OK))
                except Exception as e:
                    logger.error(f"Error stopping PaymentManager's Kafka consumer: {e}", exc_info=True)
                    span.record_exception(e)
                    span.set_status(Status(StatusCode.ERROR, "KafkaConsumerStopFailedInManager"))
        else:
            logger.info("PaymentManager's Kafka consumer was not initialized or already stopped.")