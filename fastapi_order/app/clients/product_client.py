import httpx
from fastapi import HTTPException
import os

class ProductClient:
    def __init__(self):
        self.base_url = os.getenv("PRODUCT_SERVICE_URL", "http://product-service:8000")
        self.timeout = 5.0  # 5초 타임아웃
    
    async def get_product(self, product_id: str):
        """상품 정보 조회"""
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            try:
                response = await client.get(f"{self.base_url}/api/products/{product_id}")
                if response.status_code == 404:
                    raise HTTPException(status_code=404, detail=f"Product {product_id} not found")
                response.raise_for_status()
                return response.json()
            except httpx.RequestError:
                raise HTTPException(status_code=503, detail="Product service unavailable")
            except httpx.HTTPStatusError as e:
                raise HTTPException(status_code=e.response.status_code, detail=str(e))
    
    async def check_products_exist(self, product_ids: list[str]):
        """여러 상품이 존재하는지 확인"""
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            try:
                response = await client.post(
                    f"{self.base_url}/api/products/check-exist",
                    json={"product_ids": product_ids}
                )
                response.raise_for_status()
                return response.json()
            except httpx.RequestError:
                raise HTTPException(status_code=503, detail="Product service unavailable")
            except httpx.HTTPStatusError as e:
                raise HTTPException(status_code=e.response.status_code, detail=str(e))