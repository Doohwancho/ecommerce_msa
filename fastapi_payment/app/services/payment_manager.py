from app.config.payment_kafka import KafkaConsumer # OTel 자동 계측을 활용하고 로깅이 강화된 KafkaConsumer
from app.services.payment_service import PaymentService
from app.config.payment_database import WriteSessionLocal
from app.schemas.payment_schemas import PaymentCreate, PaymentMethod
from app.models.outbox import Outbox
from app.models.failed_event import FailedEvent # _store_failed_event에서 사용
import uuid
import json
import logging # Changed
import asyncio
import datetime
import os # bootstrap_servers 환경 변수 읽기 위해

# OpenTelemetry API 임포트
from opentelemetry import trace, propagate 
from opentelemetry.trace import Status, StatusCode, SpanKind
from opentelemetry.semconv.trace import SpanAttributes

logger = logging.getLogger(__name__) # Added

# 모듈 수준 트레이서
tracer = trace.get_tracer("app.managers.payment_manager", "0.1.0")

class PaymentManager:
    def __init__(self):
        self.kafka_consumer: KafkaConsumer | None = None
        self.max_retries = 3
        logger.info("PaymentManager instance created.")

    async def initialize_kafka(self, bootstrap_servers: str, group_id: str, topic: str = 'dbserver.order'):
        """Kafka Consumer를 초기화하고 시작합니다."""
        with tracer.start_as_current_span("PaymentManager.initialize_kafka") as span:
            span.set_attribute(SpanAttributes.MESSAGING_SYSTEM, "kafka")
            span.set_attribute("app.kafka.bootstrap_servers", bootstrap_servers)
            span.set_attribute(SpanAttributes.MESSAGING_KAFKA_CONSUMER_GROUP, group_id)
            span.set_attribute("app.kafka.subscribed_topic", topic)
            
            logger.info("Attempting to initialize Kafka consumer.", 
                        extra={"group_id": group_id, "topic": topic, "bootstrap_servers": bootstrap_servers})
            try:
                if not bootstrap_servers:
                    logger.error("KAFKA_BOOTSTRAP_SERVERS is not set. Cannot initialize Kafka consumer.")
                    span.set_status(Status(StatusCode.ERROR, "BootstrapServersNotConfigured"))
                    # 이 경우, 애플리케이션 시작을 중단시키거나, Kafka 없이 동작하는 모드로 전환해야 할 수 있음
                    # 여기서는 일단 로깅만 하고 넘어가지 않도록 수정 (예외 발생 또는 플래그 설정)
                    raise ValueError("KAFKA_BOOTSTRAP_SERVERS must be configured.")

                self.kafka_consumer = KafkaConsumer(
                    bootstrap_servers=bootstrap_servers,
                    group_id=group_id,
                    topic=topic 
                )
                span.add_event("KafkaConsumerInstanceCreatedInManager", {"group_id": group_id, "topic": topic})
                logger.info("KafkaConsumer instance created.", 
                            extra={"group_id": group_id, "topic": topic})

                # 이벤트 핸들러 등록
                # 'order_created'는 Kafka 메시지 헤더의 'eventType' 또는 페이로드의 'type'과 일치해야 함
                # KafkaConsumer 내부에서 이 event_type으로 핸들러를 찾음
                event_type_to_handle = 'order_created' # 명시적으로 정의
                self.kafka_consumer.register_handler(event_type_to_handle, self.handle_order_created)
                span.add_event("EventHandlerRegisteredInManager", {"event_type_registered": event_type_to_handle, "handler": "handle_order_created"})
                logger.info("Handler registered for event type.", 
                            extra={"handler_name": self.handle_order_created.__name__, "event_type": event_type_to_handle})
                
                await self.kafka_consumer.start() # KafkaConsumer.start 내부에도 자체 스팬 및 로깅 있음
                span.add_event("KafkaConsumerStartRequestedViaManager")
                
                logger.info("Kafka consumer initialization and start process completed.", extra={"group_id": group_id})
                span.set_status(Status(StatusCode.OK))
            except Exception as e:
                logger.error("Failed to initialize or start Kafka.", 
                             extra={"error": str(e), "group_id": group_id, "topic": topic}, 
                             exc_info=True)
                if span.is_recording():
                    span.record_exception(e)
                    span.set_status(Status(StatusCode.ERROR, f"KafkaInitializationFailedInManager: {str(e)}"))
                raise # 초기화 실패는 심각하므로 예외 전파

    async def handle_order_created(self, event_data: dict):
        """
        'order_created' Kafka 이벤트를 처리하여 결제를 생성합니다.
        event_data는 KafkaConsumer로부터 전달받은 최종 비즈니스 페이로드(dict)입니다.
        """

        # jaeger에서 payment 백트레이스 안보여서 로그 찍어보기 
        current_handler_entry_span = trace.get_current_span()
        if current_handler_entry_span and current_handler_entry_span.is_recording():
            ctx = current_handler_entry_span.get_span_context()
            logger.info(
                "PaymentManager.handle_order_created: ENTRY",
                extra={
                    "trace_id": f"{ctx.trace_id:x}",
                    "span_id": f"{ctx.span_id:x}",
                    "is_remote": ctx.is_remote
                }
            )
            # 여기서 ctx.span_id가 네가 Jaeger에서 본 "dbserver.order receive" 스팬의 Span ID (6fdf35b41154c46c)와 같아야 이상적이야!
            # 또는, AIOKafkaInstrumentor가 만든 CONSUMER 스팬 바로 다음의 첫 자식 스팬 ID일 수도 있어.
        else:
            logger.warning("PaymentManager.handle_order_created: No active/recording span at handler entry.")


        # 이 함수는 payment_kafka.KafkaConsumer에 의해 호출됩니다.
        # AIOKafkaInstrumentor가 생성한 부모 CONSUMER 스팬의 컨텍스트 내에서 이미 실행됩니다.
        # 여기서 만드는 스팬은 해당 CONSUMER 스팬의 자식 스팬이 됩니다.
        with tracer.start_as_current_span("PaymentManager.handle_order_created_logic", kind=SpanKind.INTERNAL) as span:
            span.set_attribute("app.event.handler", "PaymentManager.handle_order_created")
            span.set_attribute("app.event.assumed_type", "order_created") # 이 핸들러가 처리하기로 한 타입

            # KafkaConsumer에서 이미 상세 로깅을 하므로, 여기서는 간략하게 또는 필요한 정보만 추가 로깅
            logger.info("Processing 'order_created' event.", 
                        extra={"data_keys": list(event_data.keys()) if isinstance(event_data, dict) else 'Not a dict'})
            if span.is_recording():
                try:
                    span.set_attribute("app.event.received_data_preview", json.dumps(event_data, ensure_ascii=False)[:512]) # 미리보기 길이 증가
                except Exception:
                    span.set_attribute("app.event.received_data_preview", str(event_data)[:512])

            retry_count = 0
            business_payload = event_data # KafkaConsumer에서 이미 최종 페이로드로 만들어 전달했다고 가정

            # 로깅 및 스팬을 위한 order_id 추출 (실패해도 로깅은 가능하도록)
            order_id_for_log = business_payload.get('order_id', 'ORDER_ID_NOT_FOUND_IN_PAYLOAD') if isinstance(business_payload, dict) else 'PAYLOAD_NOT_DICT'

            while retry_count < self.max_retries:
                current_attempt = retry_count + 1
                span.add_event(f"PaymentServiceCallAttempt", {"retry.attempt_number": current_attempt, "order_id": order_id_for_log})
                logger.info("Processing attempt for order.", 
                            extra={"attempt": current_attempt, "max_retries": self.max_retries, "order_id": order_id_for_log})

                try:
                    if not isinstance(business_payload, dict):
                        err_msg = "Critical: business_payload for handle_order_created is not a dict"
                        logger.error(err_msg, extra={"payload_type": str(type(business_payload))})
                        raise ValueError(f"{err_msg}, but {type(business_payload)}")

                    # 1. 필수 필드 추출 및 검증
                    order_id_val = business_payload.get('order_id')
                    total_amount_val = business_payload.get('total_amount')
                    
                    logger.debug("Validating payload fields.", 
                                 extra={"attempt": current_attempt, "order_id": order_id_val, "total_amount": total_amount_val})

                    if not order_id_val or total_amount_val is None:
                        err_msg = "Missing critical fields in payload."
                        logger.error(err_msg, 
                                     extra={
                                         "attempt": current_attempt, 
                                         "order_id_val": order_id_val, 
                                         "total_amount_val": total_amount_val,
                                         "payload_preview": str(business_payload)[:200]
                                     })
                        span.set_attribute("app.validation.error", err_msg)
                        raise ValueError(f"Missing critical fields: order_id='{order_id_val}', total_amount='{total_amount_val}'.") 
                    
                    if span.is_recording():
                        span.set_attribute("app.order_id", str(order_id_val))
                        span.set_attribute("app.order.total_amount", float(total_amount_val))
                    logger.info("Payload validated.", 
                                extra={"attempt": current_attempt, "order_id": order_id_val})

                    # 2. PaymentService.create_payment 호출 데이터 준비
                    payment_data_to_service = PaymentCreate(
                        order_id=str(order_id_val),
                        amount=float(total_amount_val),
                        currency="KRW",
                        payment_method=PaymentMethod.CREDIT_CARD,
                    )
                    logger.info("Prepared PaymentCreate schema.", 
                                extra={"attempt": current_attempt, "data": payment_data_to_service.dict()})
                    span.add_event("PaymentSchemaPrepared", payment_data_to_service.dict())
                    
                    # 3. PaymentService 호출
                    async with WriteSessionLocal() as db_session_for_payment:
                        payment_service = PaymentService(session=db_session_for_payment)
                        logger.info("Calling PaymentService.create_payment.", 
                                    extra={"attempt": current_attempt, "order_id": order_id_val})
                        payment_result = await payment_service.create_payment(payment_data_to_service)
                    
                    if payment_result:
                        logger.info("PaymentService.create_payment succeeded.", 
                                    extra={
                                        "attempt": current_attempt, 
                                        "payment_id": payment_result.payment_id, 
                                        "payment_status": payment_result.payment_status.value, 
                                        "order_id": order_id_val
                                    })
                        if span.is_recording():
                            span.set_attribute("app.payment_id_created", str(payment_result.payment_id))
                            span.set_attribute("app.payment.created_status", payment_result.payment_status.value)
                    else:
                        # create_payment가 None을 반환하는 경우는 PaymentService 내에서 예외없이 None을 반환하도록 수정되었을 때 발생 가능
                        # 보통은 예외를 발생시키므로 이 경우는 드묾.
                        logger.error("PaymentService.create_payment returned None, which is unexpected.", 
                                     extra={"attempt": current_attempt, "order_id": order_id_val})
                        raise Exception(f"PaymentService.create_payment returned None unexpectedly for order_id: {order_id_val}")

                    span.set_status(Status(StatusCode.OK))
                    logger.info("Successfully processed 'order_created' event.", 
                                extra={"order_id": order_id_val, "attempt": current_attempt})
                    return  # 성공, 재시도 루프 종료

                except ValueError as ve: 
                    logger.error("ValueError in handle_order_created.", 
                                 extra={"attempt": current_attempt, "order_id": order_id_for_log, "error": str(ve)},
                                 exc_info=True) 
                    if span.is_recording():
                        span.record_exception(ve)
                        span.set_status(Status(StatusCode.ERROR, f"DataValidationError: {str(ve)}"))
                    await self._store_failed_event('order_created_event_validation_error_in_pm', business_payload, str(ve))
                    return 
                except Exception as e: 
                    retry_count += 1
                    logger.error("General error in handle_order_created.", 
                                 extra={
                                     "attempt": current_attempt, 
                                     "max_retries": self.max_retries, 
                                     "order_id": order_id_for_log, 
                                     "error": str(e)
                                 },
                                 exc_info=True)
                    if span.is_recording():
                        span.record_exception(e)
                    
                    if retry_count >= self.max_retries:
                        logger.error("All retries failed for handle_order_created. Initiating compensation.", 
                                     extra={
                                         "max_retries": self.max_retries, 
                                         "order_id": order_id_for_log, 
                                         "final_error": str(e)
                                     })
                        if span.is_recording():
                            span.set_attribute("app.processing.final_outcome", "failed_max_retries")
                            span.set_status(Status(StatusCode.ERROR, "MaxRetriesExceeded_HandleOrderCreated"))
                        
                        payload_for_comp = business_payload if isinstance(business_payload, dict) else event_data # 원본 event_data 사용
                        if isinstance(payload_for_comp, dict) and payload_for_comp.get('order_id'):
                             await self.create_compensation_event(payload_for_comp, "payment_creation_failed_after_retries")
                        else:
                             await self._store_failed_event('order_created_max_retries_invalid_payload_for_comp', event_data, str(e))
                        return 
                    
                    delay = 2 ** (retry_count -1) 
                    span.add_event("RetryDelaying", {"delay_seconds": delay, "next_attempt_number": retry_count + 1})
                    logger.info("Waiting before next retry.", 
                                extra={"delay_seconds": delay, "order_id": order_id_for_log, "next_attempt": retry_count + 1})
                    await asyncio.sleep(delay)
            
            if span.get_status().status_code != StatusCode.OK :
                 logger.error("PaymentManager.handle_order_created ultimately failed.", 
                              extra={"order_id": order_id_for_log})


    async def create_compensation_event(self, original_event_payload: dict, reason_type: str):
        with tracer.start_as_current_span("PaymentManager.create_compensation_event_logic") as span:
            order_id = original_event_payload.get('order_id')
            span.set_attribute("app.order_id_for_compensation", str(order_id))
            span.set_attribute("app.compensation.reason_type", reason_type)
            logger.info("Creating compensation event.", 
                        extra={"order_id": order_id, "reason_type": reason_type})
            # ... (이하 로직은 이전과 동일: Outbox에 컨텍스트 주입 포함)
            try:
                async with WriteSessionLocal() as session:
                    async with session.begin():
                        compensation_event_data = {
                            'type': "payment_failed",
                            'order_id': str(order_id),
                            'items_to_revert_stock': original_event_payload.get('items', []),
                            'reason': reason_type,
                            'payment_attempt_details': original_event_payload.get('payment_details_if_any', {}), # 필요시 결제 시도 정보 추가
                            'original_event_preview': json.dumps(original_event_payload, ensure_ascii=False)[:128],
                            'timestamp': datetime.datetime.utcnow().isoformat()
                        }

                        # 현재 활성화된 스팬의 컨텍스트를 가져옴
                        current_otel_span = trace.get_current_span()
                        # 주입할 컨텍스트 생성
                        context_to_propagate = trace.set_span_in_context(current_otel_span)
                        
                        carrier = {}  # W3C Trace Context 헤더를 담을 딕셔너리
                        # 전역 프로파게이터를 사용하여 컨텍스트 주입
                        propagator = propagate.get_global_textmap()
                        propagator.inject(carrier, context=context_to_propagate)

                        span.add_event("TraceContextInjectedToCarrierForOutbox", 
                                   {"traceparent": carrier.get('traceparent'), "tracestate": carrier.get('tracestate')})

                        outbox_entry = Outbox(
                            id=str(uuid.uuid4()),
                            aggregatetype="payment", 
                            aggregateid=str(order_id),
                            type="payment_failed", 
                            payload=compensation_event_data,
                            traceparent_for_header=carrier.get('traceparent'),
                            tracestate_for_header=carrier.get('tracestate')
                        )
                        session.add(outbox_entry)
                span.add_event("CompensationOutboxEventPrepared", {"otel_trace_headers_injected": bool(carrier.get("traceparent"))})
                logger.info("Compensation event added to outbox.", 
                            extra={"order_id": order_id, "reason": reason_type})
                span.set_status(Status(StatusCode.OK))
            except Exception as e:
                logger.critical("CRITICAL - Failed to create compensation event.", 
                                extra={"order_id": order_id, "error": str(e)}, 
                                exc_info=True)
                if span.is_recording():
                    span.record_exception(e)
                    span.set_status(Status(StatusCode.ERROR, "CompensationEventCreationFailedInManager"))

    async def _store_failed_event(self, event_type: str, event_data: dict, error_msg: str) -> None:
        with tracer.start_as_current_span("PaymentManager._store_failed_event_logic") as span: # 스팬 이름 변경
            logger.info("Storing failed event.", 
                        extra={
                            "event_type": event_type, 
                            "error_msg": error_msg, 
                            "data_preview": str(event_data)[:200]
                        })
            # ... (이전 DB 저장 로직, FailedEvent 임포트 확인) ...
            span.set_attribute("app.failed_event.type", event_type)
            span.set_attribute("app.failed_event.error_message", error_msg[:256])
            try:
                event_data_json = json.dumps(event_data, ensure_ascii=False)
                span.set_attribute("app.failed_event.data_size_bytes", len(event_data_json))
                from app.models.failed_event import FailedEvent 

                failed_event_record = FailedEvent(
                    event_type=event_type,
                    event_data=event_data_json,
                    error_message=error_msg,
                    status='pending_review'
                )
                async with WriteSessionLocal() as session:
                    async with session.begin():
                        session.add(failed_event_record)
                
                logger.info("Stored failed event successfully.", 
                            extra={"event_type": event_type, "error_msg": error_msg})
                span.set_status(Status(StatusCode.OK))
            except Exception as e:
                # ... (예외 처리) ...
                logger.critical("CRITICAL - Failed to store failed_event in DB.", 
                                extra={"event_type": event_type, "error_msg": error_msg, "db_error": str(e)}, 
                                exc_info=True)
                if span.is_recording():
                    span.record_exception(e)
                    span.set_status(Status(StatusCode.ERROR, "StoreFailedEventToDBError"))


    async def stop(self):
        if self.kafka_consumer:
            with tracer.start_as_current_span("PaymentManager.request_kafka_consumer_stop") as span: # 스팬 이름 변경
                logger.info("Requesting to stop Kafka consumer...")
                try:
                    await self.kafka_consumer.stop() # KafkaConsumer.stop 내부에도 스팬이 있음
                    logger.info("Kafka consumer stop request successful.")
                    span.set_status(Status(StatusCode.OK))
                except Exception as e:
                    # ... (예외 처리) ...
                     logger.error("Error requesting stop for Kafka consumer.", 
                                  extra={"error": str(e)}, 
                                  exc_info=True)
                     if span.is_recording():
                        span.record_exception(e)
                        span.set_status(Status(StatusCode.ERROR, "KafkaConsumerStopRequestFailed"))
        else:
            logger.info("Kafka consumer was not initialized or already stopped.")