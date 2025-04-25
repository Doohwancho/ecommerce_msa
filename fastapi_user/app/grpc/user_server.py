from concurrent import futures
import grpc
import logging
from app.services.user import UserService as UserManager
import user_pb2 
import user_pb2_grpc

# 로깅 설정
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class UserService(user_pb2_grpc.UserServiceServicer):
    def __init__(self):
        self.user_manager = UserManager()
        logger.info("UserService initialized")

    async def GetUser(self, request, context):
        try:
            logger.info(f"GetUser request received for user_id: {request.user_id}")
            try:
                user = await self.user_manager.get_user_by_id(request.user_id)
            except Exception as e:
                logger.error(f"Error converting user_id to ObjectId: {str(e)}")
                context.set_code(grpc.StatusCode.INVALID_ARGUMENT)
                context.set_details(f"Invalid user ID format: {str(e)}")
                return user_pb2.UserResponse()
                
            if not user:
                logger.warning(f"User not found: {request.user_id}")
                context.set_code(grpc.StatusCode.NOT_FOUND)
                context.set_details(f"User {request.user_id} not found")
                return user_pb2.UserResponse()
            
            logger.info(f"User found: {user}")
            return user_pb2.UserResponse(
                user_id=str(user.id),
                name=user.name,
                age=user.age,
                occupation=user.occupation,
                learning=user.learning
            )
        except Exception as e:
            logger.error(f"Error in GetUser: {str(e)}")
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