# app/config/otel.py
import os
import atexit

from opentelemetry import trace, propagate
from opentelemetry.sdk.trace import TracerProvider # TracerProvider는 logging_config에서 관리
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter # Exporter도 logging_config에서 관리

from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator

from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.grpc import GrpcInstrumentorClient
from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor
from opentelemetry.instrumentation.aiokafka import AIOKafkaInstrumentor
# LoggingInstrumentor는 logging_config.py에서 호출

# logging_config.py의 로거를 사용하도록 get_configured_logger 함수 임포트
import logging # 표준 로깅 사용
from app.core.logging_config import get_global_tracer_provider, get_configured_logger, shutdown_otel_providers # Getter 임포트


# 이 파일 내에서 사용할 로거 (logging_config.py를 통해 설정된 로거를 가져옴)
# setup_telemetry가 호출되기 전에 로거를 사용해야 할 수 있으므로, get_configured_logger 사용
logger = get_configured_logger(__name__) # app.config.otel 이름으로 로거 가져오기


OTEL_SERVICE_NAME = os.getenv("OTEL_SERVICE_NAME", "order-service")

# _TRACER_PROVIDER 와 _LOGGER_PROVIDER 는 logging_config.py에서 관리되므로 여기서는 제거
# _TRACER_PROVIDER = None
# _LOGGER_PROVIDER = None


def setup_non_logging_telemetry(): # 함수 이름 변경: 로깅 관련 설정은 logging_config.py로 이동
    """OpenTelemetry 트레이싱 및 주요 라이브러리 계측을 설정합니다. (로깅 계측 제외)"""

    current_tracer_provider = get_global_tracer_provider() # Getter 사용
    if current_tracer_provider is None:
        logger.error(
            "TracerProvider not available via getter. "
            "Ensure initialize_logging_and_telemetry() was called first and set it."
        )
        return

    logger.info(f"Setting up non-logging telemetry for {OTEL_SERVICE_NAME} using existing TracerProvider.")

    # 전역 TextMap Propagator 설정
    propagator_to_set = [TraceContextTextMapPropagator()]
    propagate.set_global_textmap(propagator_to_set[0])
    logger.info(f"Global textmap propagator set to: {propagator_to_set[0].__class__.__name__}")

    # --- 라이브러리 인스트루멘테이션 (FastAPI 제외, Logging 제외) ---
    if os.getenv("INSTRUMENT_GRPC_CLIENT", "true").lower() == "true":
        # 'global_tracer_provider' -> 'current_tracer_provider'로 수정
        GrpcInstrumentorClient().instrument(tracer_provider=current_tracer_provider) 
        logger.info("GrpcInstrumentorClient applied.")
    
    if os.getenv("INSTRUMENT_SQLALCHEMY", "true").lower() == "true":
        # 'global_tracer_provider' -> 'current_tracer_provider'로 수정
        SQLAlchemyInstrumentor().instrument(tracer_provider=current_tracer_provider) 
        logger.info("SQLAlchemyInstrumentor applied.")

    if os.getenv("INSTRUMENT_AIOKAFKA", "true").lower() == "true":
        # 'global_tracer_provider' -> 'current_tracer_provider'로 수정
        AIOKafkaInstrumentor().instrument(tracer_provider=current_tracer_provider) 
        logger.info("AIOKafkaInstrumentor applied.")

    logger.info(f"Non-logging OpenTelemetry setup for '{OTEL_SERVICE_NAME}' complete.")


# atexit 핸들러는 logging_config.py 로 이동 또는 여기서 호출 (중복 등록 방지)
# 만약 logging_config.py에 이미 atexit.register(shutdown_otel_providers)가 있다면 여기서는 제거
# 없다면, logging_config.py의 shutdown_otel_providers를 호출하도록 설정
if not any(func == shutdown_otel_providers for func, _, _ in getattr(atexit, '_registrars', []) if hasattr(atexit, '_registrars')): # 좀 더 안전한 중복 체크
    atexit.register(shutdown_otel_providers)
    logger.info("Registered shutdown_otel_providers from otel.py")


def instrument_fastapi_app(app):
    """FastAPI 앱을 OpenTelemetry로 계측합니다."""
    current_tracer_provider = get_global_tracer_provider() # Getter 사용
    if current_tracer_provider is None:
        logger.error(
            "TracerProvider not available for FastAPI instrumentation via getter. "
            "Ensure initialize_logging_and_telemetry() set it."
        )
        return 

    if app is None:
        logger.error("FastAPI app instance is None for instrumentation.")
        raise ValueError("FastAPI app instance cannot be None")
    try:
        FastAPIInstrumentor.instrument_app(app, tracer_provider=current_tracer_provider)
        logger.info(f"FastAPI application instrumented by OpenTelemetry for {OTEL_SERVICE_NAME}")
    except Exception as e:
        logger.error(f"Failed to instrument FastAPI app for {OTEL_SERVICE_NAME}: {e}", exc_info=True)
        # 정책에 따라 오류를 다시 발생시킬 수 있음