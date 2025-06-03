from app.models.user import UserCreate, UserResponse
from app.config.database import get_write_users_collection, get_read_users_collection
# from motor.core import AgnosticCollection # Not used directly in this snippet
from bson import ObjectId
import logging

# OpenTelemetry trace API for interacting with current span
from opentelemetry import trace
# OpenTelemetry semantic conventions for attribute naming (optional but good practice)
from opentelemetry.semconv.trace import SpanAttributes

logger = logging.getLogger(__name__)

class UserService:
    @staticmethod
    async def create_user(user: UserCreate) -> UserResponse:
        """
        새로운 사용자 생성 (Write DB 사용)
        """
        # Get the current span (created by the FastAPI endpoint's tracer)
        current_span = trace.get_current_span()

        users_collection = await get_write_users_collection()
        if users_collection is None:
            log_message = "Database write connection failed during user creation"
            logger.error(log_message, extra={"service_event": "db_connection_failed", "operation": "create_user"})
            current_span.set_status(trace.Status(trace.StatusCode.ERROR, log_message))
            current_span.set_attribute("db.connection.available", False)
            raise Exception("Database write connection failed") # Or a more specific custom exception

        current_span.set_attribute("db.collection", users_collection.name) # Semantic convention for collection name
        current_span.set_attribute("app.user.name", user.name) # Custom attribute

        user_dict = user.dict()
        try:
            # PymongoInstrumentor will create a child span for this insert_one operation.
            # That child span will have attributes like db.system, db.statement, etc.
            result = await users_collection.insert_one(user_dict)
            user_id = result.inserted_id

            current_span.set_attribute("app.user.id", str(user_id)) # Add created user ID to current span
            logger.info(f"User created successfully.", extra={"user_name": user.name, "user_id": str(user_id)})
            return UserResponse(id=str(user_id), **user_dict)
        except Exception as e:
            log_message = f"Error creating user '{user.name}'"
            logger.error(log_message, exc_info=True, extra={"user_name": user.name, "error_message": str(e)})
            current_span.record_exception(e)
            current_span.set_status(trace.Status(trace.StatusCode.ERROR, log_message))
            raise # Re-raise the exception to be handled by the endpoint

    @staticmethod
    async def get_users() -> list[UserResponse]:
        """
        모든 사용자 조회 (Read DB 사용)
        """
        current_span = trace.get_current_span()
        users_collection = await get_read_users_collection()
        if users_collection is None:
            log_message = "Database read connection failed when getting all users"
            logger.error(log_message, extra={"service_event": "db_connection_failed", "operation": "get_users"})
            current_span.set_status(trace.Status(trace.StatusCode.ERROR, log_message))
            current_span.set_attribute("db.connection.available", False)
            raise Exception("Database read connection failed")

        current_span.set_attribute("db.collection", users_collection.name)

        try:
            users = []
            # PymongoInstrumentor will trace the find() operation and iterations.
            async for user_doc in users_collection.find():
                users.append(UserResponse(id=str(user_doc["_id"]), **user_doc))

            current_span.set_attribute("app.users.count", len(users))
            logger.info(f"Retrieved users.", extra={"user_count": len(users)})
            return users
        except Exception as e:
            log_message = f"Error retrieving all users"
            logger.error(log_message, exc_info=True, extra={"error_message": str(e)})
            current_span.record_exception(e)
            current_span.set_status(trace.Status(trace.StatusCode.ERROR, log_message))
            raise

    @staticmethod
    async def get_user(username: str) -> UserResponse | None: # Use | None for type hint
        """
        사용자 이름으로 사용자 조회 (Read DB 사용)
        """
        current_span = trace.get_current_span()
        current_span.set_attribute("app.user.search.username", username)

        users_collection = await get_read_users_collection()
        if users_collection is None:
            log_message = f"Database read connection failed when getting user by name '{username}'"
            logger.error(log_message, extra={"service_event": "db_connection_failed", "operation": "get_user_by_name", "username": username})
            current_span.set_status(trace.Status(trace.StatusCode.ERROR, log_message))
            raise Exception("Database read connection failed")

        current_span.set_attribute("db.collection", users_collection.name)

        try:
            # PymongoInstrumentor will trace find_one.
            user_doc = await users_collection.find_one({"name": username})
            if user_doc:
                logger.info(f"User found by username.", extra={"username": username, "user_id": str(user_doc['_id'])})
                current_span.set_attribute("app.user.found", True)
                current_span.set_attribute("app.user.id", str(user_doc['_id']))
                return UserResponse(id=str(user_doc["_id"]), **user_doc)

            logger.warning(f"User not found by username.", extra={"username": username})
            current_span.set_attribute("app.user.found", False)
            # Not an error for the span if "not found" is an expected outcome
            # current_span.set_status(trace.Status(trace.StatusCode.OK, "User not found"))
            return None
        except Exception as e:
            log_message = f"Error retrieving user by name '{username}'"
            logger.error(log_message, exc_info=True, extra={"username": username, "error_message": str(e)})
            current_span.record_exception(e)
            current_span.set_status(trace.Status(trace.StatusCode.ERROR, log_message))
            raise

    @staticmethod
    async def get_user_by_id(user_id: str) -> UserResponse | None:
        """
        사용자 ID로 사용자 조회 (Read DB 사용)
        """
        current_span = trace.get_current_span()
        current_span.set_attribute("app.user.search.id", user_id)

        users_collection = await get_read_users_collection()
        if users_collection is None:
            log_message = f"Database read connection failed when getting user by ID '{user_id}'"
            logger.error(log_message, extra={"service_event": "db_connection_failed", "operation": "get_user_by_id", "user_id": user_id})
            current_span.set_status(trace.Status(trace.StatusCode.ERROR, log_message))
            raise Exception("Database read connection failed")

        current_span.set_attribute("db.collection", users_collection.name)

        try:
            # PymongoInstrumentor will trace find_one.
            user_doc = await users_collection.find_one({"_id": ObjectId(user_id)}) # Ensure ObjectId conversion is safe
            if user_doc:
                logger.info(f"User found by ID.", extra={"user_id": user_id})
                current_span.set_attribute("app.user.found", True)
                return UserResponse(id=str(user_doc["_id"]), **user_doc)

            logger.warning(f"User not found by ID.", extra={"user_id": user_id})
            current_span.set_attribute("app.user.found", False)
            return None
        except Exception as e: # Could be BSONError from ObjectId, or DB error
            log_message = f"Error retrieving user by ID '{user_id}'"
            logger.error(log_message, exc_info=True, extra={"user_id": user_id, "error_message": str(e)})
            current_span.record_exception(e)
            current_span.set_status(trace.Status(trace.StatusCode.ERROR, log_message))
            # Distinguish between "invalid ID format" and other errors if necessary
            # if isinstance(e, bson.errors.InvalidId):
            # raise HTTPException(status_code=400, detail="Invalid user ID format")
            raise