# app/core/logging_config.py

import logging
import sys
import json
from datetime import datetime, timezone
import socket
import os
import atexit

# OpenTelemetry API 및 SDK
from opentelemetry import trace # 트레이스는 기존 방식 유지 가능
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter

# OpenTelemetry Logs 관련 import (공식 예제 스타일 + 우리 환경)
from opentelemetry.sdk._logs import LoggerProvider, LoggingHandler # _logs 내부 API지만 예제에서 사용
from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
# OTLPLogExporter는 gRPC로!
from opentelemetry.exporter.otlp.proto.grpc._log_exporter import OTLPLogExporter

try:
    from opentelemetry.logs import set_logger_provider # 최신 권장 API
except ImportError: # 이전 버전 호환
    from opentelemetry._logs import set_logger_provider

from opentelemetry.sdk.resources import Resource, DEPLOYMENT_ENVIRONMENT
from opentelemetry.sdk.resources import SERVICE_NAME as SDK_SERVICE_NAME_KEY

# --- OTel SDK 내부 디버그 로깅 활성화 (문제 해결될 때까지 유지!) ---
OTEL_SDK_INTENSIVE_DEBUG_LOGGERS = [
    "opentelemetry.sdk._logs", "opentelemetry.sdk._logs.export",
    "opentelemetry.exporter.otlp", "opentelemetry.exporter.otlp.proto.grpc",
    "opentelemetry.exporter.otlp.proto.grpc._log_exporter",
    # "grpc" # 이건 너무 많으니 일단 제외
]
for logger_name in OTEL_SDK_INTENSIVE_DEBUG_LOGGERS:
    sdk_logger = logging.getLogger(logger_name)
    sdk_logger.setLevel(logging.DEBUG)
    if not sdk_logger.handlers: 
        sdk_handler = logging.StreamHandler(sys.stdout)
        sdk_formatter = logging.Formatter(f'[OTEL_SDK_DEBUG:%(name)s:%(levelname)s] %(message)s')
        sdk_handler.setFormatter(sdk_formatter)
        sdk_logger.addHandler(sdk_handler)
        sdk_logger.propagate = False
# --- OTel SDK 내부 디버그 로깅 활성화 끝 ---

_TRACER_PROVIDER_INSTANCE: TracerProvider | None = None
_LOGGER_PROVIDER_INSTANCE: LoggerProvider | None = None # OTel LoggerProvider
_LOGGING_CONFIGURED: bool = False
_INTERNAL_SETUP_LOGGER: logging.Logger | None = None # 이 파일 자체 설정용 로거

def _get_internal_setup_logger() -> logging.Logger:
    global _INTERNAL_SETUP_LOGGER
    if _INTERNAL_SETUP_LOGGER is None:
        logger = logging.getLogger("app.core.logging_config.setup")
        logger.setLevel(logging.INFO)
        if not logger.handlers:
            handler = logging.StreamHandler(sys.stdout)
            formatter = logging.Formatter('[%(asctime)s] [%(levelname)s] [LOG_SETUP:%(name)s] %(message)s')
            handler.setFormatter(formatter)
            logger.addHandler(handler)
            logger.propagate = False
        _INTERNAL_SETUP_LOGGER = logger
    return _INTERNAL_SETUP_LOGGER

class CustomJSONEncoder(json.JSONEncoder): # (이전과 동일)
    def default(self, obj):
        if isinstance(obj, (set, frozenset)): return list(obj)
        if isinstance(obj, datetime): return obj.isoformat()
        return super().default(obj)

class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        log_data = {
            "@timestamp": datetime.now(timezone.utc).isoformat(), # ⭐⭐⭐ 필드명을 '@timestamp'로 변경! ⭐⭐⭐
            "message": record.getMessage(),
            "level": record.levelname,
            "logger_name": record.name,
            "hostname": socket.gethostname(),
        }
        if record.exc_info: # 예외 정보는 유용하니 일단 유지
            log_data["exception"] = {
                "type": record.exc_info[0].__name__,
                "message": str(record.exc_info[1]),
                "stack_trace": self.formatException(record.exc_info)
            }
        # 다른 복잡한 필드(trace_id, attributes 등)는 일단 주석 처리
        return json.dumps(log_data, cls=CustomJSONEncoder, ensure_ascii=False)

