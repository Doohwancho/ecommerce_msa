import os
import logging
import atexit # For graceful shutdown
from typing import Optional

from opentelemetry import trace, propagate # propagate 모듈 임포트
from opentelemetry import _logs as otel_sdk_logs
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator
# from opentelemetry.baggage.propagation import W3CBaggagePropagator # 필요시 주석 해제

from opentelemetry.sdk._logs import LoggerProvider
from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
from opentelemetry.exporter.otlp.proto.grpc._log_exporter import OTLPLogExporter

from opentelemetry.sdk.resources import Resource, DEPLOYMENT_ENVIRONMENT
from opentelemetry.sdk.resources import SERVICE_NAME as SDK_SERVICE_NAME_KEY

from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor
from opentelemetry.instrumentation.aiokafka import AIOKafkaInstrumentor
from opentelemetry.instrumentation.logging import LoggingInstrumentor
# from opentelemetry.instrumentation.grpc import GrpcInstrumentorClient


logger = logging.getLogger(__name__)

# OpenTelemetry Environment Variables
OTEL_EXPORTER_OTLP_ENDPOINT = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://otel-collector:4317")
OTEL_SERVICE_NAME = os.getenv("OTEL_SERVICE_NAME", "payment-service")
OTEL_ENVIRONMENT = os.getenv("OTEL_ENVIRONMENT", "development")

# Global provider variables for graceful shutdown
_TRACER_PROVIDER: Optional[TracerProvider] = None
_LOGGER_PROVIDER: Optional[LoggerProvider] = None


def setup_telemetry():
    """
    Initializes OpenTelemetry tracing and logging.
    """
    global _TRACER_PROVIDER, _LOGGER_PROVIDER

    if _TRACER_PROVIDER is not None or _LOGGER_PROVIDER is not None:
        logger.warning("OpenTelemetry telemetry setup already performed. Skipping.")
        return

    try:
        # 1. Create a Resource
        resource = Resource.create({
            SDK_SERVICE_NAME_KEY: OTEL_SERVICE_NAME,
            DEPLOYMENT_ENVIRONMENT: OTEL_ENVIRONMENT,
        })

        # 2. Configure Tracing
        tracer_provider = TracerProvider(resource=resource)
        otlp_span_exporter = OTLPSpanExporter(endpoint=OTEL_EXPORTER_OTLP_ENDPOINT)
        span_processor = BatchSpanProcessor(otlp_span_exporter)
        tracer_provider.add_span_processor(span_processor)
        
        # !!!!! TracerProvider 및 Global Propagator 설정은 여기서 !!!!!
        trace.set_tracer_provider(tracer_provider)
        _TRACER_PROVIDER = tracer_provider # 전역 변수에 할당 (shutdown용)
        logger.info(f"TracerProvider configured for service: {OTEL_SERVICE_NAME}")

        # 전역 TextMap Propagator 설정
        propagator_list = [TraceContextTextMapPropagator()]
        # if W3CBaggagePropagator: # 필요시 Baggage 추가
        #     propagator_list.append(W3CBaggagePropagator())
        
        if len(propagator_list) == 1: # 지금은 TraceContextTextMapPropagator 하나만 사용
            propagate.set_global_textmap(propagator_list[0])
            logger.info(f"Global textmap propagator set to: {propagator_list[0].__class__.__name__}")
        # else: # 여러 개일 경우 (지금은 해당 없음)
            # from opentelemetry.propagate import CompositePropagator
            # propagate.set_global_textmap(CompositePropagator(propagator_list))
            # logger.info(f"Global textmap propagator set to CompositePropagator with: {[p.__class__.__name__ for p in propagator_list]}")


        # 3. Configure Logging
        logger_provider = LoggerProvider(resource=resource)
        otlp_log_exporter = OTLPLogExporter(endpoint=OTEL_EXPORTER_OTLP_ENDPOINT)
        log_record_processor = BatchLogRecordProcessor(otlp_log_exporter)
        logger_provider.add_log_record_processor(log_record_processor)
        otel_sdk_logs.set_logger_provider(logger_provider)
        _LOGGER_PROVIDER = logger_provider # 전역 변수에 할당 (shutdown용)
        logger.info(f"LoggerProvider configured for service: {OTEL_SERVICE_NAME}")

        # 4. Instrument standard Python logging
        LoggingInstrumentor().instrument(set_logging_format=True)
        logger.info("LoggingInstrumentor applied.")

        # 5. Instrument Libraries
        SQLAlchemyInstrumentor().instrument()
        logger.info("SQLAlchemyInstrumentor applied.")

        AIOKafkaInstrumentor().instrument()
        logger.info("AIOKafkaInstrumentor applied.")

        logger.info(
            f"OpenTelemetry tracing and logging for '{OTEL_SERVICE_NAME}' in '{OTEL_ENVIRONMENT}' "
            f"setup complete. Exporting to: {OTEL_EXPORTER_OTLP_ENDPOINT}"
        )

    except Exception as e:
        logger.error(f"Failed to setup OpenTelemetry for {OTEL_SERVICE_NAME}: {str(e)}", exc_info=True)
        raise

# ... (shutdown_telemetry, instrument_fastapi_app 함수는 그대로) ...
def shutdown_telemetry():
    """Gracefully shuts down OpenTelemetry tracer and logger providers."""
    global _TRACER_PROVIDER, _LOGGER_PROVIDER

    if _TRACER_PROVIDER and hasattr(_TRACER_PROVIDER, "shutdown"):
        logger.info(f"Shutting down OpenTelemetry TracerProvider for {OTEL_SERVICE_NAME}...")
        _TRACER_PROVIDER.shutdown()
        logger.info("TracerProvider shutdown complete.")
    
    if _LOGGER_PROVIDER and hasattr(_LOGGER_PROVIDER, "shutdown"):
        logger.info(f"Shutting down OpenTelemetry LoggerProvider for {OTEL_SERVICE_NAME}...")
        _LOGGER_PROVIDER.shutdown()
        logger.info("LoggerProvider shutdown complete.")

atexit.register(shutdown_telemetry)

def instrument_fastapi_app(app):
    """Instruments the FastAPI application instance."""
    if app is None:
        logger.error("Cannot instrument FastAPI app: app instance is None.")
        return
    try:
        FastAPIInstrumentor.instrument_app(app)
        logger.info(f"FastAPI app successfully instrumented for service: {OTEL_SERVICE_NAME}")
    except Exception as e:
        logger.error(f"Failed to instrument FastAPI app: {e}", exc_info=True)