import os
import logging
from app.config.logging import (
    get_global_tracer_provider, 
    get_configured_logger, 
    shutdown_otel_providers
)

import atexit
from opentelemetry import trace, propagate # 트레이싱용
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter

from opentelemetry._logs import set_logger_provider # 로깅 프로바이더 설정용
from opentelemetry.sdk._logs import LoggerProvider # 로거 프로바이더
from opentelemetry.sdk._logs.export import BatchLogRecordProcessor # 로그 프로세서
from opentelemetry.exporter.otlp.proto.grpc._log_exporter import OTLPLogExporter # 로그 익스포터

from opentelemetry.sdk.resources import Resource # 트레이싱/로깅 같이 쓰는 리소스

from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.grpc import GrpcInstrumentorClient
from opentelemetry.instrumentation.pymongo import PymongoInstrumentor # PyMongo 계측 유지 (requirements.txt에 있음)

from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator
# LoggingInstrumentation 대신 LoggingInstrumentor 임포트 (0.42b0 버전 호환 추정)
# from opentelemetry.instrumentation.logging import LoggingInstrumentor

# Kafka, SQLAlchemy는 제공된 requirements.txt 및 에러 컨텍스트에 없었으므로 제거합니다.
# 필요하다면 해당 패키지 및 계측기를 requirements.txt에 추가하고 여기에 임포트/초기화하세요.
# from opentelemetry.instrumentation.kafka import KafkaInstrumentor
# from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor


logger = get_configured_logger(__name__) # app.config.otel 이름으로 로거 가져오기

# OpenTelemetry settings
OTEL_EXPORTER_OTLP_ENDPOINT = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://otel-collector:4317")
# OTEL_SERVICE_NAME은 Deployment YAML 환경 변수에서 제대로 설정되어야 함
OTEL_SERVICE_NAME = os.getenv("OTEL_SERVICE_NAME", "user-service") # 제공된 코드와 requirements.txt 기준으로 user-service로 유지

# 트레이스 샘플러 설정 (필요에 따라 수정)
OTEL_TRACES_SAMPLER = os.getenv("OTEL_TRACES_SAMPLER", "always_on") # always_on, parentbased_always_on 등

# 메트릭스/트레이스 익스포터 타입 변수는 설정 자체에 직접 사용되지 않으므로 제거하거나 필요에 따라 유지
# OTEL_METRICS_EXPORTER = os.getenv("OTEL_METRICS_EXPORTER", "otlp")
# OTEL_TRACES_EXPORTER = os.getenv("OTEL_TRACES_EXPORTER", "otlp")


def setup_non_logging_telemetry(): # 함수 이름 변경: 로깅 관련 설정은 logging_config.py로 이동
    """
    OpenTelemetry 설정 (트레이싱 + 포괄적 로깅)을 초기화합니다.
    """
    try:
        # --- 리소스 설정 ---
        # 트레이싱과 로깅이 공유할 서비스 정보 등의 리소스를 정의합니다.
        resource = Resource.create({
            "service.name": OTEL_SERVICE_NAME, # 이 서비스의 이름
            # "deployment.environment": os.getenv("ENVIRONMENT", "development"), # 환경 정보 등 추가 가능
            # 다른 리소스 속성들은 https://opentelemetry.io/docs/specs/resource/semantic_conventions/ 참조
        })

        # --- 트레이싱 설정 ---
        # 트레이서 프로바이더 설정 (리소스 연결)
        tracer_provider = TracerProvider(resource=resource)
        trace.set_tracer_provider(tracer_provider)

        # OTLP 스팬 익스포터 설정 (트레이스를 컬렉터로 보냄)
        otlp_span_exporter = OTLPSpanExporter(endpoint=OTEL_EXPORTER_OTLP_ENDPOINT)
        # 스팬 프로세서 설정 (스팬을 모아서 배치로 보냄)
        span_processor = BatchSpanProcessor(otlp_span_exporter)
        tracer_provider.add_span_processor(span_processor)


        # --- 전역 컨텍스트 ---
        propagators_to_set = [TraceContextTextMapPropagator()]
        # 만약 W3C Baggage도 사용한다면 리스트에 추가:
        # from opentelemetry.baggage.propagation import W3CBaggagePropagator
        # propagators_to_set.append(W3CBaggagePropagator())

        if len(propagators_to_set) == 1:
            propagate.set_global_textmap(propagators_to_set[0])
            logger.info(f"Global textmap propagator set to: {propagators_to_set[0].__class__.__name__}")

        # --- 라이브러리 인스트루멘테이션 설정 ---
        # 서비스에서 사용하는 라이브러리들을 계측하여 자동으로 트레이스/스팬을 생성하게 합니다.
        # FastAPI는 일반적으로 제일 먼저 계측하는 것이 좋습니다.
        FastAPIInstrumentor().instrument()

        # gRPC 클라이언트 호출 계측 (다른 서비스 호출 시)
        GrpcInstrumentorClient().instrument()

        # PyMongo 계측 유지 (requirements.txt에 있음)
        PymongoInstrumentor().instrument()

        # 사용하는 다른 라이브러리들도 필요에 따라 여기에 추가합니다.
        # 예: Kafka, Redis 등등 필요한 계측기는 여기에 추가하고 위에 임포트해야 합니다.

        logger.info("OpenTelemetry tracing and logging instrumentation setup completed successfully")

    except Exception as e:
        # OpenTelemetry 설정 중 에러가 발생하면 중요한 문제이므로 로깅하고 예외를 다시 발생시키는 것이 좋습니다.
        logger.error(f"Failed to setup OpenTelemetry instrumentation: {str(e)}", exc_info=True) # exc_info=True로 에러 정보도 로깅
        raise # 앱 시작 전에 실패하면 앱 실행을 중단

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