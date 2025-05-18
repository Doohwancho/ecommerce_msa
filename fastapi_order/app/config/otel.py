import os
import logging
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.grpc import GrpcInstrumentorClient
# PyMongo instrumentation removed for this module
# from opentelemetry.instrumentation.pymongo import PymongoInstrumentor

# Add Kafka instrumentation import
from opentelemetry.instrumentation.kafka import KafkaInstrumentor

# Add SQLAlchemy instrumentation import
from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor # <-- SQLAlchemy 계측 임포트 추가!


logger = logging.getLogger(__name__)

# OpenTelemetry settings
# OTEL_SERVICE_NAME은 Deployment YAML 환경 변수에서 제대로 설정되어야 함 (Order Service면 "order-service")
OTEL_EXPORTER_OTLP_ENDPOINT = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://otel-collector:4317")
OTEL_SERVICE_NAME = os.getenv("OTEL_SERVICE_NAME", "order-service") # 이 기본값은 중요하지 않음, YAML에서 덮어쓸 거라
OTEL_TRACES_SAMPLER = os.getenv("OTEL_TRACES_SAMPLER", "always_on")
# METRICS 관련 변수는 필요에 따라 남겨두거나 삭제
OTEL_METRICS_EXPORTER = os.getenv("OTEL_METRICS_EXPORTER", "otlp")
OTEL_TRACES_EXPORTER = os.getenv("OTEL_TRACES_EXPORTER", "otlp")


def setup_telemetry():
    """
    OpenTelemetry 설정을 초기화하고 필요한 인스트루멘테이션을 설정합니다.
    """
    try:
        # Set up the tracer provider
        tracer_provider = TracerProvider()
        trace.set_tracer_provider(tracer_provider)

        # Configure the OTLP Exporter (sends traces to the collector)
        otlp_exporter = OTLPSpanExporter(endpoint=OTEL_EXPORTER_OTLP_ENDPOINT)
        span_processor = BatchSpanProcessor(otlp_exporter)
        tracer_provider.add_span_processor(span_processor)

        # Instrument specific libraries used by this service

        # Instrument FastAPI (incoming web requests)
        FastAPIInstrumentor().instrument()

        # Instrument gRPC client calls (for calling other services)
        GrpcInstrumentorClient().instrument()

        # Instrument Kafka clients (kafka-python, aiokafka)
        KafkaInstrumentor().instrument()

        # Instrument SQLAlchemy (database ORM)
        SQLAlchemyInstrumentor().instrument() 


        logger.info("OpenTelemetry instrumentation setup completed successfully")
    except Exception as e:
        logger.error(f"Failed to setup OpenTelemetry instrumentation: {str(e)}")
        # 중요한 설정이니 실패 시 예외 다시 발생시키는 게 좋음
        raise