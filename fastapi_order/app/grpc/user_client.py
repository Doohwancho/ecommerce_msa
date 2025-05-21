import grpc
import user_pb2
import user_pb2_grpc
from fastapi import HTTPException
import os
import logging
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type, RetryCallState
from grpc import RpcError,aio # aio 임포트 추가
import asyncio
from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode
from opentelemetry.semconv.trace import SpanAttributes # 시맨틱 컨벤션 사용

# 로깅 설정 (애플리케이션 진입점에서 한 번만 설정 권장)
# logging.basicConfig(level=logging.INFO) # 이미 설정되었다고 가정
logger = logging.getLogger(__name__)
tracer = trace.get_tracer(__name__) # 모듈 수준 트레이서

# gRPC 채널 옵션 (동일하게 유지)
CHANNEL_OPTIONS = [
    ('grpc.max_send_message_length', 50 * 1024 * 1024),
    ('grpc.max_receive_message_length', 50 * 1024 * 1024),
    ('grpc.keepalive_time_ms', 10000),
    ('grpc.keepalive_timeout_ms', 5000),
    ('grpc.keepalive_permit_without_calls', True),
    ('grpc.http2.min_ping_interval_without_data_ms', 5000),
    ('grpc.dns_min_time_between_resolutions_ms', 10000),
]

# Tenacity 재시도 시 로깅 및 스팬 이벤트 추가를 위한 콜백 함수
def log_user_client_retry_attempt(retry_state: RetryCallState):
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
        current_span.add_event("RetryAttempt", attributes=event_attributes)
    logger.warning(
        f"Retrying UserClient gRPC call, attempt {retry_state.attempt_number}, "
        f"due to: {retry_state.outcome.exception() if retry_state.outcome else 'N/A'}"
    )

