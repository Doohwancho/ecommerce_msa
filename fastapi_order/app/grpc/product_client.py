# fastapi-order/app/grpc/product_client.py
import grpc
import product_pb2 # 네가 생성한 product_pb2.py 파일
import product_pb2_grpc # 네가 생성한 product_pb2_grpc.py 파일
from fastapi import HTTPException
import logging
from typing import List, Tuple, Optional # Tuple 임포트
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type, RetryCallState
from grpc import RpcError, aio as grpc_aio # aio 명시적 임포트
import asyncio
from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode
from opentelemetry.semconv.trace import SpanAttributes
from circuitbreaker import circuit, CircuitBreakerError # CircuitBreakerError 임포트
import os

logger = logging.getLogger(__name__)
# 모듈 수준 트레이서는 애플리케이션 시작 시 OTel 설정이 완료된 후 생성되도록 하는 것이 좋음
# 여기서는 각 클라이언트 인스턴스가 생성될 때 또는 메서드 호출 시 트레이서를 얻도록 변경 가능
# tracer = trace.get_tracer(__name__) # 또는 클라이언트 __init__에서 self.tracer = trace.get_tracer(...)

GRPC_CHANNEL_OPTIONS = [
    ('grpc.max_send_message_length', 50 * 1024 * 1024),
    ('grpc.max_receive_message_length', 50 * 1024 * 1024),
    ('grpc.keepalive_time_ms', 10000),
    ('grpc.keepalive_timeout_ms', 5000),
    ('grpc.keepalive_permit_without_calls', True),
    ('grpc.http2.min_ping_interval_without_data_ms', 5000),
    ('grpc.dns_min_time_between_resolutions_ms', 10000),
]

def log_product_client_retry_attempt(retry_state: RetryCallState):
    # UserClient의 콜백 함수와 동일한 로직 사용 가능 (또는 서비스별로 커스터마이징)
    tracer_for_log = trace.get_tracer("app.grpc.product_client.retry_logger") # 로깅용 트레이서
    current_span = trace.get_current_span() # 현재 활성화된 스팬 가져오기
    attempt_number = retry_state.attempt_number
    exception_info = ""
    if retry_state.outcome and retry_state.outcome.failed:
        exc = retry_state.outcome.exception()
        exception_info = f" due to: {exc.__class__.__name__} - {str(exc)}"
    if current_span.is_recording():
        current_span.add_event(
            "gRPCMethodRetryAttempt",
            attributes={
                "retry.attempt_number": attempt_number,
                "retry.exception_type": exc.__class__.__name__ if retry_state.outcome and retry_state.outcome.failed else "N/A", # Ensure exc is defined
                "retry.exception_message": str(exc) if retry_state.outcome and retry_state.outcome.failed else "N/A", # Ensure exc is defined
                "retry.delay_since_first_attempt_ms": retry_state.delay_since_first_attempt * 1000
            }
        )
    logger.warning(f"Retrying ProductClient gRPC call, attempt {attempt_number}{exception_info}")


