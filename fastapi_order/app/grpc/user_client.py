import grpc
import user_pb2
import user_pb2_grpc
from fastapi import HTTPException
import os
import logging
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
from grpc import RpcError
import asyncio
from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# gRPC channel options
CHANNEL_OPTIONS = [
    ('grpc.max_send_message_length', 50 * 1024 * 1024),  # 50MB
    ('grpc.max_receive_message_length', 50 * 1024 * 1024),  # 50MB
    ('grpc.keepalive_time_ms', 10000),  # 10 seconds
    ('grpc.keepalive_timeout_ms', 5000),  # 5 seconds
    ('grpc.keepalive_permit_without_calls', True),
    ('grpc.http2.min_ping_interval_without_data_ms', 5000),  # 5 seconds
    ('grpc.dns_min_time_between_resolutions_ms', 10000),  # 10 seconds
]

class UserClient:
    def __init__(self):
        self.host = os.getenv("USER_SERVICE_HOST", "user-service")
        self.port = os.getenv("USER_SERVICE_GRPC_PORT", "50051")
        self.target = f"{self.host}:{self.port}"
        logger.info(f"Initialized UserClient with target: {self.target}")
        self.channel = None
        self.stub = None
        self.default_timeout = 5  # 기본 timeout 5초
        self.tracer = trace.get_tracer(__name__)

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=4, max=10),
        retry=retry_if_exception_type((RpcError, ConnectionError)),
        reraise=True
    )
    async def get_user(self, user_id: str):
        with self.tracer.start_as_current_span("grpc.client.get_user") as span:
            try:
                # 요청 정보 추적
                span.set_attribute("user.id", user_id)
                span.set_attribute("service.target", self.target)
                
                if not self.channel or self.channel._channel.is_closed():
                    logger.info(f"Creating gRPC channel to {self.target}")
                    self.channel = grpc.aio.insecure_channel(
                        self.target,
                        options=CHANNEL_OPTIONS
                    )
                    self.stub = user_pb2_grpc.UserServiceStub(self.channel)
                    span.set_attribute("channel.created", True)

                logger.info(f"Attempting to get user with ID: {user_id}")
                
                async with asyncio.timeout(self.default_timeout):
                    request = user_pb2.UserRequest(user_id=user_id)
                    response = await self.stub.GetUser(request)
                    
                    # 응답 정보 추적
                    if response:
                        span.set_attributes({
                            "user.name": response.name,
                            "user.age": response.age,
                            "user.occupation": response.occupation,
                            "user.learning": response.learning
                        })
                    
                    logger.info(f"Successfully got user: {response}")
                    span.set_status(Status(StatusCode.OK))
                    return response
                    
            except asyncio.TimeoutError:
                span.set_status(Status(StatusCode.ERROR, "User service timeout"))
                logger.error(f"Timeout while getting user {user_id}")
                raise HTTPException(status_code=504, detail="User service timeout")
            except grpc.RpcError as e:
                span.set_status(Status(StatusCode.ERROR, str(e)))
                logger.error(f"gRPC error while getting user: {e}")
                if e.code() == grpc.StatusCode.NOT_FOUND:
                    raise HTTPException(status_code=404, detail="User not found")
                elif e.code() == grpc.StatusCode.UNAVAILABLE:
                    logger.error(f"User service is unavailable. Target: {self.target}")
                    raise HTTPException(status_code=503, detail="User service unavailable")
                else:
                    logger.error(f"Unexpected gRPC error: {e}")
                    raise HTTPException(status_code=500, detail="Internal server error")
            except Exception as e:
                span.set_status(Status(StatusCode.ERROR, str(e)))
                logger.error(f"Unexpected error while getting user: {e}")
                raise HTTPException(status_code=500, detail="Internal server error")

    async def close(self):
        if self.channel:
            logger.info("Closing gRPC channel")
            await self.channel.close()
            self.channel = None
            self.stub = None 