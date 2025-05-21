import os
from app.config.kafka_consumer import OrderKafkaConsumer # OrderKafkaConsumer는 이미 OTel 친화적으로 수정되었다고 가정
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
PAYMENT_TOPIC = 'payment'  # Payment 서비스의 토픽

# 글로벌 변수로 Kafka Consumer 인스턴스 유지
kafka_consumer = None

async def handle_payment_success_wrapper(event_data):
    """payment_success 이벤트를 처리하는 래퍼 함수. OTel 트레이싱 적용."""
    # 이 함수는 OrderKafkaConsumer에 의해 호출되며, 이미 부모 Kafka Consumer 스팬 컨텍스트 내에서 실행됩니다.
    # 여기서는 해당 비즈니스 로직 처리를 위한 자식 스팬을 생성합니다.
    with tracer.start_as_current_span("HandlePaymentSuccess", kind=SpanKind.INTERNAL) as span:
        try:
            logger.info(f"Handling payment_success event: {event_data}")
            span.set_attribute("app.event.type", "payment_success")
            if isinstance(event_data, dict):
                # 중요 정보나 식별자를 속성으로 추가 (민감 정보 주의)
                order_id = event_data.get('order_id')
                payment_id = event_data.get('payment_id')
                if order_id:
                    span.set_attribute("app.order_id", str(order_id))
                if payment_id:
                    span.set_attribute("app.payment_id", str(payment_id))
                # event_data 전체를 저장하는 것은 데이터 크기나 민감 정보 유출 위험으로 권장되지 않음
                # 필요한 경우 안전한 형태로 일부만 저장:
                # span.set_attribute("app.event.data_preview", json.dumps(event_data, ensure_ascii=False)[:256])


            async with AsyncSessionLocal() as session: # SQLAlchemyInstrumentor가 DB 작업 스팬 자동 생성
                order_manager = OrderManager(session)
                await order_manager.handle_payment_success(event_data)
            
            span.set_status(Status(StatusCode.OK))
            logger.info("Payment success event processed successfully.")

        except Exception as e:
            logger.error(f"Error handling payment_success_event: {e}", exc_info=True)
            if span.is_recording():
                span.record_exception(e)
                span.set_status(Status(StatusCode.ERROR, str(e)))
            raise # 필요한 경우 예외를 다시 발생시켜 상위에서 처리하도록 할 수 있음

async def handle_payment_failed_wrapper(event_data):
    """payment_failed 이벤트를 처리하는 래퍼 함수. OTel 트레이싱 적용."""
    with tracer.start_as_current_span("HandlePaymentFailed", kind=SpanKind.INTERNAL) as span:
        try:
            logger.info(f"Handling payment_failed event: {event_data}")
            span.set_attribute("app.event.type", "payment_failed")
            if isinstance(event_data, dict):
                order_id = event_data.get('order_id')
                error_message = event_data.get('error_message')
                if order_id:
                    span.set_attribute("app.order_id", str(order_id))
                if error_message:
                     span.set_attribute("app.payment.error_message", str(error_message))

            async with AsyncSessionLocal() as session: # SQLAlchemyInstrumentor가 DB 작업 스팬 자동 생성
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

async def init_kafka_consumer():
    """Kafka Consumer를 초기화하고 시작합니다. OTel 트레이싱 적용."""
    global kafka_consumer
    
    # 이 함수 자체의 실행을 추적하기 위한 스팬
    with tracer.start_as_current_span("InitKafkaConsumer") as span:
        span.set_attribute(SpanAttributes.MESSAGING_SYSTEM, "kafka")
        span.set_attribute(SpanAttributes.MESSAGING_KAFKA_CONSUMER_GROUP, KAFKA_CONSUMER_GROUP)
        span.set_attribute("app.kafka.bootstrap_servers", KAFKA_BOOTSTRAP_SERVERS)
        span.set_attribute("app.kafka.target_topics", PAYMENT_TOPIC)

        if kafka_consumer is not None:
            logger.info("Kafka consumer already initialized and running.")
            span.add_event("ConsumerAlreadyInitialized")
            span.set_status(Status(StatusCode.OK, "Already initialized"))
            return
        
        try:
            kafka_consumer = OrderKafkaConsumer(
                bootstrap_servers=KAFKA_BOOTSTRAP_SERVERS,
                group_id=KAFKA_CONSUMER_GROUP
            )
            
            # OrderKafkaConsumer.register_handler 내부에서도 필요하다면 스팬을 추가할 수 있지만,
            # 여기서는 init_kafka_consumer 스팬의 이벤트로 기록
            span.add_event("RegisteringHandlers", {"topic": PAYMENT_TOPIC})

            kafka_consumer.register_handler(
                PAYMENT_TOPIC, 
                handle_payment_success_wrapper, # 이 핸들러들은 자체적으로 내부 스팬을 생성
                event_type='payment_success'
            )
            span.add_event("RegisteredHandler", {"event_type": "payment_success"})
            
            kafka_consumer.register_handler(
                PAYMENT_TOPIC, 
                handle_payment_failed_wrapper, # 이 핸들러들은 자체적으로 내부 스팬을 생성
                event_type='payment_failed'
            )
            span.add_event("RegisteredHandler", {"event_type": "payment_failed"})
            
            await kafka_consumer.start() # OrderKafkaConsumer.start() 내부에도 자체 스팬이 있을 수 있음
            
            logger.info(f"Kafka consumer started, listening to topic: {PAYMENT_TOPIC} for payment events")
            span.set_status(Status(StatusCode.OK))

        except Exception as e:
            logger.error(f"Failed to initialize Kafka consumer: {e}", exc_info=True)
            if span.is_recording():
                span.record_exception(e)
                span.set_status(Status(StatusCode.ERROR, f"Kafka consumer initialization failed: {str(e)}"))
            # 초기화 실패 시 kafka_consumer를 None으로 유지하거나, 에러를 다시 발생시킬 수 있음
            kafka_consumer = None 
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
                logger.error(f"Failed to stop Kafka consumer: {e}", exc_info=True)
                if span.is_recording():
                    span.record_exception(e)
                    span.set_status(Status(StatusCode.ERROR, f"Kafka consumer stop failed: {str(e)}"))
                raise # 또는 다른 오류 처리
        else:
            logger.info("Kafka consumer was not running.")
            span.add_event("ConsumerNotRunning")
            span.set_status(Status(StatusCode.OK, "Not running"))