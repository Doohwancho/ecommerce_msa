import grpc
import product_pb2
import product_pb2_grpc
from fastapi import HTTPException
import logging
from typing import List, Tuple, Optional
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type, RetryCallState
from grpc import RpcError
import asyncio
from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode
from opentelemetry.semconv.trace import SpanAttributes # 시맨틱 컨벤션 사용

# 로깅 설정 (애플리케이션 진입점에서 한 번만 설정하는 것이 일반적)
# logging.basicConfig(level=logging.INFO) # 이미 설정되어 있다고 가정
logger = logging.getLogger(__name__)
tracer = trace.get_tracer(__name__) # 모듈 수준 트레이서

# gRPC 채널 옵션 (동일하게 유지)
GRPC_CHANNEL_OPTIONS = [
    ('grpc.max_send_message_length', 50 * 1024 * 1024),
    ('grpc.max_receive_message_length', 50 * 1024 * 1024),
    ('grpc.keepalive_time_ms', 10000),
    ('grpc.keepalive_timeout_ms', 5000),
    ('grpc.keepalive_permit_without_calls', True),
    ('grpc.http2.min_ping_interval_without_data_ms', 5000),
    ('grpc.dns_min_time_between_resolutions_ms', 10000),
]

# Tenacity 재시도 시 로깅 및 스팬 이벤트 추가를 위한 콜백 함수
def log_retry_attempt(retry_state: RetryCallState):
    current_span = trace.get_current_span()
    if current_span.is_recording():
        event_attributes = {
            "retry.attempt_number": retry_state.attempt_number,
            "retry.delay_since_first_attempt_ms": retry_state.delay_since_first_attempt * 1000,
        }
        if retry_state.outcome and retry_state.outcome.failed:
            exc = retry_state.outcome.exception()
            event_attributes["retry.exception_type"] = exc.__class__.__name__
            event_attributes["retry.exception_message"] = str(exc)
            # record_exception은 스팬 자체에 예외를 기록하므로 이벤트에는 요약 정보만 넣거나 생략 가능

        current_span.add_event("RetryAttempt", attributes=event_attributes)
    logger.warning(
        f"Retrying gRPC call, attempt {retry_state.attempt_number}, "
        f"due to: {retry_state.outcome.exception() if retry_state.outcome else 'N/A'}"
    )