class ProductClient:
    def __init__(self, host: Optional[str] = None, port: Optional[str] = None):
        self.host = host or os.getenv("PRODUCT_SERVICE_HOST", "product-service")
        self.port = port or os.getenv("PRODUCT_SERVICE_GRPC_PORT", "50051")
        self.target = f"{self.host}:{self.port}"
        self.channel: Optional[grpc_aio.Channel] = None
        self.stub: Optional[product_pb2_grpc.ProductServiceStub] = None
        self.default_timeout = 10  # 기본 타임아웃 10초 (조정 가능)
        self.tracer = trace.get_tracer("app.grpc.ProductClient", "0.1.0") # 인스턴스별 트레이서

        # Circuit Breaker 인스턴스 (각 ProductClient 인스턴스마다 개별 상태를 가짐)
        self.circuit_breaker = circuit(
            failure_threshold=3,    # 3번 연속 실패하면 open
            recovery_timeout=20,    # 20초 후 half-open
            expected_exception=(RpcError, ConnectionError, asyncio.TimeoutError, CircuitBreakerError), # CircuitBreakerError도 추가 (중첩 방지)
            name=f"ProductClient.{self.target}" # 서킷 브레이커에 고유 이름 부여 (로깅/모니터링 용이)
        )
        logger.info(f"Initialized ProductClient with target: {self.target}")

    async def _ensure_channel(self):
        # UserClient의 _ensure_channel과 거의 동일한 로직. 스팬 이름 등만 ProductClient에 맞게 수정.
        current_state = self.channel.get_state(try_to_connect=False) if self.channel else None
        if self.channel is None or current_state == grpc.ChannelConnectivity.SHUTDOWN:
            with self.tracer.start_as_current_span("gRPC.channel.ensure_product_service_connection") as span:
                span.set_attribute(SpanAttributes.RPC_SYSTEM, "grpc")
                span.set_attribute(SpanAttributes.NET_PEER_NAME, self.host)
                span.set_attribute(SpanAttributes.NET_PEER_PORT, self.port)
                try:
                    if self.channel and current_state == grpc.ChannelConnectivity.SHUTDOWN:
                        await self.channel.close()
                    logger.info(f"Creating new gRPC channel to ProductService at {self.target}")
                    self.channel = grpc_aio.insecure_channel(self.target, options=GRPC_CHANNEL_OPTIONS)
                    self.stub = product_pb2_grpc.ProductServiceStub(self.channel)
                    span.set_status(Status(StatusCode.OK))
                    span.add_event("ProductService.gRPCChannelEstablished")
                except Exception as e:
                    logger.error(f"Failed to establish gRPC channel to ProductService at {self.target}: {e}", exc_info=True)
                    if span.is_recording(): span.record_exception(e); span.set_status(Status(StatusCode.ERROR, "ProductChannelEstablishmentFailed"))
                    self.channel = None; self.stub = None; raise

    # 데코레이터 순서: @circuit이 바깥쪽, @retry가 안쪽
    # 이렇게 하면 서킷이 열렸을 때는 재시도 로직 자체가 실행 안 됨.
    @circuit(failure_threshold=3, recovery_timeout=20, expected_exception=(RpcError, ConnectionError, asyncio.TimeoutError))
    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=0.5, max=3), # 재시도 간격 살짝 줄임
        retry=retry_if_exception_type((RpcError, ConnectionError, asyncio.TimeoutError)),
        before_sleep=log_product_client_retry_attempt,
        reraise=True
    )
    async def get_product(self, product_id: str) -> product_pb2.ProductResponse:
        # 메서드 시작 시 트레이서 다시 가져오기 (NoOpTracer 방지 위한 습관)
        # tracer = trace.get_tracer(__name__) # 또는 self.tracer 사용
        with self.tracer.start_as_current_span("ProductClient.get_product_call") as span: # 스팬 이름 변경
            span.set_attribute(SpanAttributes.RPC_SYSTEM, "grpc")
            span.set_attribute(SpanAttributes.RPC_SERVICE, "ProductService") # 호출하는 서비스 명시
            span.set_attribute(SpanAttributes.RPC_METHOD, "GetProduct")    # 호출하는 메서드 명시
            span.set_attribute("app.product_id", product_id)
            try:
                await self._ensure_channel()
                if not self.stub: raise ConnectionError("ProductService stub not available for get_product.")
                
                request = product_pb2.ProductRequest(product_id=product_id) # 요청 객체 이름 확인
                logger.info(f"ProductClient: Calling GetProduct for product_id: {product_id}")
                # GrpcInstrumentorClient가 이 stub 호출을 자동으로 계측하여 CLIENT 스팬을 생성
                response = await self.stub.GetProduct(request, timeout=self.default_timeout)
                
                if not response or not response.product_id: # 응답 내용으로 성공/실패 판단 강화
                    logger.warning(f"Product {product_id} not found by ProductService (empty or invalid response).")
                    span.set_attribute("app.product.found", False)
                    span.set_status(Status(StatusCode.ERROR, "ProductNotFoundByServiceLogic")) # 서비스 로직상 못 찾은 것도 에러로 간주 가능
                    raise HTTPException(status_code=404, detail=f"Product {product_id} not found via ProductService")
                
                span.set_attribute("app.product.found", True)
                # ... (필요한 응답값 속성으로 추가)
                span.set_status(Status(StatusCode.OK))
                return response
            except CircuitBreakerError as cbe: # 서킷 브레이커가 열려서 발생한 예외
                logger.error(f"Circuit open for ProductClient.get_product(id={product_id}): {cbe}", exc_info=True)
                if span.is_recording(): span.record_exception(cbe); span.set_status(Status(StatusCode.ERROR, "CircuitBreakerOpen"))
                raise HTTPException(status_code=503, detail=f"Product service is temporarily unavailable (circuit open): {cbe}")
            except grpc.RpcError as e:
                # ... (UserClient와 유사한 RpcError 처리 로직)
                logger.error(f"gRPC RpcError in ProductClient.get_product for {product_id}: {e.code()} - {e.details()}", exc_info=True)
                if span.is_recording(): span.record_exception(e); span.set_attribute(SpanAttributes.RPC_GRPC_STATUS_CODE, e.code().value[0]); span.set_status(Status(StatusCode.ERROR, str(e.details())))
                if e.code() == grpc.StatusCode.NOT_FOUND: raise HTTPException(status_code=404, detail=f"Product {product_id} not found (gRPC)")
                elif e.code() == grpc.StatusCode.UNAVAILABLE: raise HTTPException(status_code=503, detail="Product service unavailable")
                elif e.code() == grpc.StatusCode.DEADLINE_EXCEEDED: raise HTTPException(status_code=504, detail="Product service request timed out")
                else: raise HTTPException(status_code=500, detail=f"Product service gRPC call failed: {e.details()}")
            except asyncio.TimeoutError as te: # Tenacity 재시도 중 stub 호출의 timeout 또는 asyncio.wait_for의 타임아웃
                logger.error(f"TimeoutError in ProductClient.get_product for {product_id} after retries: {te}", exc_info=True)
                if span.is_recording(): span.record_exception(te); span.set_status(Status(StatusCode.ERROR, "TimeoutAfterRetries"))
                raise HTTPException(status_code=504, detail="Product service request timed out after retries")
            except Exception as e:
                # ... (UserClient와 유사한 일반 예외 처리 로직)
                logger.error(f"Unexpected error in ProductClient.get_product for {product_id}: {e}", exc_info=True)
                if span.is_recording(): span.record_exception(e); span.set_status(Status(StatusCode.ERROR, "UnexpectedError"))
                if not isinstance(e, HTTPException): raise HTTPException(status_code=500, detail=str(e))
                raise

    # check_and_reserve_inventory 메서드도 유사하게 @circuit, @retry, OTel 스팬 적용
    @circuit(failure_threshold=3, recovery_timeout=20, expected_exception=(RpcError, ConnectionError, asyncio.TimeoutError, CircuitBreakerError))
    @retry(
        stop=stop_after_attempt(2), # 재고 관련 작업은 재시도 횟수 줄일 수도 있음
        wait=wait_exponential(multiplier=1, min=0.2, max=2),
        retry=retry_if_exception_type((RpcError, ConnectionError, asyncio.TimeoutError)),
        before_sleep=log_product_client_retry_attempt,
        reraise=True
    )
    async def check_and_reserve_inventory(self, product_id: str, quantity: int) -> Tuple[bool, str]:
        # tracer = trace.get_tracer(__name__)
        with self.tracer.start_as_current_span("ProductClient.check_and_reserve_inventory_call") as span:
            span.set_attribute(SpanAttributes.RPC_SYSTEM, "grpc")
            span.set_attribute(SpanAttributes.RPC_SERVICE, "ProductService")
            span.set_attribute(SpanAttributes.RPC_METHOD, "CheckAndReserveInventory")
            span.set_attribute("app.product_id", product_id)
            span.set_attribute("app.quantity_to_reserve", quantity)
            try:
                await self._ensure_channel()
                if not self.stub: raise ConnectionError("ProductService stub not available for check_and_reserve_inventory.")

                request = product_pb2.InventoryRequest(product_id=product_id, quantity=quantity) # 요청 객체 이름 확인
                logger.info(f"ProductClient: Calling CheckAndReserveInventory for product {product_id}, quantity {quantity}")
                response = await self.stub.CheckAndReserveInventory(request, timeout=self.default_timeout)

                span.set_attribute("app.inventory.reservation.success", response.success)
                span.set_attribute("app.inventory.reservation.message", response.message[:256])
                if response.success:
                    span.set_status(Status(StatusCode.OK))
                else:
                    # 비즈니스 로직상 실패는 에러는 아닐 수 있지만, 스팬에는 기록
                    span.set_status(Status(StatusCode.OK, f"InventoryReservationFailedLogically: {response.message}"))
                return response.success, response.message
            except CircuitBreakerError as cbe:
                logger.error(f"Circuit open for ProductClient.check_and_reserve_inventory(id={product_id}, qty={quantity}): {cbe}", exc_info=True)
                if span.is_recording(): span.record_exception(cbe); span.set_status(Status(StatusCode.ERROR, "CircuitBreakerOpen"))
                # SAGA 패턴에서는 보상 트랜잭션 유발을 위해 특정 예외를 발생시키거나, (False, 메시지) 반환
                return False, f"Product service temporarily unavailable (circuit open): {cbe}"
            except grpc.RpcError as e:
                # ... (get_product과 유사한 RpcError 처리, False, 메시지 반환)
                logger.error(f"gRPC RpcError in ProductClient.check_and_reserve for {product_id}: {e.code()} - {e.details()}", exc_info=True)
                if span.is_recording(): span.record_exception(e); span.set_attribute(SpanAttributes.RPC_GRPC_STATUS_CODE, e.code().value[0]); span.set_status(Status(StatusCode.ERROR, str(e.details())))
                # SAGA 패턴에 맞춰 (False, 에러메시지) 반환 또는 특정 예외 발생
                return False, f"gRPC Error: {e.details()}" 
            except asyncio.TimeoutError as te:
                logger.error(f"TimeoutError in ProductClient.check_and_reserve for {product_id} after retries: {te}", exc_info=True)
                if span.is_recording(): span.record_exception(te); span.set_status(Status(StatusCode.ERROR, "TimeoutAfterRetries"))
                return False, "Product service request timed out after retries"
            except Exception as e:
                # ... (get_product과 유사한 일반 예외 처리, False, 메시지 반환)
                logger.error(f"Unexpected error in ProductClient.check_and_reserve for {product_id}: {e}", exc_info=True)
                if span.is_recording(): span.record_exception(e); span.set_status(Status(StatusCode.ERROR, "UnexpectedError"))
                return False, f"Unexpected error: {str(e)}"


    # cancel_inventory_reservation 메서드도 check_and_reserve_inventory와 유사하게 @circuit, @retry, OTel 스팬 적용

    async def close(self):
        # UserClient의 close와 동일한 로직
        if self.channel:
            # tracer = trace.get_tracer(__name__)
            with self.tracer.start_as_current_span("gRPC.channel.close_product_service") as span:
                # ... (UserClient와 동일하게 스팬 속성, 로깅, 예외 처리)
                pass