# payment-service/app/config/otel.py
import os
import logging # 표준 로깅 대신 get_configured_logger 사용

# logging_config.py의 함수들 임포트
from app.config.payment_logging import (
    get_global_tracer_provider,
    get_configured_logger,
    # shutdown_otel_providers # atexit은 logging_config.py에서 한 번만 등록
)

from opentelemetry import propagate, trace
from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator
# from opentelemetry.baggage.propagation import W3CBaggagePropagator

from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor
from opentelemetry.instrumentation.aiokafka import AIOKafkaInstrumentor
# from opentelemetry.instrumentation.grpc import GrpcInstrumentorClient # 필요시 주석 해제

# 이 파일 내에서 사용할 로거 (logging_config.py를 통해 설정된 로거를 가져옴)
logger = get_configured_logger(__name__) # app.config.otel 이름으로 로거 가져오기

# OTEL_SERVICE_NAME은 logging_config.py에서 주로 사용되지만, FastAPI 계측 시 로깅을 위해 여기서도 읽을 수 있음
OTEL_SERVICE_NAME_FOR_LOGGING = os.getenv("OTEL_SERVICE_NAME", "payment-service")


def setup_non_logging_telemetry():
    """
    OpenTelemetry 트레이싱 전파 및 주요 라이브러리 계측을 설정합니다.
    (TracerProvider, LoggerProvider, 로깅 계측은 logging_config.py에서 이미 처리됨)
    """
    logger.info(f"Setting up non-logging telemetry for {OTEL_SERVICE_NAME_FOR_LOGGING} using existing providers.")

    current_tracer_provider = get_global_tracer_provider()
    if current_tracer_provider is None:
        logger.error(
            "TracerProvider not available via getter from logging_config.py. "
            "Ensure initialize_logging_and_telemetry() was called first from main.py."
        )
        # 심각한 오류이므로 여기서 중단하거나, 계측 없이 진행하도록 결정할 수 있음
        # raise RuntimeError("TracerProvider not initialized for non-logging telemetry setup.")
        logger.warning("Proceeding without some instrumentations due to missing TracerProvider.")
        # return # 또는 아래 계측기들을 실행하지 않음

    # 전역 TextMap Propagator 설정
    propagator_list = [TraceContextTextMapPropagator()]
    # if W3CBaggagePropagator: # 필요시 Baggage 추가
    # propagator_list.append(W3CBaggagePropagator())

    if len(propagator_list) == 1:
        propagate.set_global_textmap(propagator_list[0])
        logger.info(f"Global textmap propagator set to: {propagator_list[0].__class__.__name__}")
    # else: # 여러 개일 경우 (현재 해당 없음)
        # from opentelemetry.propagate import CompositePropagator
        # propagate.set_global_textmap(CompositePropagator(propagator_list))
        # logger.info(f"Global textmap propagator set to CompositePropagator with: {[p.__class__.__name__ for p in propagator_list]}")

    # --- 라이브러리 인스트루멘테이션 (FastAPI 제외, Logging 제외) ---
    # 각 계측기는 current_tracer_provider가 있을 때만 시도
    if current_tracer_provider:
        # SQLAlchemyInstrumentor (기존 코드에 있었음)
        if os.getenv("INSTRUMENT_SQLALCHEMY", "true").lower() == "true":
            try:
                SQLAlchemyInstrumentor().instrument(tracer_provider=current_tracer_provider)
                logger.info("SQLAlchemyInstrumentor applied.")
            except Exception as e_sqlalchemy:
                logger.error(f"Failed to apply SQLAlchemyInstrumentor: {e_sqlalchemy}", exc_info=True)

        # AIOKafkaInstrumentor (기존 코드에 있었음)
        if os.getenv("INSTRUMENT_AIOKAFKA", "true").lower() == "true":
            try:
                AIOKafkaInstrumentor().instrument(tracer_provider=current_tracer_provider)
                logger.info("AIOKafkaInstrumentor applied.")
            except Exception as e_aiokafka:
                logger.error(f"Failed to apply AIOKafkaInstrumentor: {e_aiokafka}", exc_info=True)

        # GrpcInstrumentorClient (필요한 경우 추가)
        # if os.getenv("INSTRUMENT_GRPC_CLIENT", "false").lower() == "true":
        # try:
        # GrpcInstrumentorClient().instrument(tracer_provider=current_tracer_provider)
        #         logger.info("GrpcInstrumentorClient applied.")
        # except Exception as e_grpc:
        # logger.error(f"Failed to apply GrpcInstrumentorClient: {e_grpc}", exc_info=True)
    else:
        logger.warning("Skipping library instrumentations because TracerProvider is not available.")


    logger.info(f"Non-logging OpenTelemetry setup for '{OTEL_SERVICE_NAME_FOR_LOGGING}' process finished.")


# atexit 핸들러는 logging_config.py 에서 이미 등록되었으므로 여기서는 제거.
# 이전 코드의 atexit.register(shutdown_telemetry)는 삭제합니다.

def instrument_fastapi_app(app):
    """FastAPI 앱을 OpenTelemetry로 계측합니다."""
    logger.info(f"Attempting to instrument FastAPI app for {OTEL_SERVICE_NAME_FOR_LOGGING}.")
    current_tracer_provider = get_global_tracer_provider()
    if current_tracer_provider is None:
        logger.error(
            "TracerProvider not available for FastAPI instrumentation. "
            "Ensure initialize_logging_and_telemetry() set it up via logging_config.py."
        )
        # FastAPI 계측 실패는 심각할 수 있으므로 오류 발생 또는 로깅 후 반환
        # raise RuntimeError("Cannot instrument FastAPI app without a TracerProvider.")
        return


    if app is None:
        logger.error("FastAPI app instance is None, cannot instrument.")
        # raise ValueError("FastAPI app instance cannot be None for instrumentation") # 기존 코드와 유사하게 처리
        return

    try:
        FastAPIInstrumentor.instrument_app(app, tracer_provider=current_tracer_provider)
        logger.info(f"FastAPI app successfully instrumented by OpenTelemetry for {OTEL_SERVICE_NAME_FOR_LOGGING}")
    except Exception as e:
        logger.error(f"Failed to instrument FastAPI app for {OTEL_SERVICE_NAME_FOR_LOGGING}: {e}", exc_info=True)
        # raise # 필요시 예외 다시 발생