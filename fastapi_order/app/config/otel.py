# telemetry_setup.py (기존 setup_telemetry.py 내용을 수정)
import os
import logging
import atexit

from opentelemetry import trace, _logs as otel_logs # _logs 임포트 경로 수정 가능성 있음 (버전 따라)
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter # 사용하시는 익스포터

# from opentelemetry._logs import set_logger_provider # SDK 버전 1.20.0 이상
# from opentelemetry.sdk._logs import LoggerProvider, LoggingLevel # SDK 버전 1.20.0 이상
# from opentelemetry.sdk._logs.export import BatchLogRecordProcessor # SDK 버전 1.20.0 이상
# from opentelemetry.exporter.otlp.proto.grpc._log_exporter import OTLPLogExporter # SDK 버전 1.20.0 이상
# 참고: opentelemetry-sdk 1.15.0 이전 버전에서는 _logs API가 실험적이었고,
# 1.20.0 이후 안정화되면서 API 경로/이름에 변경이 있을 수 있습니다.
# 사용하시는 1.33.0 버전에 맞는 정확한 임포트 경로를 확인해야 합니다.
# 여기서는 제공된 코드의 임포트 경로를 최대한 따르겠습니다.
from opentelemetry.sdk._logs import LoggerProvider
from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
from opentelemetry.exporter.otlp.proto.grpc._log_exporter import OTLPLogExporter
# otel_logs.set_logger_provider 사용을 위해 set_logger_provider 직접 임포트
try:
    from opentelemetry._logs import set_logger_provider
except ImportError: # 이전 버전 호환성 (예시)
    from opentelemetry.sdk._logs import LoggingHandler
    # 오래된 방식에서는 LoggingHandler를 표준 로깅에 추가하고, set_logger_provider가 없을 수 있음
    # 1.33.0 버전이면 set_logger_provider가 있을 것으로 예상

from opentelemetry.sdk.resources import Resource, DEPLOYMENT_ENVIRONMENT, SERVICE_NAME as SDK_SERVICE_NAME
from opentelemetry.semconv.resource import ResourceAttributes # Semantic Conventions 사용 권장

from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.grpc import GrpcInstrumentorClient
from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor
from opentelemetry.instrumentation.aiokafka import AIOKafkaInstrumentor # aiokafka 용 계측기
from opentelemetry.instrumentation.logging import LoggingInstrumentor

logger = logging.getLogger(__name__)

# OpenTelemetry settings
OTEL_EXPORTER_OTLP_ENDPOINT = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://otel-collector:4317")
OTEL_SERVICE_NAME = os.getenv("OTEL_SERVICE_NAME", "order-service")
OTEL_TRACES_SAMPLER = os.getenv("OTEL_TRACES_SAMPLER", "parentbased_always_on") # 프로덕션 권장 샘플러
OTEL_ENVIRONMENT = os.getenv("OTEL_ENVIRONMENT", "development")

_TRACER_PROVIDER = None
_LOGGER_PROVIDER = None

def setup_telemetry():
    global _TRACER_PROVIDER, _LOGGER_PROVIDER

    try:
        resource = Resource.create({
            SDK_SERVICE_NAME: OTEL_SERVICE_NAME,
            DEPLOYMENT_ENVIRONMENT: OTEL_ENVIRONMENT,
        })

        # --- Tracing 설정 ---
        tracer_provider = TracerProvider(resource=resource)
        trace.set_tracer_provider(tracer_provider)
        _TRACER_PROVIDER = tracer_provider

        otlp_span_exporter = OTLPSpanExporter(endpoint=OTEL_EXPORTER_OTLP_ENDPOINT)
        span_processor = BatchSpanProcessor(otlp_span_exporter)
        tracer_provider.add_span_processor(span_processor)

        # --- Logging 설정 ---
        logger_provider = LoggerProvider(resource=resource)
        set_logger_provider(logger_provider)
        _LOGGER_PROVIDER = logger_provider

        otlp_log_exporter = OTLPLogExporter(endpoint=OTEL_EXPORTER_OTLP_ENDPOINT)
        log_record_processor = BatchLogRecordProcessor(otlp_log_exporter)
        logger_provider.add_log_record_processor(log_record_processor)
        
        LoggingInstrumentor().instrument(set_logging_format=True)

        # --- 라이브러리 인스트루멘테이션 ---
        # FastAPI는 별도로 instrument_fastapi_app 함수를 통해 처리
        GrpcInstrumentorClient().instrument()
        SQLAlchemyInstrumentor().instrument()
        AIOKafkaInstrumentor().instrument()

        logger.info(f"OpenTelemetry tracing and logging for '{OTEL_SERVICE_NAME}' in '{OTEL_ENVIRONMENT}' setup complete. Endpoint: {OTEL_EXPORTER_OTLP_ENDPOINT}")

    except Exception as e:
        logger.error(f"Failed to setup OpenTelemetry instrumentation: {str(e)}", exc_info=True)
        raise

def shutdown_telemetry():
    global _TRACER_PROVIDER, _LOGGER_PROVIDER
    if _TRACER_PROVIDER and hasattr(_TRACER_PROVIDER, 'shutdown'):
        logger.info("Shutting down OpenTelemetry TracerProvider...")
        _TRACER_PROVIDER.shutdown()
        logger.info("TracerProvider shutdown complete.")
    
    if _LOGGER_PROVIDER and hasattr(_LOGGER_PROVIDER, 'shutdown'):
        logger.info("Shutting down OpenTelemetry LoggerProvider...")
        _LOGGER_PROVIDER.shutdown()
        logger.info("LoggerProvider shutdown complete.")

# 애플리케이션 종료 시 자동 호출되도록 등록
atexit.register(shutdown_telemetry)

def instrument_fastapi_app(app):
    """FastAPI 앱을 OpenTelemetry로 계측합니다."""
    if app is None:
        raise ValueError("FastAPI app instance cannot be None")
    FastAPIInstrumentor.instrument_app(app)
    logger.info("FastAPI application instrumented by OpenTelemetry")

# SQLAlchemy 엔진 계측 (필요시)
# def instrument_sqlalchemy_engine(engine):
#     SQLAlchemyInstrumentor().instrument(engine=engine)