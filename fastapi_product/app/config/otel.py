import os
import logging
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.grpc import GrpcInstrumentorClient
from opentelemetry.instrumentation.pymongo import PymongoInstrumentor
from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor 
from opentelemetry.instrumentation.kafka import KafkaInstrumentor 
from opentelemetry.instrumentation.elasticsearch import ElasticsearchInstrumentor 


logger = logging.getLogger(__name__)

# OpenTelemetry settings
OTEL_EXPORTER_OTLP_ENDPOINT = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://otel-collector:4317")
OTEL_SERVICE_NAME = os.getenv("OTEL_SERVICE_NAME", "product-service")
OTEL_TRACES_SAMPLER = os.getenv("OTEL_TRACES_SAMPLER", "always_on")
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

        # Instrument PyMongo (MongoDB)
        PymongoInstrumentor().instrument() 

        # Instrument SQLAlchemy (MySQL DB)
        SQLAlchemyInstrumentor().instrument()

        # Instrument Kafka clients
        KafkaInstrumentor().instrument()

        # Instrument Elasticsearch
        ElasticsearchInstrumentor().instrument()


        logger.info("OpenTelemetry instrumentation setup completed successfully")
    except Exception as e:
        logger.error(f"Failed to setup OpenTelemetry instrumentation: {str(e)}")
        raise