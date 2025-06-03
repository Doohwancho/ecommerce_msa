import os
from app.config.kafka_consumer import OrderModuleKafkaConsumer # OrderKafkaConsumer는 이미 OTel 친화적으로 수정되었다고 가정
from app.services.order_manager import OrderManager
from app.config.database import AsyncSessionLocal # SQLAlchemyInstrumentor가 DB 세션 자동 계측
import logging
# import json # 현재 코드에서 직접 사용되지 않으므로 주석 처리 또는 제거 가능
import asyncio

# OpenTelemetry API 임포트
from opentelemetry import trace
from opentelemetry.trace import SpanKind, Status, StatusCode
from opentelemetry.semconv.trace import SpanAttributes # 시맨틱 컨벤션 사용 권장

logger = logging.getLogger(__name__)
tracer = trace.get_tracer(__name__) # 모듈 레벨 트레이서 가져오기

# Kafka 설정
KAFKA_BOOTSTRAP_SERVERS = os.getenv('KAFKA_BOOTSTRAP_SERVERS', 'kafka-service:9092')
KAFKA_CONSUMER_GROUP = os.getenv('KAFKA_CONSUMER_GROUP', 'order-service-group')
PAYMENT_EVENTS_TOPIC = os.getenv('PAYMENT_EVENTS_TOPIC', 'dbserver.payment') # Topic where payment_success/failed are published

# 글로벌 변수로 Kafka Consumer 인스턴스 유지
kafka_consumer = None


async def init_kafka_consumer():
    """Kafka Consumer를 초기화하고 시작합니다. OTel 트레이싱 적용."""
    global kafka_consumer
    
    with tracer.start_as_current_span("InitOrderKafkaConsumer") as span: # 스팬 이름 명확화
        span.set_attribute(SpanAttributes.MESSAGING_SYSTEM, "kafka")
        span.set_attribute(SpanAttributes.MESSAGING_KAFKA_CONSUMER_GROUP, KAFKA_CONSUMER_GROUP)
        span.set_attribute("app.kafka.bootstrap_servers", KAFKA_BOOTSTRAP_SERVERS)
        # OrderModule은 payment 이벤트를 구독하므로, 구독 대상 토픽은 PAYMENT_EVENTS_TOPIC
        span.set_attribute("app.kafka.subscribed_topics_for_order_module", PAYMENT_EVENTS_TOPIC) 

        if kafka_consumer is not None:
            span.add_event("OrderModuleConsumerAlreadyInitialized")
            span.set_status(Status(StatusCode.OK, "Already initialized"))
            return
        
        try:
            kafka_consumer = OrderModuleKafkaConsumer( # OrderModuleKafkaConsumer 사용
                bootstrap_servers=KAFKA_BOOTSTRAP_SERVERS,
                group_id=KAFKA_CONSUMER_GROUP
                # topics 인자는 OrderModuleKafkaConsumer.__init__에서 사용하지 않고,
                # start 메소드에서 self.handlers.keys()로 구독함.
            )
            
            # OrderManager 인스턴스는 핸들러 내부에서 DB 작업을 위해 필요할 수 있으므로,
            # 래퍼 함수 내부에서 생성하거나, OrderManager 메소드를 직접 핸들러로 등록.
            # 여기서는 래퍼 함수를 사용하고 있으므로, OrderManager 인스턴스가 래퍼 내부에서 생성됨.

            span.add_event("RegisteringHandlersForOrderModule", {"consuming_topic": PAYMENT_EVENTS_TOPIC})

            kafka_consumer.register_handler(
                topic=PAYMENT_EVENTS_TOPIC,  # 첫 번째 인자: topic
                event_type='payment_success', # 두 번째 인자: event_type (문자열)
                handler=handle_payment_success_wrapper # 세 번째 인자: handler (실제 호출될 함수)
            )
            span.add_event("RegisteredHandlerForOrderModule", {"event_type": "payment_success"})
            
            kafka_consumer.register_handler(
                topic=PAYMENT_EVENTS_TOPIC, 
                event_type='payment_failed',
                handler=handle_payment_failed_wrapper
            )
            span.add_event("RegisteredHandlerForOrderModule", {"event_type": "payment_failed"})
            
            await kafka_consumer.start()
            
            logger.info("OrderModule Kafka consumer started", extra={
                "topic": PAYMENT_EVENTS_TOPIC,
                "group_id": KAFKA_CONSUMER_GROUP
            })
            span.set_status(Status(StatusCode.OK))

        except Exception as e:
            logger.error("Failed to initialize OrderModule Kafka consumer", extra={
                "error": str(e),
                "bootstrap_servers": KAFKA_BOOTSTRAP_SERVERS,
                "group_id": KAFKA_CONSUMER_GROUP
            }, exc_info=True)
            if span.is_recording():
                span.record_exception(e)
                span.set_status(Status(StatusCode.ERROR, f"Order Kafka consumer init failed: {str(e)}"))
            kafka_consumer = None 
            raise


