from fastapi import APIRouter, HTTPException
from typing import List
from app.models.user import UserCreate, UserResponse
from app.services.user import UserService
from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode

router = APIRouter()
tracer = trace.get_tracer(__name__)

@router.post("/", response_model=UserResponse)
async def create_user(user: UserCreate):
    with tracer.start_as_current_span("create_user") as span:
        try:
            span.set_attribute("user.name", user.name)
            span.set_attribute("user.age", user.age)
            span.set_attribute("user.occupation", user.occupation)
            span.set_attribute("user.learning", user.learning)
            result = await UserService.create_user(user)
            span.set_status(Status(StatusCode.OK))
            return result
        except Exception as e:
            span.set_status(Status(StatusCode.ERROR, str(e)))
            raise

@router.get("/", response_model=List[UserResponse])
async def get_users():
    with tracer.start_as_current_span("get_all_users") as span:
        try:
            users = await UserService.get_users()
            span.set_attribute("users.count", len(users))
            span.set_status(Status(StatusCode.OK))
            return users
        except Exception as e:
            span.set_status(Status(StatusCode.ERROR, str(e)))
            raise

@router.get("/id/{user_id}", response_model=UserResponse)
async def get_user_by_id(user_id: str):
    with tracer.start_as_current_span("get_user_by_id") as span:
        try:
            span.set_attribute("user.id", user_id)
            user = await UserService.get_user_by_id(user_id)
            if not user:
                span.set_status(Status(StatusCode.ERROR, f"User with ID {user_id} not found"))
                raise HTTPException(status_code=404, detail=f"User with ID {user_id} not found")
            span.set_status(Status(StatusCode.OK))
            return user
        except HTTPException:
            raise
        except Exception as e:
            span.set_status(Status(StatusCode.ERROR, str(e)))
            raise HTTPException(status_code=400, detail=str(e))

@router.get("/{username}", response_model=UserResponse)
async def get_user(username: str):
    with tracer.start_as_current_span("get_user_by_username") as span:
        try:
            span.set_attribute("user.username", username)
            user = await UserService.get_user(username)
            if not user:
                span.set_status(Status(StatusCode.ERROR, f"User {username} not found"))
                raise HTTPException(status_code=404, detail="User not found")
            span.set_status(Status(StatusCode.OK))
            return user
        except HTTPException:
            raise
        except Exception as e:
            span.set_status(Status(StatusCode.ERROR, str(e)))
            raise HTTPException(status_code=400, detail=str(e))