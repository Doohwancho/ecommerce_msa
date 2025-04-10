from fastapi import APIRouter, HTTPException
from app.models.user import User 
from app.config.database import user_collection
from app.config.logging import logger
from bson.objectid import ObjectId

router = APIRouter()

@router.post("/create_user/")
async def create_user(user: User):
    try:
        logger.info(f"Creating user: {user.Name}")
        result = user_collection.insert_one(user.dict())
        logger.info(f"User created successfully: {user.Name}")
        return {"message": "User created successfully", "id": str(result.inserted_id)}
    except Exception as e:
        logger.error(f"Error creating user {user.Name}: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/get_users/{name}")
async def get_user(name: str):
    try:
        logger.info(f"Fetching user: {name}")
        user = user_collection.find_one({"Name": name})
        if user:
            # ObjectId를 문자열로 변환
            user["_id"] = str(user["_id"])
            logger.info(f"User found: {name}")
            return user
        logger.warning(f"User not found: {name}")
        raise HTTPException(status_code=404, detail="User not found")
    except Exception as e:
        logger.error(f"Error fetching user {name}: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))