class ProductClient:
    def __init__(self, target_address: str = 'product-service:50051'): # 타겟 주소 주입 가능하도록 변경
        self.target_address = target_address
        self.channel: Optional[grpc.aio.Channel] = None # 타입 힌트 명확화
        self.stub: Optional[product_pb2_grpc.ProductServiceStub] = None # 타입 힌트 명확화
        self.default_timeout = 5  # 기본 timeout 5초
        # self.tracer = trace.get_tracer(__name__) # 모듈 수준 트레이서 사용

    async def _ensure_channel(self):
        # 이 메서드는 짧은 시간 내에 완료되지만, 채널 생성 자체를 추적할 수 있음
        # GrpcInstrumentorClient는 채널 생성은 직접 계측하지 않음
        if self.channel is None or self.channel.get_state(try_to_connect=False) == grpc.ChannelConnectivity.SHUTDOWN:
            # 채널이 없거나, 명시적으로 닫힌 경우에만 새로 생성
            with tracer.start_as_current_span("gRPC.channel.ensure_connection") as span:
                span.set_attribute(SpanAttributes.RPC_SYSTEM, "grpc")
                span.set_attribute(SpanAttributes.NET_PEER_NAME, self.target_address.split(':')[0])
                if ':' in self.target_address:
                     span.set_attribute(SpanAttributes.NET_PEER_PORT, self.target_address.split(':')[1])
                else: # 포트가 명시되지 않은 경우 (예: DNS SRV 사용 시)
                     span.set_attribute(SpanAttributes.NET_PEER_PORT, "default_grpc_port") # 또는 실제 사용 포트

                try:
                    if self.channel: # 기존 채널이 있었으나 SHUTDOWN 상태라면 명시적으로 닫기 시도
                        await self.channel.close()

                    self.channel = grpc.aio.insecure_channel(self.target_address, options=GRPC_CHANNEL_OPTIONS)
                    self.stub = product_pb2_grpc.ProductServiceStub(self.channel)
                    logger.info(f"Established new gRPC channel to {self.target_address}")
                    span.set_status(Status(StatusCode.OK))
                    span.add_event("gRPCChannelEstablished")
                except Exception as e:
                    logger.error(f"Failed to establish gRPC channel to {self.target_address}: {e}", exc_info=True)
                    span.record_exception(e)
                    span.set_status(Status(StatusCode.ERROR, "ChannelEstablishmentFailed"))
                    raise # 채널 생성 실패는 심각한 문제이므로 예외를 다시 발생

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=5), # 재시도 간격 조정 (예시)
        retry=retry_if_exception_type((RpcError, ConnectionError, asyncio.TimeoutError)), # TimeoutError도 재시도 대상 포함
        before_sleep=log_retry_attempt, # 재시도 전 콜백
        reraise=True
    )
    async def get_product(self, product_id: str) -> product_pb2.ProductResponse: # 반환 타입 명시
        # 이 스팬은 get_product 작업 전체(재시도 포함)를 감싼다.
        # GrpcInstrumentorClient가 각 gRPC 시도에 대한 자식 스팬을 생성한다.
        with tracer.start_as_current_span("ProductClient.get_product") as span: # 스팬 이름 변경 (클래스.메서드)
            span.set_attribute(SpanAttributes.RPC_SYSTEM, "grpc") # 이 작업이 gRPC 호출임을 명시
            span.set_attribute("app.product_id", product_id) # 애플리케이션 특정 속성
            try:
                await self._ensure_channel()
                
                request = product_pb2.ProductRequest(product_id=product_id)
                # GrpcInstrumentorClient가 `self.stub.GetProduct` 호출을 자동으로 계측
                response = await self.stub.GetProduct(request, timeout=self.default_timeout)
                
                if not response.product_id: # 응답은 왔지만, 내용이 없는 경우 (서비스 로직에 따라)
                    logger.warning(f"Product {product_id} not found by service (empty response).")
                    span.set_attribute("app.product.found", False)
                    span.set_status(Status(StatusCode.ERROR, "ProductNotFoundByServiceLogic")) # OK가 아님을 명시
                    raise HTTPException(status_code=404, detail="Product not found by service logic")
                
                span.set_attribute("app.product.found", True)
                span.set_attribute("app.response.product.title", response.title)
                span.set_attribute("app.response.product.price", response.price)
                span.set_status(Status(StatusCode.OK))
                return response
            # asyncio.TimeoutError는 tenacity @retry에서 처리되도록 함 (retry_if_exception_type에 포함)
            except grpc.RpcError as e:
                logger.error(f"gRPC RpcError in get_product for product_id {product_id}: {e.code()} - {e.details()}", exc_info=True)
                span.record_exception(e) # 스팬에 예외 기록
                # 자동 계측된 gRPC 스팬에도 오류 상태가 기록됨
                span.set_attribute(SpanAttributes.RPC_GRPC_STATUS_CODE, e.code().value[0]) # gRPC 상태 코드 기록
                span.set_status(Status(StatusCode.ERROR, f"gRPC RpcError: {e.details()}"))
                
                if e.code() == grpc.StatusCode.NOT_FOUND:
                    raise HTTPException(status_code=404, detail=f"Product {product_id} not found (gRPC NOT_FOUND)")
                elif e.code() == grpc.StatusCode.UNAVAILABLE:
                    raise HTTPException(status_code=503, detail="Product service unavailable")
                # DEADLINE_EXCEEDED는 asyncio.TimeoutError로 잡히거나, gRPC 자체 타임아웃으로 올 수 있음
                elif e.code() == grpc.StatusCode.DEADLINE_EXCEEDED:
                    raise HTTPException(status_code=504, detail="Product service request timed out (gRPC DEADLINE_EXCEEDED)")
                else:
                    raise HTTPException(status_code=500, detail=f"gRPC call failed: {e.details()}")
            except Exception as e: # 그 외 예외 (예: HTTPException, 개발 중 실수 등)
                logger.error(f"Unexpected error in get_product for product_id {product_id}: {e}", exc_info=True)
                span.record_exception(e)
                span.set_status(Status(StatusCode.ERROR, "UnexpectedErrorInGetProduct"))
                # 이미 HTTPException인 경우 그대로, 아니면 500으로 변환
                if not isinstance(e, HTTPException):
                    raise HTTPException(status_code=500, detail=f"An unexpected error occurred: {str(e)}")
                raise

    # 다른 메서드들(check_availability, check_and_reserve_inventory 등)도 유사한 패턴으로 수정
    # - 스팬 이름: ProductClient.<method_name>
    # - @retry 데코레이터에 before_sleep=log_retry_attempt 추가
    # - 주요 파라미터 및 응답 정보를 app.* 형태의 속성으로 추가
    # - grpc.RpcError 및 기타 예외 처리 시 span.record_exception 및 span.set_status, SpanAttributes.RPC_GRPC_STATUS_CODE 추가

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=5),
        retry=retry_if_exception_type((RpcError, ConnectionError, asyncio.TimeoutError)),
        before_sleep=log_retry_attempt,
        reraise=True
    )
    async def check_availability(self, product_id: str, quantity: int) -> Tuple[bool, Optional[product_pb2.ProductResponse]]:
        with tracer.start_as_current_span("ProductClient.check_availability") as span:
            span.set_attribute(SpanAttributes.RPC_SYSTEM, "grpc")
            span.set_attribute("app.product_id", product_id)
            span.set_attribute("app.request.quantity", quantity)
            product_info: Optional[product_pb2.ProductResponse] = None
            try:
                await self._ensure_channel()
                
                # 1. 상품 정보 가져오기 (내부 호출이지만, 이 메서드의 일부로 트레이스)
                # get_product 호출 시 자체적인 스팬 생성 (부모-자식 관계)
                product_info = await self.get_product(product_id) # 이 호출은 이미 트레이싱됨
                # get_product에서 product_id가 없으면 HTTPException(404) 발생하므로, product_info는 항상 유효하거나 예외 발생
                
                # 2. 재고 정보 가져오기
                # get_product_inventory 호출 시 자체적인 스팬 생성
                inventory = await self.get_product_inventory(product_id) # 이 호출은 이미 트레이싱됨
                if not inventory or not inventory.product_id: # product_id 확인 추가
                    logger.warning(f"Inventory info not found for product {product_id} during check_availability.")
                    span.set_attribute("app.inventory.found", False)
                    # 제품은 찾았지만 재고 정보가 없는 경우, 서비스 로직에 따라 처리
                    # 여기서는 False 반환, 제품 정보는 전달
                    span.set_status(Status(StatusCode.OK, "InventoryInfoNotFoundButProductExists")) # 에러는 아님
                    return False, product_info

                span.set_attribute("app.inventory.found", True)
                span.set_attribute("app.inventory.available_stock", inventory.available_stock)
                
                available = inventory.available_stock >= quantity
                span.set_attribute("app.inventory.is_available", available)
                
                if not available:
                    logger.warning(f"Product {product_id} insufficient stock. Required: {quantity}, Available: {inventory.available_stock}")
                else:
                    logger.info(f"Product {product_id} sufficient stock. Required: {quantity}, Available: {inventory.available_stock}")
                
                span.set_status(Status(StatusCode.OK))
                return available, product_info

            except HTTPException as http_exc: # get_product 등에서 발생한 HTTP 예외
                # 이 경우는 보통 404 (Product Not Found) 등이며, 재시도 대상이 아닐 수 있음
                # tenacity의 retry_if_exception_type에 따라 재시도 여부 결정됨
                logger.warning(f"HTTPException during check_availability for {product_id}: {http_exc.detail}", exc_info=True)
                span.record_exception(http_exc) # 자식 스팬(get_product)에서 이미 기록되었을 수 있음
                span.set_status(Status(StatusCode.ERROR, f"AvailabilityCheckFailedDueToHTTPException: {http_exc.detail}"))
                # False와 함께 product_info (있다면) 반환 또는 예외 다시 발생
                # 현재 코드는 tenacity에서 reraise=True이므로 get_product의 HTTPException이 그대로 올라감.
                # check_availability의 반환 타입에 맞게 처리하려면, 여기서 잡아서 (False, product_info) 반환해야 할 수 있음
                # 하지만, 제품 자체가 없으면 False, None이 더 적절.
                if http_exc.status_code == 404:
                    return False, None # 명시적으로 제품 없음 처리
                raise # 다른 HTTP 예외는 그대로 전파
            except grpc.RpcError as e: # get_product_inventory 등에서 직접 발생한 RpcError
                logger.error(f"gRPC RpcError in check_availability for product_id {product_id}: {e.code()} - {e.details()}", exc_info=True)
                span.record_exception(e)
                span.set_attribute(SpanAttributes.RPC_GRPC_STATUS_CODE, e.code().value[0])
                span.set_status(Status(StatusCode.ERROR, f"gRPC RpcError: {e.details()}"))
                # RpcError 발생 시 False와 함께 product_info (있다면) 반환
                return False, product_info
            except Exception as e:
                logger.error(f"Unexpected error in check_availability for product_id {product_id}: {e}", exc_info=True)
                span.record_exception(e)
                span.set_status(Status(StatusCode.ERROR, "UnexpectedErrorInCheckAvailability"))
                return False, product_info # 예기치 않은 오류 시에도 (False, product_info) 반환


    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=5),
        retry=retry_if_exception_type((RpcError, ConnectionError, asyncio.TimeoutError)),
        before_sleep=log_retry_attempt,
        reraise=True # 실패 시 예외를 다시 발생시켜 호출자가 처리하도록 함
    )
    async def check_and_reserve_inventory(self, product_id: str, quantity: int) -> tuple[bool, str]:
        with tracer.start_as_current_span("ProductClient.check_and_reserve_inventory") as span:
            span.set_attribute(SpanAttributes.RPC_SYSTEM, "grpc")
            span.set_attribute("app.product_id", product_id)
            span.set_attribute("app.request.quantity", quantity)
            try:
                await self._ensure_channel()
                request = product_pb2.InventoryRequest(product_id=product_id, quantity=quantity)
                response = await self.stub.CheckAndReserveInventory(request, timeout=10) # 타임아웃 증가 예시

                span.set_attribute("app.response.success", response.success)
                span.set_attribute("app.response.message", response.message[:256]) # 메시지 길이 제한

                if not response.success:
                    logger.warning(f"Failed to check and reserve inventory for product {product_id}: {response.message}")
                    # 성공 여부와 관계없이 gRPC 호출 자체는 성공했을 수 있으므로 OK로 두되, 추가 속성으로 결과 명시
                    span.set_status(Status(StatusCode.OK, "ReservationLogicFailed")) 
                else:
                    span.set_status(Status(StatusCode.OK))
                return response.success, response.message
            # asyncio.TimeoutError는 tenacity @retry에서 처리
            except grpc.RpcError as e:
                logger.error(f"gRPC RpcError in check_and_reserve_inventory for {product_id}: {e.code()} - {e.details()}", exc_info=True)
                span.record_exception(e)
                span.set_attribute(SpanAttributes.RPC_GRPC_STATUS_CODE, e.code().value[0])
                span.set_status(Status(StatusCode.ERROR, f"gRPC RpcError: {e.details()}"))
                # tenacity에서 reraise=True 이므로 예외가 다시 발생됨.
                # 호출부에서 이 예외를 보고 False, error_message를 반환하거나 다른 처리를 해야 함.
                # 이 함수의 반환 타입 tuple[bool, str]을 맞추기 위해선 여기서 변환 필요.
                # 하지만 reraise=True면 이 부분은 실행되지 않을 수 있음.
                # reraise=False로 하고 여기서 (False, e.details())를 반환하는 방법도 있음.
                # 현재는 reraise=True이므로, 호출자가 HTTPException 등으로 변환할 것임.
                raise 
            except Exception as e:
                logger.error(f"Unexpected error in check_and_reserve_inventory for {product_id}: {e}", exc_info=True)
                span.record_exception(e)
                span.set_status(Status(StatusCode.ERROR, "UnexpectedError"))
                raise # 예측 못한 에러는 그대로 전파

    # release_inventory, get_product_inventory도 유사하게 수정

    async def close(self):
        if self.channel:
            with tracer.start_as_current_span("gRPC.channel.close") as span: # 스팬 이름 명확히
                span.set_attribute(SpanAttributes.RPC_SYSTEM, "grpc")
                span.set_attribute(SpanAttributes.NET_PEER_NAME, self.target_address.split(':')[0])
                try:
                    logger.info(f"Closing gRPC channel to {self.target_address}")
                    await self.channel.close()
                    self.channel = None
                    self.stub = None
                    span.set_status(Status(StatusCode.OK))
                    span.add_event("gRPCChannelClosed")
                except Exception as e:
                    logger.error(f"Error closing gRPC channel: {e}", exc_info=True)
                    span.record_exception(e)
                    span.set_status(Status(StatusCode.ERROR, "ChannelCloseFailed"))