async def handle_payment_success_wrapper(event_data, parent_context=None):
    """payment_success 이벤트를 처리하는 래퍼 함수. OTel 트레이싱 적용."""
    with tracer.start_as_current_span(
        "HandlePaymentSuccess", 
        context=parent_context,  # 명시적으로 부모 컨텍스트 설정
        kind=SpanKind.INTERNAL
    ) as span:
        try:
            logger.info(f"Handling payment_success event: {event_data}")
            span.set_attribute("app.event.type", "payment_success")
            if isinstance(event_data, dict):
                order_id = event_data.get('order_id')
                payment_id = event_data.get('payment_id')
                if order_id:
                    span.set_attribute("app.order_id", str(order_id))
                if payment_id:
                    span.set_attribute("app.payment_id", str(payment_id))

            async with AsyncSessionLocal() as session:
                order_manager = OrderManager(session)
                await order_manager.handle_payment_success(event_data)
            
            span.set_status(Status(StatusCode.OK))
            logger.info("Payment success event processed successfully.")
        except Exception as e:
            logger.error(f"Error handling payment_success_event: {e}", exc_info=True)
            if span.is_recording():
                span.record_exception(e)
                span.set_status(Status(StatusCode.ERROR, str(e)))
            raise

async def handle_payment_failed_wrapper(event_data, parent_context=None):
    """payment_failed 이벤트를 처리하는 래퍼 함수. OTel 트레이싱 적용."""
    with tracer.start_as_current_span(
        "HandlePaymentFailed",
        context=parent_context,  # 명시적으로 부모 컨텍스트 설정
        kind=SpanKind.INTERNAL
    ) as span:
        try:
            logger.info(f"Handling payment_failed event: {event_data}")
            span.set_attribute("app.event.type", "payment_failed")
            if isinstance(event_data, dict):
                order_id = event_data.get('order_id')
                error_message = event_data.get('error_message') or event_data.get('reason')
                if order_id:
                    span.set_attribute("app.order_id", str(order_id))
                if error_message:
                     span.set_attribute("app.payment.error_message", str(error_message))

            async with AsyncSessionLocal() as session:
                order_manager = OrderManager(session)
                await order_manager.handle_payment_failed(event_data)

            span.set_status(Status(StatusCode.OK))
            logger.info("Payment failed event processed successfully.")
        except Exception as e:
            logger.error(f"Error handling payment_failed_event: {e}", exc_info=True)
            if span.is_recording():
                span.record_exception(e)
                span.set_status(Status(StatusCode.ERROR, str(e)))
            raise


async def stop_kafka_consumer():
    """Kafka Consumer를 종료합니다. OTel 트레이싱 적용."""
    global kafka_consumer
    
    with tracer.start_as_current_span("StopKafkaConsumer") as span:
        if kafka_consumer:
            try:
                await kafka_consumer.stop() # OrderKafkaConsumer.stop() 내부에도 자체 스팬이 있을 수 있음
                kafka_consumer = None
                logger.info("Kafka consumer stopped successfully")
                span.set_status(Status(StatusCode.OK))
            except Exception as e:
                logger.error("Failed to stop Kafka consumer", extra={
                    "error": str(e)
                }, exc_info=True)
                if span.is_recording():
                    span.record_exception(e)
                    span.set_status(Status(StatusCode.ERROR, f"Kafka consumer stop failed: {str(e)}"))
                raise # 또는 다른 오류 처리
        else:
            span.add_event("ConsumerNotRunning")
            span.set_status(Status(StatusCode.OK, "Not running"))