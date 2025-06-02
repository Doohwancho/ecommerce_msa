# fastapi-order/app/config/otel.py
import os
import logging
import atexit

from opentelemetry import trace, propagate # Added 'propagate'
from opentelemetry import _logs as otel_sdk_logs # Using _logs as per your existing style
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter

from opentelemetry.sdk._logs import LoggerProvider # Using sdk._logs as per your existing style
from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
from opentelemetry.exporter.otlp.proto.grpc._log_exporter import OTLPLogExporter
from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator # Added
# from opentelemetry.baggage.propagation import W3CBaggagePropagator # Optional: if using baggage

try:
    from opentelemetry._logs import set_logger_provider
except ImportError:
    # Fallback for older versions or different SDK structure if needed
    # For opentelemetry-sdk 1.33.0, set_logger_provider should be available from opentelemetry.sdk._logs
    # but your original code had it in opentelemetry._logs
    # If opentelemetry.sdk._logs.set_logger_provider is the correct path for your version, adjust accordingly.
    # from opentelemetry.sdk._logs import set_logger_provider as set_sdk_logger_provider
    # set_logger_provider = set_sdk_logger_provider # Alias if necessary
    logger.warning("Could not import set_logger_provider from opentelemetry._logs, check SDK version/paths.")
    # As a minimal fallback, ensure logger_provider is still created and used,
    # but linking to Python's stdlib logging might need specific LoggingHandler if set_logger_provider fails.


from opentelemetry.sdk.resources import Resource, DEPLOYMENT_ENVIRONMENT
from opentelemetry.sdk.resources import SERVICE_NAME as SDK_SERVICE_NAME_KEY # Corrected alias
# from opentelemetry.semconv.resource import ResourceAttributes # Not directly used in resource creation in your snippet

from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.grpc import GrpcInstrumentorClient
from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor
from opentelemetry.instrumentation.aiokafka import AIOKafkaInstrumentor
from opentelemetry.instrumentation.logging import LoggingInstrumentor

logger = logging.getLogger(__name__)

# OpenTelemetry settings
OTEL_EXPORTER_OTLP_ENDPOINT = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://otel-collector:4317")
OTEL_SERVICE_NAME = os.getenv("OTEL_SERVICE_NAME", "order-service") # Specific to order-service
# OTEL_TRACES_SAMPLER is usually read directly by the SDK if set as an environment variable.
# Examples: "always_on", "parentbased_always_on" (default if not set), "traceidratio;arg=0.1"
OTEL_ENVIRONMENT = os.getenv("OTEL_ENVIRONMENT", "development")

_TRACER_PROVIDER = None
_LOGGER_PROVIDER = None