def initialize_logging_and_telemetry():
    global _TRACER_PROVIDER_INSTANCE, _LOGGER_PROVIDER_INSTANCE, _LOGGING_CONFIGURED
    
    internal_logger = _get_internal_setup_logger()

    if _LOGGING_CONFIGURED:
        internal_logger.warning("Skipping: Logging and Telemetry already configured.")
        return

    internal_logger.info("---- Initializing Logging and Telemetry (Official Example Style) ----")

    otel_service_name = os.getenv("OTEL_SERVICE_NAME", "payment-service") # 서비스 이름 변경해서 테스트
    otel_environment = os.getenv("OTEL_ENVIRONMENT", "development")
    otel_collector_grpc_endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "otel-collector:4317")
    
    internal_logger.info(f"Service Name: {otel_service_name}, Environment: {otel_environment}")
    internal_logger.info(f"Target OTLP gRPC Endpoint: '{otel_collector_grpc_endpoint}' (ensure no http:// scheme)")

    # 스킴 제거 (gRPC 엔드포인트는 'host:port' 형식)
    if otel_collector_grpc_endpoint.startswith("http://"):
        otel_collector_grpc_endpoint = otel_collector_grpc_endpoint[len("http://"):]
    elif otel_collector_grpc_endpoint.startswith("https://"):
        otel_collector_grpc_endpoint = otel_collector_grpc_endpoint[len("https://"):]
    
    resource_attributes = {
        SDK_SERVICE_NAME_KEY: otel_service_name,
        DEPLOYMENT_ENVIRONMENT: otel_environment,
        "hostname": socket.gethostname(),
    }
    # 공유 리소스 객체
    common_resource = Resource.create(resource_attributes)
    internal_logger.info(f"Common OTel Resource created: {common_resource.attributes}")

    # --- 1. TracerProvider Setup (기존 방식 유지 또는 유사하게 단순화) ---
    try:
        tracer_provider = TracerProvider(resource=common_resource)
        otlp_span_exporter = OTLPSpanExporter(endpoint=otel_collector_grpc_endpoint, insecure=True)
        tracer_provider.add_span_processor(BatchSpanProcessor(otlp_span_exporter))
        trace.set_tracer_provider(tracer_provider)
        _TRACER_PROVIDER_INSTANCE = tracer_provider
        internal_logger.info(f"TracerProvider configured. Instance: {_TRACER_PROVIDER_INSTANCE}")
    except Exception as e_trace:
        internal_logger.error(f"!!! FAILED to setup TracerProvider: {e_trace}", exc_info=True)

    # --- 2. LoggerProvider Setup (공식 예제 스타일 + OTLPExporter) ---
    try:
        logger_provider = LoggerProvider(resource=common_resource)
        internal_logger.info(f"OTel LoggerProvider created. Instance: {logger_provider}")
        
        # OTLPLogExporter 사용
        otlp_log_exporter = OTLPLogExporter(endpoint=otel_collector_grpc_endpoint, insecure=True)
        internal_logger.info(f"OTLPLogExporter created for logs. Instance: {otlp_log_exporter}")
        
        # 로그 배치 프로세서 (공격적인 설정 유지하며 테스트)
        log_processor = BatchLogRecordProcessor(
            otlp_log_exporter,
            schedule_delay_millis=100,
            max_export_batch_size=1 
        )
        internal_logger.info(f"BatchLogRecordProcessor for logs created with AGGRESSIVE settings. Instance: {log_processor}")
        
        logger_provider.add_log_record_processor(log_processor)
        internal_logger.info("LogRecordProcessor (with OTLPLogExporter) added to LoggerProvider.")
        
        set_logger_provider(logger_provider) # 글로벌 LoggerProvider로 설정!
        internal_logger.info("Global OTel LoggerProvider set via set_logger_provider().")
        _LOGGER_PROVIDER_INSTANCE = logger_provider
        internal_logger.info(f"Global _LOGGER_PROVIDER_INSTANCE set. Instance: {_LOGGER_PROVIDER_INSTANCE}")

        # --- 3. Python 표준 로깅과 연동 (LoggingHandler 사용) ---
        # LoggingInstrumentor().instrument(...) 대신 이 방식을 사용!
        otel_logging_handler = LoggingHandler(
            level=logging.NOTSET, # 핸들러 자체는 모든 레벨을 받고, 실제 필터링은 로거 레벨에서
            logger_provider=logger_provider # 우리가 만든 LoggerProvider 전달
        )
        internal_logger.info(f"OTel LoggingHandler created. Instance: {otel_logging_handler}")
        
        # 루트 로거에 OTel LoggingHandler 추가
        logging.getLogger().addHandler(otel_logging_handler)
        internal_logger.info("OTel LoggingHandler added to Python's root logger.")
        
    except Exception as e_logs_sdk:
        internal_logger.error(f"!!! FAILED during OTel Logs SDK setup (LoggerProvider/Exporter/Handler): {e_logs_sdk}", exc_info=True)

    # --- 4. Python 표준 로깅 콘솔 출력 핸들러 (JSON 포맷) ---
    # 이 부분은 콘솔에 JSON 로그를 찍기 위한 것이므로 OTel 전송과는 별개. 하지만 유용함.
    json_formatter = JsonFormatter()
    console_stream_handler = logging.StreamHandler(sys.stdout)
    console_stream_handler.setFormatter(json_formatter)
    console_stream_handler.setLevel(logging.INFO)

    root_logger = logging.getLogger()
    # 기존에 유사한 핸들러가 없다면 추가 (중복 방지)
    if not any(isinstance(h, logging.StreamHandler) and isinstance(h.formatter, JsonFormatter) for h in root_logger.handlers):
        root_logger.addHandler(console_stream_handler)
        internal_logger.info("JsonFormatter StreamHandler added to root logger for console output.")
    
    root_logger.setLevel(logging.INFO) # 루트 로거의 기본 레벨
    internal_logger.info(f"Root logger level set to INFO. Effective level: {root_logger.getEffectiveLevel()}")
    
    # --- 5. 시끄러운 라이브러리 로그 레벨 조정 ---
    # (이전과 동일)
    noisy_libraries = ["uvicorn.access", "uvicorn.error", "aiokafka", "grpc", "grpc.aio", "httpx"]
    for lib_logger_name in noisy_libraries:
        logging.getLogger(lib_logger_name).setLevel(logging.WARNING)
    internal_logger.info("Log levels for some noisy libraries adjusted to WARNING.")

    _LOGGING_CONFIGURED = True
    final_check_logger = get_configured_logger("app.core.logging_config.final_check") # 이제 이 로거는 OTel 핸들러도 가짐
    final_check_logger.info( # 이 로그는 콘솔에 JSON으로 + OTel Collector로 전송 시도되어야 함
        f"FINAL_CHECK_OFFICIAL_STYLE: Logging and Telemetry setup process finished. Service: '{otel_service_name}'. "
        f"OTLP gRPC Endpoint: '{otel_collector_grpc_endpoint}'."
    )
    internal_logger.info("---- Finished initialize_logging_and_telemetry (Official Example Style) ----")

