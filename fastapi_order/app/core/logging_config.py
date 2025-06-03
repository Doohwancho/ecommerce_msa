import logging
import sys
import json
from datetime import datetime
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.logging import LoggingInstrumentor
from logging.config import dictConfig
import socket

class CustomJSONEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, (set, frozenset)):
            return list(obj)
        return super().default(obj)

class JsonFormatter(logging.Formatter):
    def format(self, record):
        # 기본 로그 레코드 데이터
        log_data = {
            "timestamp": datetime.utcnow().isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "hostname": socket.gethostname()
        }

        # 예외 정보가 있는 경우 추가
        if record.exc_info:
            log_data["exception"] = {
                "type": record.exc_info[0].__name__,
                "message": str(record.exc_info[1]),
                "stack_trace": self.formatException(record.exc_info)
            }

        # extra 필드 추가
        if hasattr(record, "extra"):
            log_data.update(record.extra)

        return json.dumps(log_data, cls=CustomJSONEncoder)

def setup_logging():
    # OpenTelemetry Tracer 설정
    tracer_provider = TracerProvider()
    otlp_exporter = OTLPSpanExporter(
        endpoint="otel-collector:4317",  # OpenTelemetry Collector 주소
        insecure=True
    )
    span_processor = BatchSpanProcessor(otlp_exporter)
    tracer_provider.add_span_processor(span_processor)
    trace.set_tracer_provider(tracer_provider)

    # LoggingInstrumentor 설정
    LoggingInstrumentor().instrument(
        tracer_provider=tracer_provider,
        log_level=logging.INFO
    )

    # JSON 포맷터 설정
    json_formatter = JsonFormatter()

    # 콘솔 핸들러 설정
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(json_formatter)

    # 루트 로거 설정
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)
    root_logger.addHandler(console_handler)

    # gRPC 로깅 레벨 조정
    logging.getLogger('grpc').setLevel(logging.WARNING)
    logging.getLogger('grpc.aio').setLevel(logging.WARNING)

    # 로깅 설정 적용
    log_config = {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {
            "json": {
                "()": JsonFormatter
            }
        },
        "handlers": {
            "console": {
                "class": "logging.StreamHandler",
                "formatter": "json",
                "stream": "ext://sys.stdout",
            }
        },
        "loggers": {
            "app": {
                "handlers": ["console"],
                "level": "INFO",
                "propagate": True
            },
            "": {  # Root logger
                "handlers": ["console"],
                "level": "INFO",
                "propagate": False
            }
        }
    }

    dictConfig(log_config)
    logger = logging.getLogger("app")

    # hostname 추가
    logger = logging.LoggerAdapter(logger, {'hostname': socket.gethostname()})

    return root_logger 