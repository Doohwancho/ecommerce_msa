import logging
import sys
import json
from datetime import datetime
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
    # The OpenTelemetry TracerProvider and LoggingInstrumentor setup 
    # has been moved to app.config.otel.setup_telemetry()

    # 로깅 설정 적용 (dictConfig 사용)
    log_config = {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {
            "json": {
                "()": "app.config.logging.JsonFormatter" # Ensure full path for custom class
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
            "app": { # Specific logger for "app" context
                "handlers": ["console"],
                "level": "INFO",
                "propagate": False # Do not propagate to root if it has similar handlers
            },
            "": {  # Root logger
                "handlers": ["console"],
                "level": "INFO",
                # "propagate": False # Root logger propagation is not applicable
            },
            "uvicorn.access": { # To control uvicorn access logs if needed
                "handlers": ["console"],
                "level": "WARNING", # Or your desired level
                "propagate": False
            },
            "uvicorn.error": {
                "handlers": ["console"],
                "level": "INFO", # Or your desired level
                "propagate": False
            }
        }
    }
    dictConfig(log_config)

    # gRPC 로깅 레벨 조정 (dictConfig 이후에 해도 되고, dictConfig 내 logger 설정으로도 가능)
    logging.getLogger('grpc').setLevel(logging.WARNING)
    logging.getLogger('grpc.aio').setLevel(logging.WARNING)