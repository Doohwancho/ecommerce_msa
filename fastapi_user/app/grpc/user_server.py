from concurrent import futures
import grpc
import logging
from app.services.user import UserService as UserManager
import user_pb2 
import user_pb2_grpc
from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode

# 로깅 설정
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class UserService(user_pb2_grpc.UserServiceServicer):
    def __init__(self):
        self.user_manager = UserManager()
        self.tracer = trace.get_tracer(__name__)
        logger.info("UserService initialized")

    async def GetUser(self, request, context):
        with self.tracer.start_as_current_span("grpc.server.get_user") as span:
            try:
                # 요청 정보 추적
                span.set_attribute("user.id", request.user_id)
                logger.info(f"GetUser request received for user_id: {request.user_id}")

                try:
                    user = await self.user_manager.get_user_by_id(request.user_id)
                except Exception as e:
                    logger.error(f"Error converting user_id to ObjectId: {str(e)}")
                    span.set_status(Status(StatusCode.ERROR, f"Invalid user ID format: {str(e)}"))
                    context.set_code(grpc.StatusCode.INVALID_ARGUMENT)
                    context.set_details(f"Invalid user ID format: {str(e)}")
                    return user_pb2.UserResponse()
                    
                if not user:
                    logger.warning(f"User not found: {request.user_id}")
                    span.set_status(Status(StatusCode.ERROR, f"User {request.user_id} not found"))
                    context.set_code(grpc.StatusCode.NOT_FOUND)
                    context.set_details(f"User {request.user_id} not found")
                    return user_pb2.UserResponse()
                
                # 사용자 정보 추적 (민감한 정보는 제외)
                span.set_attributes({
                    "user.name": user.name,
                    "user.age": user.age,
                    "user.occupation": user.occupation,
                    "user.learning": user.learning
                })
                
                logger.info(f"User found: {user}")
                span.set_status(Status(StatusCode.OK))
                
                return user_pb2.UserResponse(
                    user_id=str(user.id),
                    name=user.name,
                    age=user.age,
                    occupation=user.occupation,
                    learning=user.learning
                )
            except Exception as e:
                logger.error(f"Error in GetUser: {str(e)}")
                span.set_status(Status(StatusCode.ERROR, str(e)))
                context.set_code(grpc.StatusCode.INTERNAL)
                context.set_details(str(e))
                return user_pb2.UserResponse()

async def serve():
    server = grpc.aio.server()
    user_pb2_grpc.add_UserServiceServicer_to_server(
        UserService(), server
    )
    server.add_insecure_port('[::]:50051')
    logger.info("Starting gRPC server on port 50051")
    await server.start()
    logger.info("gRPC server started successfully")
    await server.wait_for_termination() 