from typing import List, Optional, Dict, Any
from bson import ObjectId
from datetime import datetime
from app.schemas.product import ProductCreate, ProductUpdate, ProductResponse, ProductsExistResponse
from app.config.database import product_collection
from app.config.logging import logger

class ProductService:
    def __init__(self):
        self.product_collection = product_collection
    
    def create_product(self, product: ProductCreate) -> ProductResponse:
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
            self.product_collection.insert_one(product_dict)
            
            logger.info(f"Product created: {product_id}")
            # 삽입된 문서 반환
            return ProductResponse(**product_dict)
        except Exception as e:
            logger.error(f"Error creating product: {str(e)}")
            raise e
    
    def get_product(self, product_id: str) -> Optional[ProductResponse]:
        """제품 ID로 제품 조회"""
        try:
            product = self.product_collection.find_one({"product_id": product_id})
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
    
    def update_product(self, product_id: str, product_update: ProductUpdate) -> Optional[ProductResponse]:
        """제품 업데이트"""
        try:
            # 현재 제품 가져오기
            current_product = self.product_collection.find_one({"product_id": product_id})
            if not current_product:
                logger.warning(f"Product not found for update: {product_id}")
                return None
            
            # 업데이트할 필드
            update_data = {k: v for k, v in product_update.dict(exclude_unset=True).items()}
            update_data["updated_at"] = datetime.now().isoformat()
            
            # 업데이트 수행
            self.product_collection.update_one(
                {"product_id": product_id},
                {"$set": update_data}
            )
            
            # 업데이트된 제품 반환
            updated_product = self.product_collection.find_one({"product_id": product_id})
            if "_id" in updated_product:
                updated_product["_id"] = str(updated_product["_id"])
            
            logger.info(f"Product updated: {product_id}")
            return ProductResponse(**updated_product)
        except Exception as e:
            logger.error(f"Error updating product {product_id}: {str(e)}")
            raise e
    
    def delete_product(self, product_id: str) -> bool:
        """제품 삭제"""
        try:
            result = self.product_collection.delete_one({"product_id": product_id})
            if result.deleted_count:
                logger.info(f"Product deleted: {product_id}")
                return True
            logger.warning(f"Product not found for deletion: {product_id}")
            return False
        except Exception as e:
            logger.error(f"Error deleting product {product_id}: {str(e)}")
            raise e
    
    def get_products(self, skip: int = 0, limit: int = 100) -> List[ProductResponse]:
        """모든 제품 목록 조회"""
        try:
            products = list(self.product_collection.find().skip(skip).limit(limit))
            for product in products:
                if "_id" in product:
                    product["_id"] = str(product["_id"])
            
            logger.info(f"Retrieved {len(products)} products")
            return [ProductResponse(**product) for product in products]
        except Exception as e:
            logger.error(f"Error getting products: {str(e)}")
            raise e
    
    def check_products_exist(self, product_ids: List[str]) -> ProductsExistResponse:
        """여러 상품이 존재하는지 확인"""
        try:
            # 존재하는 제품 ID만 찾기
            existing_products = self.product_collection.find(
                {"product_id": {"$in": product_ids}},
                {"product_id": 1}
            )
            
            existing_ids = [p["product_id"] for p in existing_products]
            missing_ids = [pid for pid in product_ids if pid not in existing_ids]
            
            logger.info(f"Checked existence of {len(product_ids)} products. Found: {len(existing_ids)}, Missing: {len(missing_ids)}")
            return ProductsExistResponse(
                existing_ids=existing_ids,
                missing_ids=missing_ids
            )
        except Exception as e:
            logger.error(f"Error checking products existence: {str(e)}")
            raise e