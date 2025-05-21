import os
import logging
import atexit # For graceful shutdown
from typing import Optional

from opentelemetry import trace
# Use _logs for OTel SDK logging components
from opentelemetry import _logs as otel_sdk_logs
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter

from opentelemetry.sdk._logs import LoggerProvider
from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
from opentelemetry.exporter.otlp.proto.grpc._log_exporter import OTLPLogExporter

from opentelemetry.sdk.resources import Resource, DEPLOYMENT_ENVIRONMENT
# SERVICE_NAME from opentelemetry.sdk.resources can be used as a key
from opentelemetry.sdk.resources import SERVICE_NAME as SDK_SERVICE_NAME_KEY

# Import instrumentors based on your requirements.txt
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor
from opentelemetry.instrumentation.aiokafka import AIOKafkaInstrumentor # Corrected for aiokafka
from opentelemetry.instrumentation.logging import LoggingInstrumentor
# Keep gRPC import available if needed, but commented out for instrumentation
from opentelemetry.instrumentation.grpc import GrpcInstrumentorClient


logger = logging.getLogger(__name__)

# OpenTelemetry Environment Variables
OTEL_EXPORTER_OTLP_ENDPOINT = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://otel-collector:4317")
OTEL_SERVICE_NAME = os.getenv("OTEL_SERVICE_NAME", "payment-service") # Specific for this service
OTEL_ENVIRONMENT = os.getenv("OTEL_ENVIRONMENT", "development")
# OTEL_TRACES_SAMPLER is read by the SDK automatically if set, e.g., "parentbased_always_on"
# Default sampler is ParentBased(AlwaysOnSampler) if OTEL_TRACES_SAMPLER is not set.

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
        # 1. Create a Resource: Describes the service being instrumented.
        resource = Resource.create({
            SDK_SERVICE_NAME_KEY: OTEL_SERVICE_NAME,
            DEPLOYMENT_ENVIRONMENT: OTEL_ENVIRONMENT,
            # You can add other resource attributes like service.version, host.name etc.
            # "service.version": "1.2.3",
            # "host.name": os.getenv("HOSTNAME", "unknown"), # Example: K8s pod name
        })

        # 2. Configure Tracing
        tracer_provider = TracerProvider(resource=resource)
        # Sampler can be configured via OTEL_TRACES_SAMPLER env var or explicitly:
        # from opentelemetry.sdk.trace.sampling import ParentBasedTraceIdRatioSampler
        # tracer_provider = TracerProvider(resource=resource, sampler=ParentBasedTraceIdRatioSampler(0.1)) # Sample 10%
        
        otlp_span_exporter = OTLPSpanExporter(endpoint=OTEL_EXPORTER_OTLP_ENDPOINT)
        span_processor = BatchSpanProcessor(otlp_span_exporter)
        tracer_provider.add_span_processor(span_processor)
        trace.set_tracer_provider(tracer_provider)
        _TRACER_PROVIDER = tracer_provider
        logger.info(f"TracerProvider configured for service: {OTEL_SERVICE_NAME}")

        # 3. Configure Logging
        logger_provider = LoggerProvider(resource=resource)
        otlp_log_exporter = OTLPLogExporter(endpoint=OTEL_EXPORTER_OTLP_ENDPOINT)
        log_record_processor = BatchLogRecordProcessor(otlp_log_exporter)
        logger_provider.add_log_record_processor(log_record_processor)
        otel_sdk_logs.set_logger_provider(logger_provider) # Link OTel logging to Python's logging
        _LOGGER_PROVIDER = logger_provider
        logger.info(f"LoggerProvider configured for service: {OTEL_SERVICE_NAME}")

        # 4. Instrument standard Python logging to add trace context
        # This should be done after setting the logger_provider
        LoggingInstrumentor().instrument(set_logging_format=True) # set_logging_format can be useful for console logs
        logger.info("LoggingInstrumentor applied.")

        # 5. Instrument Libraries
        # FastAPI will be instrumented explicitly in main.py using the helper function below.
        # If you prefer auto-instrumentation on app creation here, you would call FastAPIInstrumentor().instrument()

        SQLAlchemyInstrumentor().instrument()
        logger.info("SQLAlchemyInstrumentor applied.")

        AIOKafkaInstrumentor().instrument() # Corrected for aiokafka
        logger.info("AIOKafkaInstrumentor applied.")

        # gRPC Client Instrumentation (optional, if this service makes outgoing gRPC calls)
        # As per your comment, "Payment 서비스는 gRPC 클라이언트 안 쓰는 것 같으니 주석 그대로 둠"
        # If needed in the future, uncomment the import and this line:
        # GrpcInstrumentorClient().instrument()
        # logger.info("GrpcInstrumentorClient instrumentation ready (if uncommented).")

        logger.info(
            f"OpenTelemetry tracing and logging for '{OTEL_SERVICE_NAME}' in '{OTEL_ENVIRONMENT}' "
            f"setup complete. Exporting to: {OTEL_EXPORTER_OTLP_ENDPOINT}"
        )

    except Exception as e:
        logger.error(f"Failed to setup OpenTelemetry for {OTEL_SERVICE_NAME}: {str(e)}", exc_info=True)
        # Propagate the error to prevent the application from starting in a non-instrumented state
        raise

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

# Register the shutdown function to be called on application exit
atexit.register(shutdown_telemetry)

# Helper function for explicit FastAPI instrumentation (called from main.py)
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
        # Depending on policy, you might want to raise this error
        # raise