from typing import List, Optional, Dict, Any
from bson import ObjectId
from datetime import datetime
from app.schemas.product import ProductCreate, ProductUpdate, ProductResponse
from pymongo.collection import Collection

class ProductService:
    def __init__(self, product_collection: Collection):
        self.product_collection = product_collection
    
    def create_product(self, product: ProductCreate) -> ProductResponse:
        """새로운 제품 생성"""
        product_dict = product.dict()
        
        # 제품 ID 생성 (원하는 방식으로 변경 가능)
        product_id = f"P{ObjectId()}"
        product_dict["product_id"] = product_id
        
        # 타임스탬프 추가
        current_time = datetime.now().isoformat()
        product_dict["created_at"] = current_time
        product_dict["updated_at"] = current_time
        
        # MongoDB에 저장
        self.product_collection.insert_one(product_dict)
        
        # 삽입된 문서 반환
        return ProductResponse(**product_dict)
    
    def get_product(self, product_id: str) -> Optional[ProductResponse]:
        """제품 ID로 제품 조회"""
        product = self.product_collection.find_one({"product_id": product_id})
        if product:
            # ObjectId를 문자열로 변환
            if "_id" in product:
                product["_id"] = str(product["_id"])
            return ProductResponse(**product)
        return None
    
    def update_product(self, product_id: str, product_update: ProductUpdate) -> Optional[ProductResponse]:
        """제품 정보 업데이트"""
        # 기존 제품이 있는지 확인
        existing_product = self.product_collection.find_one({"product_id": product_id})
        
        if not existing_product:
            return None
        
        # 업데이트할 필드 준비
        update_data = {k: v for k, v in product_update.dict(exclude_unset=True).items() if v is not None}
        update_data["updated_at"] = datetime.now().isoformat()
        
        # 문서 업데이트
        self.product_collection.update_one(
            {"product_id": product_id},
            {"$set": update_data}
        )
        
        # 업데이트된 문서 반환
        updated_product = self.product_collection.find_one({"product_id": product_id})
        if "_id" in updated_product:
            updated_product["_id"] = str(updated_product["_id"])
        
        return ProductResponse(**updated_product)
    
    def delete_product(self, product_id: str) -> bool:
        """제품 삭제"""
        result = self.product_collection.delete_one({"product_id": product_id})
        return result.deleted_count > 0
    
    def list_products(self, skip: int = 0, limit: int = 100) -> List[ProductResponse]:
        """제품 목록 조회"""
        products = list(self.product_collection.find().skip(skip).limit(limit))
        
        # ObjectId를 문자열로 변환
        for product in products:
            if "_id" in product:
                product["_id"] = str(product["_id"])
        
        return [ProductResponse(**product) for product in products]
    
    def find_products_by_category(self, category_id: int) -> List[ProductResponse]:
        """카테고리별 제품 조회"""
        products = list(self.product_collection.find({"category_ids": category_id}))
        
        # ObjectId를 문자열로 변환
        for product in products:
            if "_id" in product:
                product["_id"] = str(product["_id"])
        
        return [ProductResponse(**product) for product in products]
    
    def search_products(self, query: str) -> List[ProductResponse]:
        """제품 검색 (제목, 설명, 브랜드, 모델에서 검색)"""
        # 텍스트 인덱스가 생성되어 있어야 함
        products = list(self.product_collection.find({
            "$or": [
                {"title": {"$regex": query, "$options": "i"}},
                {"description": {"$regex": query, "$options": "i"}},
                {"brand": {"$regex": query, "$options": "i"}},
                {"model": {"$regex": query, "$options": "i"}}
            ]
        }))
        
        # ObjectId를 문자열로 변환
        for product in products:
            if "_id" in product:
                product["_id"] = str(product["_id"])
        
        return [ProductResponse(**product) for product in products]