def setup_telemetry():
    global _TRACER_PROVIDER, _LOGGER_PROVIDER

    if _TRACER_PROVIDER is not None or _LOGGER_PROVIDER is not None:
        logger.warning(f"OpenTelemetry telemetry setup already performed for {OTEL_SERVICE_NAME}. Skipping.")
        return

    try:
        resource = Resource.create({
            SDK_SERVICE_NAME_KEY: OTEL_SERVICE_NAME, # Use the imported alias
            DEPLOYMENT_ENVIRONMENT: OTEL_ENVIRONMENT,
            # Add other common resource attributes if desired
            # "service.version": "your_order_service_version",
        })

        # --- Tracing 설정 ---
        tracer_provider = TracerProvider(resource=resource)
        # Sampler can be configured here or via OTEL_TRACES_SAMPLER env var
        # e.g., from opentelemetry.sdk.trace.sampling import ParentBased, AlwaysOnSampler
        # tracer_provider = TracerProvider(resource=resource, sampler=ParentBased(AlwaysOnSampler()))

        otlp_span_exporter = OTLPSpanExporter(endpoint=OTEL_EXPORTER_OTLP_ENDPOINT)
        span_processor = BatchSpanProcessor(otlp_span_exporter)
        tracer_provider.add_span_processor(span_processor)
        trace.set_tracer_provider(tracer_provider)
        _TRACER_PROVIDER = tracer_provider
        logger.info(f"TracerProvider configured for service: {OTEL_SERVICE_NAME}")

        # !!!!! 👇 전역 TextMap Propagator 설정 추가/확인 !!!!!
        # W3C Trace Context를 기본으로 사용. AIOKafkaInstrumentor 등이 이 설정을 참조.
        propagator_to_set = [TraceContextTextMapPropagator()]
        # if W3CBaggagePropagator: # 만약 Baggage도 사용한다면
        #     propagator_to_set.append(W3CBaggagePropagator())

        if len(propagator_to_set) == 1:
            propagate.set_global_textmap(propagator_to_set[0])
            logger.info(f"Global textmap propagator set to: {propagator_to_set[0].__class__.__name__} for {OTEL_SERVICE_NAME}")
        # else: # 여러 프로파게이터를 사용한다면 (지금은 해당 없음)
            # from opentelemetry.propagate import CompositePropagator
            # propagate.set_global_textmap(CompositePropagator(propagator_to_set))

        # --- Logging 설정 ---
        logger_provider = LoggerProvider(resource=resource)
        # Link to Python's standard logging
        # Ensure set_logger_provider is available and correctly imported for your SDK version
        if 'set_logger_provider' in globals() and callable(set_logger_provider):
            set_logger_provider(logger_provider)
        else:
            logger.error("set_logger_provider function not available. OTel SDK Logs may not be fully configured with Python's logging.")

        _LOGGER_PROVIDER = logger_provider

        otlp_log_exporter = OTLPLogExporter(endpoint=OTEL_EXPORTER_OTLP_ENDPOINT)
        log_record_processor = BatchLogRecordProcessor(otlp_log_exporter)
        logger_provider.add_log_record_processor(log_record_processor)
        logger.info(f"LoggerProvider configured for service: {OTEL_SERVICE_NAME}")
        
        # Python 표준 로깅 라이브러리에 Trace ID/Span ID 자동 주입
        LoggingInstrumentor().instrument(set_logging_format=True)
        logger.info("LoggingInstrumentor applied for order-service.")


        # --- 라이브러리 인스트루멘테이션 ---
        # FastAPI는 main.py에서 instrument_fastapi_app(app)으로 호출
        
        if os.getenv("INSTRUMENT_GRPC_CLIENT", "true").lower() == "true":
            GrpcInstrumentorClient().instrument()
            logger.info("GrpcInstrumentorClient applied for order-service.")
        
        if os.getenv("INSTRUMENT_SQLALCHEMY", "true").lower() == "true":
            SQLAlchemyInstrumentor().instrument()
            logger.info("SQLAlchemyInstrumentor applied for order-service.")

        if os.getenv("INSTRUMENT_AIOKAFKA", "true").lower() == "true":
            AIOKafkaInstrumentor().instrument() # Order service도 Kafka consumer 역할 수행
            logger.info("AIOKafkaInstrumentor applied for order-service.")

        logger.info(f"OpenTelemetry for '{OTEL_SERVICE_NAME}' (env: '{OTEL_ENVIRONMENT}') setup complete. Exporting to: {OTEL_EXPORTER_OTLP_ENDPOINT}")

    except Exception as e:
        logger.error(f"Failed to setup OpenTelemetry for {OTEL_SERVICE_NAME}: {str(e)}", exc_info=True)
        raise

def shutdown_telemetry():
    global _TRACER_PROVIDER, _LOGGER_PROVIDER
    if _TRACER_PROVIDER and hasattr(_TRACER_PROVIDER, 'shutdown'):
        logger.info(f"Shutting down OpenTelemetry TracerProvider for {OTEL_SERVICE_NAME}...")
        _TRACER_PROVIDER.shutdown()
        logger.info("TracerProvider shutdown complete.")
    
    if _LOGGER_PROVIDER and hasattr(_LOGGER_PROVIDER, 'shutdown'):
        logger.info(f"Shutting down OpenTelemetry LoggerProvider for {OTEL_SERVICE_NAME}...")
        _LOGGER_PROVIDER.shutdown()
        logger.info("LoggerProvider shutdown complete.")

atexit.register(shutdown_telemetry)

def instrument_fastapi_app(app):
    """FastAPI 앱을 OpenTelemetry로 계측합니다."""
    if app is None:
        logger.error("FastAPI app instance is None for instrumentation.")
        raise ValueError("FastAPI app instance cannot be None")
    try:
        FastAPIInstrumentor.instrument_app(app)
        logger.info(f"FastAPI application instrumented by OpenTelemetry for {OTEL_SERVICE_NAME}")
    except Exception as e:
        logger.error(f"Failed to instrument FastAPI app for {OTEL_SERVICE_NAME}: {e}", exc_info=True)
        # Depending on policy, you might want to raise this