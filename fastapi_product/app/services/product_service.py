from typing import List, Optional
from bson import ObjectId
from datetime import datetime, timezone
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.config.elasticsearch import elasticsearch_config
from app.schemas.product import ProductCreate, ProductUpdate, ProductResponse, ProductsExistResponse, ProductInventoryResponse
from app.config.database import get_product_collection, get_mysql_db, get_read_mysql_db, get_read_db, get_write_db
from app.models.product import Product as MySQLProduct
from app.config.logging import logger

class ProductService:
    def __init__(self):
        self.product_collection = None
        self.write_db = None
        self.read_db = None
    
    async def _get_collection(self):
        if self.product_collection is None:
            self.product_collection = await get_product_collection()
            if self.product_collection is None:
                raise Exception("MongoDB connection failed")
        return self.product_collection
    
    async def _get_write_db(self):
        if self.write_db is None:
            self.write_db = await get_mysql_db()  # Primary DB에 연결
            if self.write_db is None:
                raise Exception("MySQL primary connection failed")
        return self.write_db
    
    async def _get_read_db(self):
        if self.read_db is None:
            self.read_db = await get_read_mysql_db()  # Secondary DB에 연결
            if self.read_db is None:
                raise Exception("MySQL secondary connection failed")
        return self.read_db
    
    async def _get_es(self):
        return await elasticsearch_config.get_client()
    
    async def create_product(self, product: ProductCreate) -> ProductResponse:
        """새로운 제품 생성 (MongoDB와 MySQL에 동시 저장)"""
        try:
            # MongoDB에 저장
            product_dict = product.dict()
            current_time = datetime.now().isoformat()
            product_dict["created_at"] = current_time
            product_dict["updated_at"] = current_time
            
            # MongoDB에서는 stock 정보 제외
            if "stock" in product_dict:
                del product_dict["stock"]
            
            collection = await self._get_collection()
            result = await collection.insert_one(product_dict)
            product_id = str(result.inserted_id)  # MongoDB가 생성한 _id를 사용
            
            # MySQL에 저장 (FOR UPDATE로 잠금)
            db = await self._get_write_db()  # Write DB 사용
            stmt = select(MySQLProduct).where(MySQLProduct.product_id == product_id).with_for_update()
            result = await db.execute(stmt)
            existing_product = result.scalar_one_or_none()
            
            if existing_product:
                raise Exception(f"Product {product_id} already exists in MySQL")
            
            mysql_product = MySQLProduct(
                product_id=product_id,
                title=product.title,
                description=product.description,
                price=int(product.price.amount),  # Float를 Integer로 변환
                stock=product.stock,
                stock_reserved=0,  # 초기 예약 재고는 0
                created_at=datetime.now()
                # updated_at은 자동으로 업데이트됨
            )
            db.add(mysql_product)
            await db.commit()
            await db.refresh(mysql_product)
            
            logger.info(f"Product created in both MongoDB and MySQL: {product_id}")
            
            # 응답 생성 시 stock 정보 제외
            response_data = product_dict.copy()
            response_data["product_id"] = product_id  # MongoDB의 _id를 product_id로 사용
            return ProductResponse(**response_data)
        except Exception as e:
            logger.error(f"Error creating product: {str(e)}")
            raise e
    
    async def get_product(self, product_id: str) -> Optional[ProductResponse]:
        """제품 ID로 제품 조회 (Elasticsearch 먼저 시도, 없으면 MongoDB 조회)"""
        try:
            # 1. Elasticsearch에서 먼저 조회
            es = await self._get_es()
            try:
                es_response = await es.get(
                    index="my_db.products",
                    id=product_id
                )
                if es_response and es_response.get('found', False):
                    product_data = es_response['_source']
                    # product_id 필드를 명시적으로 추가
                    product_data['product_id'] = product_id
                    
                    # variants 데이터 처리
                    if 'variants' in product_data:
                        variants = []
                        for variant in product_data['variants']:
                            variant_data = {
                                "attributes": variant.get("attributes", {}),
                                "color": variant.get("color"),
                                "id": variant.get("id"),
                                "inventory": variant.get("inventory", 0),
                                "price": {
                                    "amount": variant.get("price", {}).get("amount", 0.0),
                                    "currency": variant.get("price", {}).get("currency", "USD")
                                },
                                "sku": variant.get("sku"),
                                "storage": variant.get("storage")
                            }
                            variants.append(variant_data)
                        product_data['variants'] = variants
                    
                    return ProductResponse(**product_data)
            except Exception as es_error:
                logger.warning(f"Product not found in Elasticsearch: {product_id}, error: {str(es_error)}")
            
            # 2. Elasticsearch에 없는 경우 MongoDB에서 조회
            collection = await self._get_collection()
            try:
                product = await collection.find_one({"_id": ObjectId(product_id)})
            except:
                product = None
                
            if product:
                # ObjectId를 문자열로 변환
                product["product_id"] = str(product["_id"])
                del product["_id"]
                
                # MongoDB에서 가져온 데이터를 ProductResponse 형식에 맞게 변환
                response_data = {
                    "product_id": product["product_id"],
                    "title": product.get("title", ""),
                    "description": product.get("description", ""),
                    "brand": product.get("brand"),
                    "model": product.get("model"),
                    "sku": product.get("sku"),
                    "upc": product.get("upc"),
                    "color": product.get("color"),
                    "category_ids": product.get("category_ids", []),
                    "primary_category_id": product.get("primary_category_id"),
                    "category_breadcrumbs": product.get("category_breadcrumbs"),
                    "price": {
                        "amount": product.get("price", {}).get("amount", 0.0),
                        "currency": product.get("price", {}).get("currency", "USD")
                    },
                    "weight": product.get("weight"),
                    "dimensions": product.get("dimensions"),
                    "attributes": product.get("attributes"),
                    "variants": product.get("variants"),
                    "images": product.get("images"),
                    "created_at": product.get("created_at")
                }
                
                logger.info(f"Product found in MongoDB: {product_id}")
                return ProductResponse(**response_data)
            
            logger.warning(f"Product not found: {product_id}")
            return None
        except Exception as e:
            logger.error(f"Error getting product: {str(e)}")
            raise e
    
    async def check_availability(self, product_id: str, quantity: int) -> tuple[bool, Optional[ProductResponse]]:
        """
        제품이 지정된 수량만큼 재고가 있는지 확인합니다.
        가용 재고 = 총 재고 - 예약된 재고
        
        Args:
            product_id: 제품 ID
            quantity: 확인할 수량
            
        Returns:
            tuple: (가용성 여부, 제품 정보)
        """
        try:
            product = await self.get_product(product_id)
            if not product:
                return False, None
            
            # 가용 재고 = 총 재고 - 예약된 재고
            available_stock = product.stock - product.stock_reserved
            is_available = available_stock >= quantity
            
            logger.info(f"Product {product_id} availability check: requested={quantity}, available={available_stock}, result={is_available}")
            return is_available, product
        except Exception as e:
            logger.error(f"제품 재고 확인 중 오류 발생: {e}")
            return False, None

    async def check_and_reserve_inventory(self, product_id: str, quantity: int) -> tuple[bool, str]:
        """
        제품 재고 확인과 예약을 한 번에 수행합니다.
        MySQL에서만 재고를 관리합니다.
        
        Args:
            product_id: 제품 ID
            quantity: 요청 수량
            
        Returns:
            tuple: (성공 여부, 메시지)
        """
        try:
            db = await self._get_write_db()  # Write DB 사용
            
            # MySQL에서 제품 조회 (FOR UPDATE로 잠금)
            stmt = select(MySQLProduct).where(MySQLProduct.product_id == product_id).with_for_update()
            result = await db.execute(stmt)
            mysql_product = result.scalar_one_or_none()
            
            if not mysql_product:
                return False, f"Product {product_id} not found"
            
            # 가용 재고 확인
            available_stock = mysql_product.stock - mysql_product.stock_reserved
            if available_stock < quantity:
                return False, f"Insufficient stock: requested {quantity}, available {available_stock}"
            
            # 재고 예약
            mysql_product.stock_reserved += quantity
            await db.commit()
            
            logger.info(f"Successfully checked and reserved {quantity} items for product {product_id}")
            return True, f"Successfully reserved {quantity} items"
                
        except Exception as e:
            logger.error(f"Error checking and reserving inventory: {str(e)}")
            return False, str(e)

    async def update_product(self, product_id: str, product_update: ProductUpdate) -> Optional[ProductResponse]:
        """제품 업데이트"""
        try:
            collection = await self._get_collection()
            # 현재 제품 가져오기
            current_product = await collection.find_one({"_id": ObjectId(product_id)})
            if not current_product:
                logger.warning(f"Product not found for update: {product_id}")
                return None
            
            # 업데이트할 필드
            update_data = {k: v for k, v in product_update.dict(exclude_unset=True).items()}

            # updated_at
            update_data["updated_at"] = datetime.now(timezone.utc).isoformat()
            
            # 업데이트 수행
            await collection.update_one(
                {"_id": ObjectId(product_id)},
                {"$set": update_data}
            )
            
            # 업데이트된 제품 반환
            updated_product = await collection.find_one({"_id": ObjectId(product_id)})
            if updated_product:
                updated_product["product_id"] = str(updated_product["_id"])
                del updated_product["_id"]
            
            logger.info(f"Product updated: {product_id}")
            return ProductResponse(**updated_product)
        except Exception as e:
            logger.error(f"Error updating product: {str(e)}")
            raise e
    
    async def delete_product(self, product_id: str) -> bool:
        """제품 삭제"""
        try:
            collection = await self._get_collection()
            result = await collection.delete_one({"_id": ObjectId(product_id)})
            if result.deleted_count:
                logger.info(f"Product deleted: {product_id}")
                return True
            logger.warning(f"Product not found for deletion: {product_id}")
            return False
        except Exception as e:
            logger.error(f"Error deleting product: {str(e)}")
            raise e
    
    async def get_products(self, skip: int = 0, limit: int = 100) -> List[ProductResponse]:
        """모든 제품 조회 (Elasticsearch 사용)"""
        try:
            es = await self._get_es()
            query = {
                "query": {
                    "match_all": {}
                },
                "from": skip,
                "size": limit
            }
            
            response = await es.search(
                index="my_db.products",
                body=query
            )
            
            products = []
            for hit in response['hits']['hits']:
                product_data = hit['_source']
                
                # variants 데이터 처리
                variants = []
                for variant in product_data.get("variants", []):
                    variant_data = {
                        "attributes": variant.get("attributes", {}),
                        "color": variant.get("color"),
                        "id": variant.get("id"),
                        "inventory": variant.get("inventory", 0),
                        "price": {
                            "amount": variant.get("price", {}).get("amount", 0.0),
                            "currency": variant.get("price", {}).get("currency", "USD")
                        },
                        "sku": variant.get("sku"),
                        "storage": variant.get("storage")  # storage 필드가 없으면 None으로 설정
                    }
                    variants.append(variant_data)
                
                # Elasticsearch에서 가져온 데이터를 ProductResponse 형식에 맞게 변환
                response_data = {
                    "product_id": product_data.get("product_id", str(hit['_id'])),
                    "title": product_data.get("title", ""),
                    "description": product_data.get("description", ""),
                    "brand": product_data.get("brand"),
                    "model": product_data.get("model"),
                    "sku": product_data.get("sku"),
                    "upc": product_data.get("upc"),
                    "color": product_data.get("color"),
                    "category_ids": product_data.get("category_ids", []),
                    "primary_category_id": product_data.get("primary_category_id"),
                    "category_breadcrumbs": product_data.get("category_breadcrumbs"),
                    "price": {
                        "amount": product_data.get("price", {}).get("amount", 0.0),
                        "currency": product_data.get("price", {}).get("currency", "USD")
                    },
                    "weight": product_data.get("weight"),
                    "dimensions": product_data.get("dimensions"),
                    "attributes": product_data.get("attributes"),
                    "variants": variants,
                    "images": product_data.get("images"),
                    "created_at": product_data.get("created_at")
                }
                
                products.append(ProductResponse(**response_data))
            
            return products
        except Exception as e:
            logger.error(f"Error getting products from Elasticsearch: {str(e)}")
            # Elasticsearch 실패 시 MongoDB로 폴백
            try:
                collection = await self._get_collection()
                products = []
                async for product in collection.find().skip(skip).limit(limit):
                    if "_id" in product:
                        product["_id"] = str(product["_id"])
                    
                    # variants 데이터 처리
                    variants = []
                    for variant in product.get("variants", []):
                        variant_data = {
                            "attributes": variant.get("attributes", {}),
                            "color": variant.get("color"),
                            "id": variant.get("id"),
                            "inventory": variant.get("inventory", 0),
                            "price": {
                                "amount": variant.get("price", {}).get("amount", 0.0),
                                "currency": variant.get("price", {}).get("currency", "USD")
                            },
                            "sku": variant.get("sku"),
                            "storage": variant.get("storage")  # storage 필드가 없으면 None으로 설정
                        }
                        variants.append(variant_data)
                    
                    response_data = {
                        "product_id": product.get("product_id", str(product["_id"])),
                        "title": product.get("title", ""),
                        "description": product.get("description", ""),
                        "brand": product.get("brand"),
                        "model": product.get("model"),
                        "sku": product.get("sku"),
                        "upc": product.get("upc"),
                        "color": product.get("color"),
                        "category_ids": product.get("category_ids", []),
                        "primary_category_id": product.get("primary_category_id"),
                        "category_breadcrumbs": product.get("category_breadcrumbs"),
                        "price": {
                            "amount": product.get("price", {}).get("amount", 0.0),
                            "currency": product.get("price", {}).get("currency", "USD")
                        },
                        "weight": product.get("weight"),
                        "dimensions": product.get("dimensions"),
                        "attributes": product.get("attributes"),
                        "variants": variants,
                        "images": product.get("images"),
                        "created_at": product.get("created_at")
                    }
                    
                    products.append(ProductResponse(**response_data))
                return products
            except Exception as mongo_error:
                logger.error(f"Error getting products from MongoDB: {str(mongo_error)}")
                raise e
    
    async def check_products_exist(self, product_ids: List[str]) -> ProductsExistResponse:
        """여러 제품의 존재 여부 확인"""
        try:
            collection = await self._get_collection()
            existing_products = []
            missing_products = []
            
            for product_id in product_ids:
                try:
                    product = await collection.find_one({"_id": ObjectId(product_id)})
                    if product:
                        existing_products.append(product_id)
                    else:
                        missing_products.append(product_id)
                except:
                    missing_products.append(product_id)
            
            return ProductsExistResponse(
                existing_ids=existing_products,
                missing_ids=missing_products
            )
        except Exception as e:
            logger.error(f"Error checking products existence: {str(e)}")
            raise e

    async def reserve_inventory(self, product_id: str, quantity: int) -> bool:
        """
        주문 생성 시 재고를 예약합니다.
        
        Args:
            product_id: 제품 ID
            quantity: 예약할 수량
            
        Returns:
            bool: 예약 성공 여부
        """
        try:
            db = await self._get_write_db()  # Write DB 사용
            
            # MySQL에서 제품 조회 (FOR UPDATE로 잠금)
            stmt = select(MySQLProduct).where(MySQLProduct.product_id == product_id).with_for_update()
            result = await db.execute(stmt)
            mysql_product = result.scalar_one_or_none()
            
            if not mysql_product:
                logger.warning(f"Product {product_id} not found in MySQL")
                return False
            
            # 가용 재고 확인 (총 재고 - 예약 재고)
            available_stock = mysql_product.stock - mysql_product.stock_reserved
            if available_stock < quantity:
                logger.warning(f"Insufficient available stock for product {product_id}: requested {quantity}, available {available_stock}")
                return False
            
            # 재고 예약 (stock_reserved 증가)
            mysql_product.stock_reserved += quantity
            await db.commit()
            
            logger.info(f"Successfully reserved {quantity} items for product {product_id}")
            return True
            
        except Exception as e:
            logger.error(f"Error reserving inventory for product {product_id}: {str(e)}")
            return False

    async def release_inventory(self, product_id: str, quantity: int) -> bool:
        """
        주문 취소 시 예약된 재고를 해제합니다 (SAGA 롤백).
        MySQL에서만 재고를 관리합니다.
        
        Args:
            product_id: 제품 ID
            quantity: 해제할 수량
            
        Returns:
            bool: 해제 성공 여부
        """
        try:
            db = await self._get_write_db()  # Write DB 사용
            
            # MySQL에서 제품 조회 (FOR UPDATE로 잠금)
            stmt = select(MySQLProduct).where(MySQLProduct.product_id == product_id).with_for_update()
            result = await db.execute(stmt)
            mysql_product = result.scalar_one_or_none()
            
            if not mysql_product:
                logger.warning(f"Product {product_id} not found in MySQL")
                return False
                
            # 예약된 재고가 충분한지 확인
            if mysql_product.stock_reserved < quantity:
                logger.warning(f"Cannot release more than reserved: product {product_id}, requested {quantity}, reserved {mysql_product.stock_reserved}")
                return False
                
            # MySQL 재고 예약 업데이트 (stock_reserved 감소)
            mysql_product.stock_reserved -= quantity
            await db.commit()
                
            logger.info(f"Successfully released {quantity} reserved items for product {product_id}")
            return True
                
        except Exception as e:
            logger.error(f"Error releasing inventory for product {product_id}: {str(e)}")
            return False

    async def confirm_inventory(self, product_id: str, quantity: int) -> bool:
        """
        주문 확정, 성공 시 재고를 차감합니다.
        stock과 stock_reserved 모두에서 quantity를 차감합니다.
        
        Args:
            product_id: 제품 ID
            quantity: 확정할 수량
            
        Returns:
            bool: 확정 성공 여부
        """
        try:
            db = await self._get_write_db()  # Write DB 사용
            
            # MySQL에서 제품 조회 (FOR UPDATE로 잠금)
            stmt = select(MySQLProduct).where(MySQLProduct.product_id == product_id).with_for_update()
            result = await db.execute(stmt)
            mysql_product = result.scalar_one_or_none()
            
            if not mysql_product:
                logger.warning(f"Product {product_id} not found in MySQL")
                return False
            
            # 예약된 재고와 실제 재고 확인
            if mysql_product.stock_reserved < quantity or mysql_product.stock < quantity:
                logger.warning(f"Cannot confirm inventory: product {product_id}, requested {quantity}, reserved {mysql_product.stock_reserved}, total {mysql_product.stock}")
                return False
            
            # 재고 확정 (stock과 stock_reserved 모두 감소)
            mysql_product.stock -= quantity
            mysql_product.stock_reserved -= quantity
            await db.commit()
            
            logger.info(f"Successfully confirmed {quantity} items for product {product_id}")
            return True
            
        except Exception as e:
            logger.error(f"Error confirming inventory for product {product_id}: {str(e)}")
            return False

    async def get_product_inventory(self, product_id: str) -> Optional[ProductInventoryResponse]:
        """제품의 재고 정보 조회"""
        try:
            db = await self._get_read_db()  # Read DB 사용
            mysql_product = await db.get(MySQLProduct, product_id)
            if not mysql_product:
                logger.warning(f"Product {product_id} not found in MySQL")
                return None
            
            return ProductInventoryResponse(
                product_id=product_id,
                stock=mysql_product.stock,
                stock_reserved=mysql_product.stock_reserved,
                available_stock=mysql_product.stock - mysql_product.stock_reserved
            )
        except Exception as e:
            logger.error(f"Error getting product inventory {product_id}: {str(e)}")
            raise e

    async def get_product_mongodb_only(self, product_id: str) -> Optional[ProductResponse]:
        """MongoDB에서만 제품 ID로 제품 조회 (benchmark test용)"""
        try:
            collection = await self._get_collection()
            try:
                product = await collection.find_one({"_id": ObjectId(product_id)})
            except:
                product = None
            
            if product:
                # ObjectId를 문자열로 변환
                product["product_id"] = str(product["_id"])
                del product["_id"]
                
                # MongoDB에서 가져온 데이터를 ProductResponse 형식에 맞게 변환
                response_data = {
                    "product_id": product["product_id"],
                    "title": product.get("title", ""),
                    "description": product.get("description", ""),
                    "brand": product.get("brand"),
                    "model": product.get("model"),
                    "sku": product.get("sku"),
                    "upc": product.get("upc"),
                    "color": product.get("color"),
                    "category_ids": product.get("category_ids", []),
                    "primary_category_id": product.get("primary_category_id"),
                    "category_breadcrumbs": product.get("category_breadcrumbs"),
                    "price": {
                        "amount": product.get("price", {}).get("amount", 0.0),
                        "currency": product.get("price", {}).get("currency", "USD")
                    },
                    "weight": product.get("weight"),
                    "dimensions": product.get("dimensions"),
                    "attributes": product.get("attributes"),
                    "variants": product.get("variants"),
                    "images": product.get("images"),
                    "created_at": product.get("created_at")
                }
                
                return ProductResponse(**response_data)
            
            logger.warning(f"Product not found in MongoDB: {product_id}")
            return None
        except Exception as e:
            logger.error(f"Error getting product from MongoDB: {str(e)}")
            raise e