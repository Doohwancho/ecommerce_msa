from fastapi import APIRouter, HTTPException
from typing import List
from app.models.user import UserCreate, UserResponse
from app.services.user import UserService

router = APIRouter()

@router.post("/", response_model=UserResponse)
async def create_user(user: UserCreate):
    return await UserService.create_user(user)

@router.get("/", response_model=List[UserResponse])
async def get_users():
    return await UserService.get_users()

@router.get("/id/{user_id}", response_model=UserResponse)
async def get_user_by_id(user_id: str):
    try:
        user = await UserService.get_user_by_id(user_id)
        if not user:
            raise HTTPException(status_code=404, detail=f"User with ID {user_id} not found")
        return user
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.get("/{username}", response_model=UserResponse)
async def get_user(username: str):
    user = await UserService.get_user(username)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return user