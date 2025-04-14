from typing import List, Optional, Dict, Any
from bson import ObjectId
from datetime import datetime
from app.schemas.product import ProductCreate, ProductUpdate, ProductResponse, ProductsExistResponse
from app.config.database import get_product_collection
from app.config.logging import logger

class ProductService:
    def __init__(self):
        self.product_collection = None
    
    async def _get_collection(self):
        if self.product_collection is None:
            self.product_collection = await get_product_collection()
            if self.product_collection is None:
                raise Exception("Database connection failed")
        return self.product_collection
    
    async def create_product(self, product: ProductCreate) -> ProductResponse:
        """새로운 제품 생성"""
        try:
            product_dict = product.dict()
            
            # 제품 ID 생성
            product_id = f"P{ObjectId()}"
            product_dict["product_id"] = product_id
            
            # 타임스탬프 추가
            current_time = datetime.now().isoformat()
            product_dict["created_at"] = current_time
            product_dict["updated_at"] = current_time
            
            # MongoDB에 저장
            collection = await self._get_collection()
            await collection.insert_one(product_dict)
            
            logger.info(f"Product created: {product_id}")
            # 삽입된 문서 반환
            return ProductResponse(**product_dict)
        except Exception as e:
            logger.error(f"Error creating product: {str(e)}")
            raise e
    
    async def get_product(self, product_id: str) -> Optional[ProductResponse]:
        """제품 ID로 제품 조회"""
        try:
            collection = await self._get_collection()
            product = await collection.find_one({"product_id": product_id})
            if product:
                # ObjectId를 문자열로 변환
                if "_id" in product:
                    product["_id"] = str(product["_id"])
                logger.info(f"Product found: {product_id}")
                return ProductResponse(**product)
            logger.warning(f"Product not found: {product_id}")
            return None
        except Exception as e:
            logger.error(f"Error getting product {product_id}: {str(e)}")
            raise e
    
    async def check_availability(self, product_id: str, quantity: int) -> bool:
        """
        제품이 지정된 수량만큼 재고가 있는지 확인합니다.
        """
        try:
            product = await self.get_product(product_id)
            if not product:
                return False
            return product.stock >= quantity
        except Exception as e:
            logger.error(f"제품 재고 확인 중 오류 발생: {e}")
            return False

    async def update_product(self, product_id: str, product_update: ProductUpdate) -> Optional[ProductResponse]:
        """제품 업데이트"""
        try:
            collection = await self._get_collection()
            # 현재 제품 가져오기
            current_product = await collection.find_one({"product_id": product_id})
            if not current_product:
                logger.warning(f"Product not found for update: {product_id}")
                return None
            
            # 업데이트할 필드
            update_data = {k: v for k, v in product_update.dict(exclude_unset=True).items()}
            update_data["updated_at"] = datetime.now().isoformat()
            
            # 업데이트 수행
            await collection.update_one(
                {"product_id": product_id},
                {"$set": update_data}
            )
            
            # 업데이트된 제품 반환
            updated_product = await collection.find_one({"product_id": product_id})
            if "_id" in updated_product:
                updated_product["_id"] = str(updated_product["_id"])
            
            logger.info(f"Product updated: {product_id}")
            return ProductResponse(**updated_product)
        except Exception as e:
            logger.error(f"Error updating product {product_id}: {str(e)}")
            raise e
    
    async def delete_product(self, product_id: str) -> bool:
        """제품 삭제"""
        try:
            collection = await self._get_collection()
            result = await collection.delete_one({"product_id": product_id})
            if result.deleted_count:
                logger.info(f"Product deleted: {product_id}")
                return True
            logger.warning(f"Product not found for deletion: {product_id}")
            return False
        except Exception as e:
            logger.error(f"Error deleting product {product_id}: {str(e)}")
            raise e
    
    async def get_products(self, skip: int = 0, limit: int = 100) -> List[ProductResponse]:
        """모든 제품 조회"""
        try:
            collection = await self._get_collection()
            products = []
            async for product in collection.find().skip(skip).limit(limit):
                if "_id" in product:
                    product["_id"] = str(product["_id"])
                products.append(ProductResponse(**product))
            return products
        except Exception as e:
            logger.error(f"Error getting products: {str(e)}")
            raise e
    
    async def check_products_exist(self, product_ids: List[str]) -> ProductsExistResponse:
        """여러 제품의 존재 여부 확인"""
        try:
            collection = await self._get_collection()
            existing_products = []
            missing_products = []
            
            for product_id in product_ids:
                product = await collection.find_one({"product_id": product_id})
                if product:
                    existing_products.append(product_id)
                else:
                    missing_products.append(product_id)
            
            return ProductsExistResponse(
                existing_products=existing_products,
                missing_products=missing_products
            )
        except Exception as e:
            logger.error(f"Error checking products existence: {str(e)}")
            raise e