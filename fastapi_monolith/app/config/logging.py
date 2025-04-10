import logging
from logging.config import dictConfig
import socket

# 로깅 설정
log_config = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "json": {
            "()": "pythonjsonlogger.jsonlogger.JsonFormatter",
            "format": "%(asctime)s %(levelname)s %(name)s %(message)s %(hostname)s",
            "datefmt": "%Y-%m-%d %H:%M:%S",
        }
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "json",
            "stream": "ext://sys.stdout",
        },
    },
    "loggers": {
        "app": {
            "handlers": ["console"],
            "level": "INFO",
            "propagate": True
        },
    }
}

# 로깅 설정 적용
dictConfig(log_config)
logger = logging.getLogger("app")

# hostname 추가
logger = logging.LoggerAdapter(logger, {'hostname': socket.gethostname()})
