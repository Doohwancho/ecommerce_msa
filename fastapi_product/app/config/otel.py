import os
import logging

from opentelemetry import trace

# 트레이싱 관련 임포트
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter

# 라이브러리 자동 계측기 임포트 (Product 서비스에서 쓰는 것들)
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.grpc import GrpcInstrumentorClient
from opentelemetry.instrumentation.pymongo import PymongoInstrumentor
from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor
from opentelemetry.instrumentation.kafka import KafkaInstrumentor
from opentelemetry.instrumentation.elasticsearch import ElasticsearchInstrumentor


from opentelemetry._logs import set_logger_provider
from opentelemetry.sdk._logs import LoggerProvider
from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
from opentelemetry.exporter.otlp.proto.grpc._log_exporter import OTLPLogExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.instrumentation.logging import LoggingInstrumentor


logger = logging.getLogger(__name__)

# OpenTelemetry settings (기존 코드)
OTEL_EXPORTER_OTLP_ENDPOINT = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://otel-collector:4317")
OTEL_SERVICE_NAME = os.getenv("OTEL_SERVICE_NAME", "product-service") # Product 서비스 이름
OTEL_TRACES_SAMPLER = os.getenv("OTEL_TRACES_SAMPLER", "always_on")
# 메트릭/트레이스 익스포터 설정은 초기화 코드에 직접 들어가니 여기선 주석 처리하거나 참고만 해도 됨
# OTEL_METRICS_EXPORTER = os.getenv("OTEL_METRICS_EXPORTER", "otlp")
# OTEL_TRACES_EXPORTER = os.getenv("OTEL_TRACES_EXPORTER", "otlp")


def setup_telemetry():
    """
    OpenTelemetry 설정 (트레이싱 + 로깅)을 초기화합니다.
    """
    try:
        # !!! 리소스 설정 (트레이싱/로깅 같이 쓴다) !!!
        # Service Name은 필수! 모든 트레이스, 로그에 이 서비스 정보가 붙는다.
        resource = Resource.create({
            "service.name": OTEL_SERVICE_NAME, # 니 서비스 이름 환경변수 가져온 거
            # 다른 리소스 속성들 (예: deployment.environment, service.instance.id 등) 추가 가능
            # 예: "deployment.environment": os.getenv("ENVIRONMENT", "development"),
            # 예: "service.instance.id": socket.gethostname() # Pod 이름 등 고유 ID
        })

        # --- 트레이싱 설정 ---
        # Tracer Provider에 위에서 만든 리소스 연결
        tracer_provider = TracerProvider(resource=resource)
        trace.set_tracer_provider(tracer_provider) # 이 TracerProvider를 전역으로 설정

        # OTLP Span Exporter 설정 (트레이스를 OTel Collector로 보낸다)
        otlp_span_exporter = OTLPSpanExporter(endpoint=OTEL_EXPORTER_OTLP_ENDPOINT)
        # Span Processor 설정 (스팬을 모아서 익스포터로 보낸다)
        span_processor = BatchSpanProcessor(otlp_span_exporter)
        tracer_provider.add_span_processor(span_processor)

        # --- 로깅 설정 ---
        # OTLP 로그 익스포터 설정 (로그도 OTel Collector로 보낸다)
        otlp_log_exporter = OTLPLogExporter(endpoint=OTEL_EXPORTER_OTLP_ENDPOINT)

        # 로그 레코드 프로세서 생성 (로그를 모아서 익스포터로 보낸다)
        log_record_processor = BatchLogRecordProcessor(otlp_log_exporter)

        # 로거 프로바이더 생성 (리소스 연결)
        logger_provider = LoggerProvider(resource=resource) # Logger Provider에도 리소스 연결
        logger_provider.add_log_record_processor(log_record_processor)

        # OTel 로거 프로바이더를 파이썬 로깅 시스템에 전역으로 설정
        set_logger_provider(logger_provider)

        # !!! 여기가 핵심 !!! OTel 로깅 계측 활성화 (기존 logging 라이브러리에 후킹)
        # 이놈이 니 logger.info, logger.error 같은 호출 가로채서 Trace ID/Span ID 붙여준다
        LoggingInstrumentor().instrument() # <-- 임포트 이름과 초기화 방식 수정


        # --- 라이브러리 자동 계측 활성화 ---
        # 주의: LoggingInstrumentation().enable()은 다른 계측기 활성화 전에 호출하는 게 좋다는 의견도 있다.
        #       여기서는 로그/트레이스 SDK 설정 후 다른 계측기들과 함께 호출하는 방식으로 둠.

        # FastAPI (인바운드 웹 요청)
        FastAPIInstrumentor().instrument()

        # gRPC 클라이언트 (아웃바운드 gRPC 호출)
        # 컨텍스트 전파를 위해 서버 쪽에도 gRPC 서버 계측기가 필요하다
        GrpcInstrumentorClient().instrument()

        # DB 계측기들 (PyMongo, SQLAlchemy 등)
        # 이놈들이 DB 호출 스팬을 만들고, 로깅 계측기는 DB 호출 중 찍힌 로그에 Trace ID 붙인다
        PymongoInstrumentor().instrument()
        SQLAlchemyInstrumentor().instrument()

        # 메시징/검색 계측기들 (Kafka, Elasticsearch 등)
        # 이놈들이 Kafka/ES 상호작용 스팬을 만든다
        KafkaInstrumentor().instrument()
        ElasticsearchInstrumentor().instrument()

        # 필요한 다른 계측기들도 여기에 추가

        logger.info("OpenTelemetry tracing and logging instrumentation setup completed successfully for product-service")

    except Exception as e:
        logger.error(f"Failed to setup OpenTelemetry instrumentation for product-service: {str(e)}")
        # 에러 나면 앱 시작 못하게 다시 raise 하는 게 좋다
        raise