class UserClient:
    def __init__(self):
        self.host = os.getenv("USER_SERVICE_HOST", "user-service")
        self.port = os.getenv("USER_SERVICE_GRPC_PORT", "50051")
        self.target = f"{self.host}:{self.port}"
        logger.info(f"Initialized UserClient with target: {self.target}")
        self.channel: Optional[grpc.aio.Channel] = None # 타입 힌트 명확화
        self.stub: Optional[user_pb2_grpc.UserServiceStub] = None # 타입 힌트 명확화
        self.default_timeout = 5  # 기본 timeout 5초
        # self.tracer = trace.get_tracer(__name__) # 모듈 수준 트레이서 사용

    async def _ensure_channel(self):
        """gRPC 채널을 확인하고 필요한 경우 생성합니다."""
        # 채널 상태 확인: None 이거나, 마지막으로 알려진 상태가 SHUTDOWN 또는 FATAL_FAILURE 인 경우
        # try_to_connect=False로 하면 즉시 현재 상태를 반환합니다.
        current_state = self.channel.get_state(try_to_connect=False) if self.channel else None
        
        if self.channel is None or current_state in [
            grpc.ChannelConnectivity.SHUTDOWN, 
            # grpc.ChannelConnectivity.FATAL_FAILURE # FATAL_FAILURE는 재연결 시도 안함
        ]:
            with tracer.start_as_current_span("gRPC.channel.ensure_user_service_connection") as span:
                span.set_attribute(SpanAttributes.RPC_SYSTEM, "grpc")
                span.set_attribute(SpanAttributes.NET_PEER_NAME, self.host)
                span.set_attribute(SpanAttributes.NET_PEER_PORT, self.port)
                try:
                    if self.channel and current_state == grpc.ChannelConnectivity.SHUTDOWN: # 이미 닫힌 채널 정리
                        logger.info(f"Existing channel to {self.target} is SHUTDOWN. Attempting to close it before recreating.")
                        await self.channel.close() # 이미 닫혔다면 에러 없이 완료될 수 있음
                    
                    logger.info(f"Creating new gRPC channel to {self.target}")
                    self.channel = grpc.aio.insecure_channel(self.target, options=CHANNEL_OPTIONS)
                    self.stub = user_pb2_grpc.UserServiceStub(self.channel)
                    span.add_event("UsergRPCChannelEstablished")
                    span.set_status(Status(StatusCode.OK))
                except Exception as e:
                    logger.error(f"Failed to establish gRPC channel to {self.target}: {e}", exc_info=True)
                    span.record_exception(e)
                    span.set_status(Status(StatusCode.ERROR, "UserChannelEstablishmentFailed"))
                    # 채널 생성 실패 시, self.channel/stub을 None으로 유지하거나, 예외를 다시 발생
                    self.channel = None
                    self.stub = None
                    raise # 호출부에서 채널 문제를 인지하도록 함

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=5), # 재시도 간격 조정
        retry=retry_if_exception_type((RpcError, ConnectionError, asyncio.TimeoutError)), # TimeoutError도 재시도
        before_sleep=log_user_client_retry_attempt, # 재시도 전 콜백
        reraise=True
    )
    async def get_user(self, user_id: str) -> user_pb2.UserResponse: # 반환 타입 명시
        # 이 스팬은 get_user 작업 전체(재시도 포함)를 감싼다.
        # GrpcInstrumentorClient가 각 gRPC 시도에 대한 자식 스팬을 생성한다.
        with tracer.start_as_current_span("UserClient.get_user") as span: # 스팬 이름 변경
            span.set_attribute(SpanAttributes.RPC_SYSTEM, "grpc") # 이 작업이 gRPC 호출임을 명시
            span.set_attribute("app.user_id", user_id) # 애플리케이션 특정 속성
            # span.set_attribute("service.target", self.target) # _ensure_channel 스팬 또는 자동 계측된 스팬에 기록됨
            
            try:
                await self._ensure_channel()
                if not self.stub: # _ensure_channel 실패 시 stub이 None일 수 있음
                    logger.error(f"User service stub not available for get_user {user_id}. Channel might be down.")
                    span.set_status(Status(StatusCode.ERROR, "UserServiceStubNotAvailable"))
                    raise HTTPException(status_code=503, detail="User service connection not available.")

                logger.info(f"Attempting to get user with ID: {user_id} from {self.target}")
                span.add_event("UserFetchAttempt")
                
                request = user_pb2.UserRequest(user_id=user_id)
                # GrpcInstrumentorClient가 `self.stub.GetUser` 호출을 자동으로 계측
                response = await self.stub.GetUser(request, timeout=self.default_timeout)
                
                # 응답 정보 추적 (PII 주의 - 여기서는 예시로 포함)
                if response and response.user_id: # user_id 존재 여부로 성공 판단 강화
                    span.set_attribute("app.response.user.name", response.name)
                    # span.set_attribute("app.response.user.age", response.age) # 나이 등 민감 정보는 선택적
                    span.set_attribute("app.response.user.occupation", response.occupation)
                    # span.set_attribute("app.response.user.learning", response.learning) # 학습 정보도 선택적
                    span.set_attribute("app.user.found", True)
                    logger.info(f"Successfully got user: {user_id}")
                    span.set_status(Status(StatusCode.OK))
                    return response
                else: # 응답은 왔으나, 유효한 user_id가 없는 경우 (서비스 로직상 '못 찾음')
                    logger.warning(f"User {user_id} not found by service (empty or invalid response).")
                    span.set_attribute("app.user.found", False)
                    span.set_status(Status(StatusCode.ERROR, "UserNotFoundByServiceLogic"))
                    raise HTTPException(status_code=404, detail="User not found by service logic")

            # asyncio.TimeoutError는 tenacity @retry에서 처리됨
            except grpc.RpcError as e:
                logger.error(f"gRPC RpcError in get_user for user_id {user_id}: {e.code()} - {e.details()}", exc_info=True)
                span.record_exception(e)
                span.set_attribute(SpanAttributes.RPC_GRPC_STATUS_CODE, e.code().value[0])
                span.set_status(Status(StatusCode.ERROR, f"gRPC RpcError: {e.details()}"))
                
                if e.code() == grpc.StatusCode.NOT_FOUND:
                    raise HTTPException(status_code=404, detail=f"User {user_id} not found (gRPC NOT_FOUND)")
                elif e.code() == grpc.StatusCode.UNAVAILABLE:
                    raise HTTPException(status_code=503, detail="User service unavailable")
                elif e.code() == grpc.StatusCode.DEADLINE_EXCEEDED:
                     raise HTTPException(status_code=504, detail="User service request timed out (gRPC DEADLINE_EXCEEDED)")
                else:
                    raise HTTPException(status_code=500, detail=f"gRPC call to user service failed: {e.details()}")
            except Exception as e:
                logger.error(f"Unexpected error in get_user for user_id {user_id}: {e}", exc_info=True)
                span.record_exception(e)
                span.set_status(Status(StatusCode.ERROR, "UnexpectedErrorInGetUser"))
                if not isinstance(e, HTTPException): # 이미 HTTPException이 아니면 500으로 변환
                    raise HTTPException(status_code=500, detail=f"An unexpected error occurred: {str(e)}")
                raise

    async def close(self):
        if self.channel:
            with tracer.start_as_current_span("gRPC.channel.close_user_service") as span:
                span.set_attribute(SpanAttributes.RPC_SYSTEM, "grpc")
                span.set_attribute(SpanAttributes.NET_PEER_NAME, self.host)
                span.set_attribute(SpanAttributes.NET_PEER_PORT, self.port)
                try:
                    logger.info(f"Closing gRPC channel to {self.target}")
                    await self.channel.close()
                    self.channel = None
                    self.stub = None
                    span.add_event("UsergRPCChannelClosed")
                    span.set_status(Status(StatusCode.OK))
                except Exception as e:
                    logger.error(f"Error closing UserClient gRPC channel: {e}", exc_info=True)
                    span.record_exception(e)
                    span.set_status(Status(StatusCode.ERROR, "UserChannelCloseFailed"))