import os
import logging
from app.config.logging import (
    get_global_tracer_provider, 
    get_configured_logger, 
    shutdown_otel_providers
)

import atexit
from opentelemetry import trace, propagate # 'propagate' 임포트 추가!
# 트레이싱 관련 임포트
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
# W3C Trace Context 전파기 임포트 추가!
from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator
# (선택 사항) Baggage 전파기도 사용하려면 임포트
# from opentelemetry.baggage.propagation import W3CBaggagePropagator

# 라이브러리 자동 계측기 임포트 (Product 서비스에서 쓰는 것들)
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.grpc import GrpcInstrumentorClient # 서버/클라이언트 모두 계측 필요
from opentelemetry.instrumentation.pymongo import PymongoInstrumentor
from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor
from opentelemetry.instrumentation.aiokafka import AIOKafkaInstrumentor
from opentelemetry.instrumentation.elasticsearch import ElasticsearchInstrumentor # Elasticsearch 계측기

# 로깅 관련 임포트 (기존과 동일)
# from opentelemetry._logs import set_logger_provider # _logs 대신 sdk._logs 사용할 수도 있음 (버전 따라)
# from opentelemetry.sdk._logs import LoggerProvider
# from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
# from opentelemetry.exporter.otlp.proto.grpc._log_exporter import OTLPLogExporter # 로그 익스포터


logger = get_configured_logger(__name__) # app.config.otel 이름으로 로거 가져오기

# OpenTelemetry settings (기존 코드)
OTEL_EXPORTER_OTLP_ENDPOINT = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://otel-collector:4317")
OTEL_SERVICE_NAME = os.getenv("OTEL_SERVICE_NAME", "product-service") # Product 서비스 이름
# OTEL_TRACES_SAMPLER 환경 변수는 SDK가 자동으로 읽음 (예: "always_on", "parentbased_always_on")
# 명시적으로 설정하지 않으면 ParentBased(AlwaysOnSampler)가 기본값입니다.
# OTEL_PROPAGATORS 환경 변수도 SDK가 자동으로 읽지만, 코드에서 명시적으로 설정하는 것이 더 확실할 수 있습니다.


def setup_non_logging_telemetry(): # 함수 이름 변경: 로깅 관련 설정은 logging_config.py로 이동
# def setup_telemetry():
    try:
        # 1. 리소스 설정 (모든 시그널에 공통 적용)
        resource = Resource.create({
            "service.name": OTEL_SERVICE_NAME,
            "deployment.environment": os.getenv("ENVIRONMENT", "development"),
            # "service.instance.id": os.getenv("HOSTNAME", "unknown"), # Pod 이름 등
        })

        # --- 트레이싱 설정 ---
        tracer_provider = TracerProvider(resource=resource)
        # 샘플러는 OTEL_TRACES_SAMPLER 환경 변수를 따르거나, 여기서 명시적으로 설정 가능
        # 예: from opentelemetry.sdk.trace.sampling import ParentBasedTraceIdRatioSampler
        # tracer_provider = TracerProvider(resource=resource, sampler=ParentBasedTraceIdRatioSampler(0.1))

        otlp_span_exporter = OTLPSpanExporter(endpoint=OTEL_EXPORTER_OTLP_ENDPOINT)
        span_processor = BatchSpanProcessor(otlp_span_exporter)
        tracer_provider.add_span_processor(span_processor)
        trace.set_tracer_provider(tracer_provider) # 전역 TracerProvider 설정

        # !!!!! 👇 컨텍스트 전파를 위한 전역 TextMap Propagator 설정 !!!!!
        # W3C Trace Context를 기본으로 사용합니다.
        # AIOKafkaInstrumentor 등이 이 설정을 참조하여 헤더에서 컨텍스트를 추출/주입합니다.
        propagators_to_set = [TraceContextTextMapPropagator()]
        # 만약 W3C Baggage도 사용한다면 리스트에 추가:
        # from opentelemetry.baggage.propagation import W3CBaggagePropagator
        # propagators_to_set.append(W3CBaggagePropagator())

        if len(propagators_to_set) == 1:
            propagate.set_global_textmap(propagators_to_set[0])
            logger.info(f"Global textmap propagator set to: {propagators_to_set[0].__class__.__name__}")
        # elif len(propagators_to_set) > 1: # 여러 프로파게이터를 사용한다면
            # from opentelemetry.propagate import CompositePropagator
            # propagate.set_global_textmap(CompositePropagator(propagators_to_set))
            # logger.info(f"Global textmap propagator set to CompositePropagator with: {[p.__class__.__name__ for p in propagators_to_set]}")
        # !!!!! 여기까지 추가/확인 !!!!!

        # --- 로깅 설정 ---
        # logger_provider = LoggerProvider(resource=resource)
        # otlp_log_exporter = OTLPLogExporter(endpoint=OTEL_EXPORTER_OTLP_ENDPOINT)
        # log_record_processor = BatchLogRecordProcessor(otlp_log_exporter)
        # logger_provider.add_log_record_processor(log_record_processor)
        # set_logger_provider(logger_provider) # Python 로깅 시스템과 연결

        # OTel 로깅 계측기 활성화 (Trace ID/Span ID 등을 로그에 자동 주입)
        # LoggingInstrumentor().instrument(set_logging_format=True) # 콘솔 로그 형식에도 영향 줄 수 있음

        # --- 라이브러리 자동 계측 활성화 ---
        # FastAPI 계측은 main.py에서 app 객체에 직접 수행하는 것이 일반적
        # instrument_fastapi_app(app) # main.py에서 호출하도록 함수로 분리 권장

        if os.getenv("INSTRUMENT_SQLALCHEMY", "true").lower() == "true":
            SQLAlchemyInstrumentor().instrument()
            logger.info("SQLAlchemyInstrumentor applied.")

        if os.getenv("INSTRUMENT_PYMONGO", "true").lower() == "true":
            PymongoInstrumentor().instrument()
            logger.info("PymongoInstrumentor applied.")
        
        if os.getenv("INSTRUMENT_AIOKAFKA", "true").lower() == "true":
            AIOKafkaInstrumentor().instrument()
            logger.info("AIOKafkaInstrumentor applied.")

        if os.getenv("INSTRUMENT_ELASTICSEARCH", "true").lower() == "true":
            ElasticsearchInstrumentor().instrument()
            logger.info("ElasticsearchInstrumentor applied.")
        
        # Product 서비스가 gRPC 클라이언트로 다른 서비스를 호출한다면 GrpcInstrumentorClient 계측
        # Product 서비스 자체가 gRPC 서버라면 GrpcInstrumentorServer도 필요 (보통 proto 디렉토리가 있으니 서버일 가능성)
        if os.getenv("INSTRUMENT_GRPC_CLIENT", "false").lower() == "true": # 예시: 환경 변수로 제어
             GrpcInstrumentorClient().instrument()
             logger.info("GrpcInstrumentorClient applied.")
        # from opentelemetry.instrumentation.grpc import GrpcInstrumentorServer
        # if os.getenv("INSTRUMENT_GRPC_SERVER", "false").lower() == "true":
        #     GrpcInstrumentorServer().instrument() # 서버 계측 시
        #     logger.info("GrpcInstrumentorServer applied.")


        logger.info(f"OpenTelemetry setup for '{OTEL_SERVICE_NAME}' completed. Exporting to: {OTEL_EXPORTER_OTLP_ENDPOINT}")

    except Exception as e:
        logger.error(f"Failed to setup OpenTelemetry for {OTEL_SERVICE_NAME}: {str(e)}", exc_info=True)
        raise

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