import httpx
from fastapi import HTTPException
import os

class UserClient:
    def __init__(self):
        self.base_url = os.getenv("USER_SERVICE_URL", "http://user-service:8000")
        self.timeout = 5.0
    
    async def get_user(self, user_id: str):
        """사용자 정보 조회"""
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            try:
                response = await client.get(f"{self.base_url}/api/users/{user_id}")
                if response.status_code == 404:
                    raise HTTPException(status_code=404, detail=f"User {user_id} not found")
                response.raise_for_status()
                return response.json()
            except httpx.RequestError:
                raise HTTPException(status_code=503, detail="User service unavailable")
            except httpx.HTTPStatusError as e:
                raise HTTPException(status_code=e.response.status_code, detail=str(e))