def get_configured_logger(name: str = None) -> logging.Logger:
    # 이 함수는 이제 initialize_logging_and_telemetry가 먼저 호출되었다고 가정하고,
    # 해당 함수 내부의 _LOGGING_CONFIGURED 플래그에 의존하지 않음 (호출 순서 강제).
    # main.py에서 initialize_logging_and_telemetry()를 반드시 먼저 호출해야 함.
    # 만약 초기화 전에 호출되면, 표준 로거가 반환될 뿐임 (위험성 존재).
    # 좀 더 안전하게 하려면 여기서도 _LOGGING_CONFIGURED 체크 후 initialize_logging_and_telemetry() 호출 가능.
    # 하지만 지금은 main.py의 호출 순서를 신뢰하는 것으로 단순화.
    return logging.getLogger(name) if name else logging.getLogger()

def get_global_tracer_provider() -> TracerProvider | None:
    return _TRACER_PROVIDER_INSTANCE

def get_global_logger_provider() -> LoggerProvider | None:
    return _LOGGER_PROVIDER_INSTANCE

def shutdown_otel_providers():
    logger = get_configured_logger("app.core.logging_config.shutdown") 
    # ... (shutdown 로직은 이전과 동일하게 유지) ...
    service_name = os.getenv('OTEL_SERVICE_NAME', 'unknown-otel-service') # Default if not set
    logger.info(f"Initiating OTel providers shutdown for service '{service_name}'...")
    tracer_provider_to_shutdown = get_global_tracer_provider()
    if tracer_provider_to_shutdown and hasattr(tracer_provider_to_shutdown, 'shutdown'):
        logger.info(f"Shutting down TracerProvider instance: {tracer_provider_to_shutdown}")
        try: tracer_provider_to_shutdown.shutdown()
        except Exception as e: logger.error(f"Error during TracerProvider shutdown: {e}", exc_info=True)
        else: logger.info("TracerProvider shutdown successful.")
    else: logger.info("No active TracerProvider or shutdown method not found.")
    logger_provider_to_shutdown = get_global_logger_provider()
    if logger_provider_to_shutdown and hasattr(logger_provider_to_shutdown, 'shutdown'):
        logger.info(f"Shutting down LoggerProvider instance: {logger_provider_to_shutdown}")
        try: logger_provider_to_shutdown.shutdown()
        except Exception as e: logger.error(f"Error during LoggerProvider shutdown: {e}", exc_info=True)
        else: logger.info("LoggerProvider shutdown successful (includes flushing logs).")
    else: logger.info("No active LoggerProvider or shutdown method not found.")
    logger.info(f"OTel providers shutdown process finished for service '{service_name}'.")

# atexit 등록은 이 파일에서 한 번만!
if not hasattr(atexit, '_otel_shutdown_registered_from_logging_config_v2'): # 플래그 이름 변경해서 확실히 새로 등록
    atexit.register(shutdown_otel_providers)
    atexit._otel_shutdown_registered_from_logging_config_v2 = True
    _get_internal_setup_logger().info("atexit handler 'shutdown_otel_providers' registered from logging_config.py (v2).")