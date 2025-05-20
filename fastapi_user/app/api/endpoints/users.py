from fastapi import APIRouter, HTTPException
from typing import List
from app.models.user import UserCreate, UserResponse
from app.services.user import UserService
from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode
# For semantic attribute names, it's good practice:
from opentelemetry.semconv.trace import SpanAttributes

router = APIRouter()
# Consistent tracer naming
tracer = trace.get_tracer("app.api.user_router") # Or use __name__ if you prefer: trace.get_tracer(__name__)

@router.post("/", response_model=UserResponse, summary="Create a new user")
async def create_user(user: UserCreate):
    # Using a more descriptive span name, e.g., "endpoint.<operation>"
    with tracer.start_as_current_span("endpoint.create_user") as span:
        # Standard HTTP attributes
        span.set_attribute(SpanAttributes.HTTP_METHOD, "POST")
        span.set_attribute(SpanAttributes.HTTP_ROUTE, "/") # Or your specific route template if more complex

        # Application-specific attributes for the request
        span.set_attribute("app.user.request.name", user.name)
        span.set_attribute("app.user.request.age", user.age)
        span.set_attribute("app.user.request.occupation", user.occupation)
        span.set_attribute("app.user.request.learning", user.learning)

        try:
            result = await UserService.create_user(user)

            # Add response attributes to the span
            span.set_attribute("app.user.response.id", result.id)
            span.set_status(Status(StatusCode.OK))
            return result
        except HTTPException as he:
            # Exception was already an HTTPException, likely from service or validation
            span.set_attribute(SpanAttributes.HTTP_STATUS_CODE, he.status_code)
            # For 4xx/5xx errors, OTel defines span status as ERROR
            span.set_status(Status(StatusCode.ERROR, description=f"HTTPException: {he.detail}"))
            span.record_exception(he) # Records the exception with stack trace
            raise
        except Exception as e:
            # Catch any other unexpected errors
            span.set_attribute(SpanAttributes.HTTP_STATUS_CODE, 500)
            span.set_status(Status(StatusCode.ERROR, description=f"Unhandled exception: {str(e)}"))
            span.record_exception(e)
            # Re-raise as a standard HTTPException for the client
            raise HTTPException(status_code=500, detail="Internal server error")

@router.get("/", response_model=List[UserResponse], summary="Get all users")
async def get_users():
    with tracer.start_as_current_span("endpoint.get_all_users") as span:
        span.set_attribute(SpanAttributes.HTTP_METHOD, "GET")
        span.set_attribute(SpanAttributes.HTTP_ROUTE, "/")

        try:
            users = await UserService.get_users()
            span.set_attribute("app.users.response.count", len(users))
            span.set_status(Status(StatusCode.OK))
            return users
        except HTTPException as he: # If UserService raises an HTTPException
            span.set_attribute(SpanAttributes.HTTP_STATUS_CODE, he.status_code)
            span.set_status(Status(StatusCode.ERROR, description=f"HTTPException: {he.detail}"))
            span.record_exception(he)
            raise
        except Exception as e:
            span.set_attribute(SpanAttributes.HTTP_STATUS_CODE, 500)
            span.set_status(Status(StatusCode.ERROR, description=f"Unhandled exception: {str(e)}"))
            span.record_exception(e)
            raise HTTPException(status_code=500, detail="Internal server error")

@router.get("/id/{user_id}", response_model=UserResponse, summary="Get user by ID")
async def get_user_by_id(user_id: str):
    with tracer.start_as_current_span("endpoint.get_user_by_id") as span:
        span.set_attribute(SpanAttributes.HTTP_METHOD, "GET")
        span.set_attribute(SpanAttributes.HTTP_ROUTE, "/id/{user_id}") # Use the route template
        span.set_attribute("app.user.request.id", user_id)

        try:
            user = await UserService.get_user_by_id(user_id)
            if not user:
                # For "Not Found", set appropriate HTTP status code and span status
                span.set_attribute(SpanAttributes.HTTP_STATUS_CODE, 404)
                span.set_status(Status(StatusCode.ERROR, description=f"User with ID {user_id} not found"))
                # Create an HTTPException to be recorded and raised
                not_found_exception = HTTPException(status_code=404, detail=f"User with ID {user_id} not found")
                span.record_exception(not_found_exception) # Record it on the span
                raise not_found_exception

            span.set_attribute("app.user.response.name", user.name) # Example response attribute
            span.set_status(Status(StatusCode.OK))
            return user
        except HTTPException as he:
            # If it's not the 404 we raised above, or if it came from UserService
            if span.status.status_code == StatusCode.UNSET: # Only set if not already set (e.g., by the 404 logic)
                span.set_attribute(SpanAttributes.HTTP_STATUS_CODE, he.status_code)
                span.set_status(Status(StatusCode.ERROR, description=f"HTTPException: {he.detail}"))
            # Always record, even if status was set (like the 404 we created)
            # If it's the same exception, it's okay; if different, this captures the new one.
            if not hasattr(he, '_otel_recorded'): # Avoid double recording if already done by 404 block
                 span.record_exception(he)
            raise
        except Exception as e: # Handles other errors, e.g., ObjectId conversion in service layer
            span.set_attribute(SpanAttributes.HTTP_STATUS_CODE, 500) # Default to 500
            # Check if it's a known type of error that should be a 400
            if "Invalid user ID format" in str(e) or isinstance(e, ValueError): # Example check
                 span.set_attribute(SpanAttributes.HTTP_STATUS_CODE, 400)
                 span.set_status(Status(StatusCode.ERROR, description=f"Invalid request: {str(e)}"))
                 span.record_exception(e)
                 raise HTTPException(status_code=400, detail=str(e))
            else:
                 span.set_status(Status(StatusCode.ERROR, description=f"Unhandled exception: {str(e)}"))
                 span.record_exception(e)
                 raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/{username}", response_model=UserResponse, summary="Get user by username")
async def get_user_by_username(username: str): # Changed function name for clarity from `get_user`
    with tracer.start_as_current_span("endpoint.get_user_by_username") as span:
        span.set_attribute(SpanAttributes.HTTP_METHOD, "GET")
        span.set_attribute(SpanAttributes.HTTP_ROUTE, "/{username}")
        span.set_attribute("app.user.request.username", username)

        try:
            user = await UserService.get_user(username) # Assuming UserService.get_user takes username
            if not user:
                span.set_attribute(SpanAttributes.HTTP_STATUS_CODE, 404)
                span.set_status(Status(StatusCode.ERROR, description=f"User '{username}' not found"))
                not_found_exception = HTTPException(status_code=404, detail=f"User '{username}' not found")
                span.record_exception(not_found_exception)
                raise not_found_exception

            span.set_attribute("app.user.response.id", user.id) # Example response attribute
            span.set_status(Status(StatusCode.OK))
            return user
        except HTTPException as he:
            if span.status.status_code == StatusCode.UNSET:
                span.set_attribute(SpanAttributes.HTTP_STATUS_CODE, he.status_code)
                span.set_status(Status(StatusCode.ERROR, description=f"HTTPException: {he.detail}"))
            if not hasattr(he, '_otel_recorded'):
                 span.record_exception(he)
            raise
        except Exception as e:
            span.set_attribute(SpanAttributes.HTTP_STATUS_CODE, 500)
            span.set_status(Status(StatusCode.ERROR, description=f"Unhandled exception: {str(e)}"))
            span.record_exception(e)
            raise HTTPException(status_code=500, detail="Internal server error")