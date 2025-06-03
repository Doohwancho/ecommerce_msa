from concurrent import futures
import grpc
import logging
from app.services.user import UserService as UserManager
import user_pb2 
import user_pb2_grpc
from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode
import asyncio

# 로깅 설정 (basicConfig removed, setup_logging in main.py handles this)
# logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class UserService(user_pb2_grpc.UserServiceServicer):
    def __init__(self):
        self.user_manager = UserManager()
        self.tracer = trace.get_tracer(__name__) # Tracer per instance or module
        logger.info("UserService gRPC servicer initialized.", extra={"service_name": "UserServiceGRPC"})

    async def GetUser(self, request, context):
        # It's common to get tracer at module level or once in __init__
        # tracer = trace.get_tracer(__name__) # This can be moved to __init__ or module level
        with self.tracer.start_as_current_span("grpc.server.get_user") as span:
            user_id_req = request.user_id
            span.set_attribute("app.user.id_requested", user_id_req)
            logger.info("GetUser gRPC request received.", extra={"requested_user_id": user_id_req, "method": "GetUser"})

            try:
                # The original code had a nested try-except for ObjectId conversion.
                # It's better to handle it as part of the main try-catch or specifically if needed.
                # For now, assuming get_user_by_id handles potential ObjectId conversion errors gracefully
                # or they fall into the generic Exception catch.
                user = await self.user_manager.get_user_by_id(user_id_req)
                                
                if not user:
                    logger.warning("User not found by ID in gRPC GetUser.", extra={"requested_user_id": user_id_req, "found": False})
                    span.set_attribute("app.user.found", False)
                    span.set_status(Status(StatusCode.ERROR, f"User {user_id_req} not found"))
                    context.set_code(grpc.StatusCode.NOT_FOUND)
                    context.set_details(f"User {user_id_req} not found")
                    return user_pb2.UserResponse()
                
                span.set_attribute("app.user.found", True)
                span.set_attributes({
                    "app.user.name": user.name,
                    "app.user.age": user.age,
                    # Add other relevant, non-sensitive attributes
                })
                
                logger.info("User found and retrieved successfully in gRPC GetUser.", extra={"user_id": str(user.id), "user_name": user.name})
                span.set_status(Status(StatusCode.OK))
                
                return user_pb2.UserResponse(
                    user_id=str(user.id),
                    name=user.name,
                    age=user.age,
                    occupation=user.occupation,
                    learning=user.learning
                )
            except ValueError as ve: # Catching specific error like invalid ID format if get_user_by_id raises it
                logger.error("Invalid user ID format in gRPC GetUser.", 
                             extra={"requested_user_id": user_id_req, "error": str(ve)}, 
                             exc_info=True)
                span.set_status(Status(StatusCode.ERROR, f"Invalid user ID format: {str(ve)}"))
                span.record_exception(ve)
                context.set_code(grpc.StatusCode.INVALID_ARGUMENT)
                context.set_details(f"Invalid user ID format: {str(ve)}")
                return user_pb2.UserResponse()
            except Exception as e:
                logger.error("Generic error in gRPC GetUser.", 
                             extra={"requested_user_id": user_id_req, "error": str(e)}, 
                             exc_info=True)
                span.set_status(Status(StatusCode.ERROR, str(e)))
                span.record_exception(e)
                context.set_code(grpc.StatusCode.INTERNAL)
                context.set_details(f"Internal server error: {str(e)}")
                return user_pb2.UserResponse()

async def serve():
    server = grpc.aio.server()
    user_pb2_grpc.add_UserServiceServicer_to_server(
        UserService(), server
    )
    server.add_insecure_port('[::]:50051')
    logger.info("Starting gRPC server.", extra={"port": 50051, "address": "[::]:50051"})
    await server.start()
    logger.info("gRPC server started successfully and listening.", extra={"port": 50051})
    try:
        await server.wait_for_termination()
    except asyncio.CancelledError:
        logger.info("gRPC server shutting down due to cancellation.", extra={"shutdown_event": "cancelled"})
    except Exception as e:
        logger.error("gRPC server encountered an error during wait_for_termination.", extra={"error": str(e)}, exc_info=True)
    finally:
        logger.info("gRPC server has terminated.", extra={"shutdown_event": "terminated"}) 