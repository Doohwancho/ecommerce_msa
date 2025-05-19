import os
import logging

from opentelemetry import trace # 트레이싱용
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

# LoggingInstrumentation 대신 LoggingInstrumentor 임포트 (0.42b0 버전 호환 추정)
from opentelemetry.instrumentation.logging import LoggingInstrumentor

# Kafka, SQLAlchemy는 제공된 requirements.txt 및 에러 컨텍스트에 없었으므로 제거합니다.
# 필요하다면 해당 패키지 및 계측기를 requirements.txt에 추가하고 여기에 임포트/초기화하세요.
# from opentelemetry.instrumentation.kafka import KafkaInstrumentor
# from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor


logger = logging.getLogger(__name__)

# OpenTelemetry settings
OTEL_EXPORTER_OTLP_ENDPOINT = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://otel-collector:4317")
# OTEL_SERVICE_NAME은 Deployment YAML 환경 변수에서 제대로 설정되어야 함
OTEL_SERVICE_NAME = os.getenv("OTEL_SERVICE_NAME", "user-service") # 제공된 코드와 requirements.txt 기준으로 user-service로 유지

# 트레이스 샘플러 설정 (필요에 따라 수정)
OTEL_TRACES_SAMPLER = os.getenv("OTEL_TRACES_SAMPLER", "always_on") # always_on, parentbased_always_on 등

# 메트릭스/트레이스 익스포터 타입 변수는 설정 자체에 직접 사용되지 않으므로 제거하거나 필요에 따라 유지
# OTEL_METRICS_EXPORTER = os.getenv("OTEL_METRICS_EXPORTER", "otlp")
# OTEL_TRACES_EXPORTER = os.getenv("OTEL_TRACES_EXPORTER", "otlp")


def setup_telemetry():
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

        # --- 로깅 설정 ---
        # OTLP 로그 익스포터 설정 (로그 레코드를 컬렉터로 보냄)
        # 트레이스와 같은 OTLP 컬렉터 주소를 사용합니다.
        otlp_log_exporter = OTLPLogExporter(endpoint=OTEL_EXPORTER_OTLP_ENDPOINT)

        # 로그 레코드 프로세서 생성 (로그 레코드를 모아서 배치로 보냄)
        log_record_processor = BatchLogRecordProcessor(otlp_log_exporter)

        # 로거 프로바이더 생성 (리소스 연결)
        # 이 프로바이더를 통해 생성된 로거들이 로그를 OpenTelemetry 파이프라인으로 보냅니다.
        logger_provider = LoggerProvider(resource=resource)
        logger_provider.add_log_record_processor(log_record_processor)

        # OpenTelemetry 로거 프로바이더를 파이썬의 표준 로깅 시스템에 연결
        # 이를 통해 표준 logging.getLogger(__name__).info(...) 호출이 OTel 파이프라인으로 흐르게 됩니다.
        set_logger_provider(logger_provider)

        # OpenTelemetry 로깅 계측 활성화
        # 0.42b0 버전에서는 LoggingInstrumentor().instrument() 방식 사용 추정
        # 이 부분이 표준 logging 라이브러리를 후킹하여 로그 레코드에 트레이스 컨텍스트(Trace ID/Span ID)를 추가하고 OTel 파이프라인으로 보냅니다.
        LoggingInstrumentor().instrument() # <-- 임포트 이름과 초기화 방식 수정


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