from typing import List, Optional, Dict, Any # Added Dict, Any for clarity
from bson import ObjectId
from datetime import datetime, timezone
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
import sqlalchemy.exc
import pymysql.err
import asyncio
import logging # Ensure this import is present

from app.config.elasticsearch import elasticsearch_config
from app.schemas.product import ProductCreate, ProductUpdate, ProductResponse, ProductsExistResponse, ProductInventoryResponse
from app.config.database import (
    get_write_product_collection, get_read_product_collection,
    get_mysql_db, get_read_mysql_db # Removed get_read_db, get_write_db if they are duplicates
)
from app.models.product import Product as MySQLProduct

# OTel imports
from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode
from opentelemetry.semconv.trace import SpanAttributes # For semantic conventions

logger = logging.getLogger(__name__) # Ensure logger is obtained correctly

class ProductService:
    def __init__(self):
        self.write_collection = None
        self.read_collection = None
        self.write_db_session: Optional[AsyncSession] = None # Type hint for clarity
        self.read_db_session: Optional[AsyncSession] = None  # Type hint for clarity
        # Initialize tracer for this service
        self.tracer = trace.get_tracer("app.services.ProductService", "0.1.0")

    async def _get_db_connection(self, getter_func, db_type: str, instance_role: str, span_name_suffix: str) -> Any:
        with self.tracer.start_as_current_span(f"service.product.get_connection.{span_name_suffix}") as conn_span:
            conn_span.set_attribute(SpanAttributes.DB_SYSTEM, db_type)
            conn_span.set_attribute("app.db.role", instance_role)
            try:
                connection = await getter_func()
                if connection is None:
                    error_msg = f"{db_type.capitalize()} {instance_role} connection failed: getter returned None"
                    logger.error("DB connection failed: getter returned None", extra={"db_type": db_type, "instance_role": instance_role}) 
                    conn_span.set_status(Status(StatusCode.ERROR, error_msg))
                    raise ConnectionError(error_msg)
                conn_span.set_status(Status(StatusCode.OK))
                return connection
            except Exception as e:
                logger.error("Failed to get connection", extra={"db_type": db_type, "instance_role": instance_role, "error": str(e)}, exc_info=True)
                conn_span.record_exception(e)
                conn_span.set_status(Status(StatusCode.ERROR, f"Failed to get {db_type} {instance_role} connection"))
                raise

    async def _get_write_collection(self):
        if self.write_collection is None:
            self.write_collection = await self._get_db_connection(
                get_write_product_collection, "mongodb", "write", "mongo_write_collection"
            )
        return self.write_collection

    async def _get_read_collection(self):
        if self.read_collection is None:
            self.read_collection = await self._get_db_connection(
                get_read_product_collection, "mongodb", "read", "mongo_read_collection"
            )
        return self.read_collection

    async def _get_write_db(self) -> AsyncSession:
        if self.write_db_session is None:
            self.write_db_session = await self._get_db_connection(
                get_mysql_db, "mysql", "write", "mysql_write_session"
            )
        return self.write_db_session

    async def _get_read_db(self) -> AsyncSession:
        if self.read_db_session is None:
            self.read_db_session = await self._get_db_connection(
                get_read_mysql_db, "mysql", "read", "mysql_read_session"
            )
        return self.read_db_session
    
    async def _get_es(self):
        return await self._get_db_connection(
            elasticsearch_config.get_client, "elasticsearch", "client", "es_client"
        )

    async def create_product(self, product: ProductCreate) -> ProductResponse:
        """새로운 제품 생성 (MongoDB와 MySQL에 동시 저장)"""
        with self.tracer.start_as_current_span("service.product.create_product") as span:
            span.set_attribute("app.product.request.title", product.title)
            span.set_attribute("app.product.request.sku", product.sku)
            span.set_attribute("app.product.request.brand", product.brand)
            product_id = None
            max_retries = 3
            retry_count = 0

            while retry_count < max_retries:
                try:
                    product_dict = product.dict()
                    current_time_iso = datetime.now(timezone.utc).isoformat()
                    product_dict["created_at"] = current_time_iso
                    product_dict["updated_at"] = current_time_iso
                    
                    mongo_payload = product_dict.copy()
                    if "stock" in mongo_payload:
                        del mongo_payload["stock"]
                    
                    span.add_event("Attempting MongoDB insert")
                    collection = await self._get_write_collection()
                    result = await collection.insert_one(mongo_payload)
                    product_id = str(result.inserted_id)
                    span.set_attribute("app.product.id", product_id)
                    span.set_attribute(SpanAttributes.DB_MONGODB_COLLECTION, collection.name)
                    logger.info("Product created in MongoDB.", extra={"product_id": product_id})
                    span.add_event("MongoDB insert successful", {"mongodb.document_id": product_id})

                    span.add_event("Attempting MySQL insert")
                    db = await self._get_write_db()
                    
                    async with db.begin():
                        stmt_check = select(MySQLProduct).where(MySQLProduct.product_id == product_id)
                        existing_result = await db.execute(stmt_check)
                        if existing_result.scalar_one_or_none():
                            error_msg = f"IntegrityError: Product with ID {product_id} (from MongoDB) already exists in MySQL."
                            logger.error("IntegrityError: Product already exists in MySQL (MongoDB ID).", extra={"product_id": product_id})
                            span.set_attribute("app.error.type", "data_integrity_violation")
                            span.set_status(Status(StatusCode.ERROR, error_msg))
                            raise ValueError(error_msg)

                        mysql_product = MySQLProduct(
                            product_id=product_id,
                            title=product.title,
                            description=product.description,
                            price=int(product.price.amount),
                            stock=product.stock,
                            stock_reserved=0,
                            created_at=datetime.now(timezone.utc)
                        )
                        db.add(mysql_product)

                    logger.info("Product created in MySQL.", extra={"product_id": product_id})
                    span.add_event("MySQL insert successful")
                    
                    span.set_status(Status(StatusCode.OK))
                    logger.info("Product created successfully in both MongoDB and MySQL.", extra={"product_id": product_id})
                    
                    response_data = mongo_payload.copy()
                    response_data["product_id"] = product_id
                    return ProductResponse(**response_data)

                except Exception as e:
                    error_message = f"Error creating product (ID attempt: {product_id if product_id else 'N/A'}): {str(e)}"
                    logger.error("Error creating product", extra={"product_id_attempt": product_id if product_id else 'N/A', "error": str(e)}, exc_info=True)
                    span.record_exception(e)
                    
                    if isinstance(e, (sqlalchemy.exc.OperationalError, pymysql.err.OperationalError)) and hasattr(e, 'orig') and e.orig.args[0] == 1205:
                        retry_count += 1
                        if retry_count < max_retries:
                            wait_time = 0.1 * (2 ** retry_count)
                            logger.warning("Lock timeout occurred, retrying", extra={"wait_time_seconds": wait_time, "attempt": retry_count, "max_retries": max_retries})
                            await asyncio.sleep(wait_time)
                            continue
                    
                    span.set_status(Status(StatusCode.ERROR, description=error_message))
                    raise

    async def get_product(self, product_id: str) -> Optional[ProductResponse]:
        """제품 ID로 제품 조회 (MongoDB만 사용, Elasticsearch 임시 비활성화)"""
        with self.tracer.start_as_current_span("service.product.get_product") as span:
            span.set_attribute("app.product.request.id", product_id)
            try:
                # Elasticsearch lookup (Temporarily commented out)
                # span.add_event("Attempting Elasticsearch lookup")
                # es = await self._get_es()
                # try:
                #     es_response = await es.get(index="my_db.products", id=product_id)
                #     if es_response and es_response.get('found', False):
                #         product_data = es_response['_source']
                #         product_data['product_id'] = product_id
                #         
                #         if 'variants' in product_data and isinstance(product_data['variants'], list):
                #             variants = []
                #             for var_item in product_data['variants']:
                #                 if isinstance(var_item, dict):
                #                     variants.append({
                #                         "attributes": var_item.get("attributes", {}),
                #                         "color": var_item.get("color"), "id": var_item.get("id"),
                #                         "inventory": var_item.get("inventory", 0),
                #                         "price": var_item.get("price", {"amount": 0.0, "currency": "USD"}),
                #                         "sku": var_item.get("sku"), "storage": var_item.get("storage")
                #                     })
                #             product_data['variants'] = variants
                #
                #         logger.info("Product found in Elasticsearch.", extra={"product_id": product_id})
                #         span.set_attribute("app.product.source", "elasticsearch")
                #         span.set_status(Status(StatusCode.OK))
                #         return ProductResponse(**product_data)
                # except Exception as es_error:
                #     logger.warning("Product not found or error in Elasticsearch.", extra={"product_id": product_id, "elasticsearch_error": str(es_error)}, exc_info=False)
                #     span.add_event("Elasticsearch_lookup_failed_or_not_found", {
                #         "elasticsearch.error_type": type(es_error).__name__,
                #         "elasticsearch.error_message": str(es_error)
                #     })

                span.add_event("Skipping Elasticsearch, going directly to MongoDB lookup")
                collection = await self._get_read_collection()
                product_mongo = await collection.find_one({"_id": ObjectId(product_id)})
                
                if product_mongo:
                    product_mongo["product_id"] = str(product_mongo["_id"])
                    del product_mongo["_id"]
                    response_data = {
                        key: product_mongo.get(key, ProductResponse.__fields__[key].default)
                        for key in ProductResponse.__fields__ if key in product_mongo or ProductResponse.__fields__[key].default is not None
                    }
                    response_data.update(product_mongo)
                    response_data["product_id"] = product_mongo["product_id"]

                    logger.info("Product found in MongoDB after ES miss.", extra={"product_id": product_id})
                    span.set_attribute("app.product.source", "mongodb")
                    span.set_status(Status(StatusCode.OK))
                    return ProductResponse(**response_data)

                logger.warning("Product not found in any source.", extra={"product_id": product_id})
                span.set_attribute("app.product.found", False)
                span.set_status(Status(StatusCode.ERROR, "Product not found in any source"))
                return None

            except Exception as e:
                error_message = f"Error getting product {product_id}: {str(e)}"
                logger.error("Error getting product", extra={"product_id": product_id, "error": str(e)}, exc_info=True)
                span.record_exception(e)
                span.set_status(Status(StatusCode.ERROR, description=error_message))
                raise

    async def _manage_inventory(
        self, operation_name: str, product_id: str, quantity: int,
        action: callable
    ) -> tuple[bool, str]:
        with self.tracer.start_as_current_span(f"service.product.inventory.{operation_name}") as span:
            span.set_attribute("app.product.id", product_id)
            span.set_attribute("app.request.quantity", quantity)
            span.set_attribute(SpanAttributes.DB_SYSTEM, "mysql")

            try:
                db = await self._get_write_db()
                
                span.add_event("Acquiring row lock in MySQL")
                stmt = select(MySQLProduct).where(MySQLProduct.product_id == product_id).with_for_update()
                result = await db.execute(stmt)
                mysql_product: Optional[MySQLProduct] = result.scalar_one_or_none()

                if not mysql_product:
                    message = f"Product {product_id} not found in MySQL for inventory operation."
                    logger.warning("Product not found in MySQL for inventory operation.", extra={"product_id": product_id})
                    span.set_attribute("app.product.found_in_mysql", False)
                    span.set_status(Status(StatusCode.ERROR, message))
                    return False, message

                span.set_attribute("app.product.found_in_mysql", True)
                span.set_attribute("app.mysql.initial_stock", mysql_product.stock)
                span.set_attribute("app.mysql.initial_stock_reserved", mysql_product.stock_reserved)

                success, message = await action(mysql_product, quantity)

                if success:
                    await db.commit()
                    await db.refresh(mysql_product)
                    span.set_attribute("app.mysql.final_stock", mysql_product.stock)
                    span.set_attribute("app.mysql.final_stock_reserved", mysql_product.stock_reserved)
                    span.set_status(Status(StatusCode.OK))
                    logger.info("Inventory operation SUCCESS", extra={"operation_name": operation_name, "product_id": product_id, "quantity": quantity, "details": message})
                else:
                    span.set_status(Status(StatusCode.ERROR, message))
                    logger.warning("Inventory operation FAILED", extra={"operation_name": operation_name, "product_id": product_id, "quantity": quantity, "details": message})
                    await db.rollback()

                return success, message
            except Exception as e:
                error_message = f"Error during inventory operation '{operation_name}' for product {product_id}: {str(e)}"
                logger.error("Error during inventory operation", extra={"operation_name": operation_name, "product_id": product_id, "error": str(e)}, exc_info=True)
                span.record_exception(e)
                span.set_status(Status(StatusCode.ERROR, description=error_message))
                if 'db' in locals() and db.in_transaction():
                    try:
                        await db.rollback()
                        span.add_event("Transaction rolled back due to exception")
                    except Exception as rb_exc:
                        logger.error("Failed to rollback transaction during error handling", extra={"rollback_error": str(rb_exc)}, exc_info=True)
                        span.record_exception(rb_exc)

                return False, f"Unexpected error: {str(e)}"

    async def check_availability(self, product_id: str, quantity: int) -> tuple[bool, Optional[ProductResponse]]:
        with self.tracer.start_as_current_span("service.product.check_availability") as span:
            span.set_attribute("app.product.id", product_id)
            span.set_attribute("app.request.quantity", quantity)
            try:
                inventory_info = await self.get_product_inventory(product_id)
                
                if not inventory_info:
                    logger.warning("Product inventory not found during availability check.", extra={"product_id": product_id})
                    span.set_attribute("app.product.found", False)
                    span.set_status(Status(StatusCode.ERROR, "Product inventory not found"))
                    return False, None

                span.set_attribute("app.product.found", True)
                is_available = inventory_info.available_stock >= quantity
                
                span.set_attribute("app.inventory.available_stock_checked", inventory_info.available_stock)
                span.set_attribute("app.inventory.is_available", is_available)
                span.set_status(Status(StatusCode.OK))
                logger.info("Product availability check", extra={"product_id": product_id, "requested_quantity": quantity, "available_stock": inventory_info.available_stock, "is_available": is_available})
                
                product_details = await self.get_product(product_id) if is_available else None
                return is_available, product_details

            except Exception as e:
                error_message = f"Error checking availability for product {product_id}: {e}"
                logger.error("Error checking availability for product", extra={"product_id": product_id, "error": str(e)}, exc_info=True)
                span.record_exception(e)
                span.set_status(Status(StatusCode.ERROR, description=error_message))
                return False, None


    async def check_and_reserve_inventory(self, product_id: str, quantity: int) -> tuple[bool, str]:
        async def action(mysql_product: MySQLProduct, qty: int):
            available_stock = mysql_product.stock - mysql_product.stock_reserved
            if available_stock < qty:
                return False, f"Insufficient stock: requested {qty}, available {available_stock}"
            mysql_product.stock_reserved += qty
            return True, f"Successfully reserved {qty} items"
        return await self._manage_inventory("check_and_reserve", product_id, quantity, action)

    async def reserve_inventory(self, product_id: str, quantity: int) -> bool:
        success, _ = await self.check_and_reserve_inventory(product_id, quantity)
        return success

    async def release_inventory(self, product_id: str, quantity: int) -> bool:
        async def action(mysql_product: MySQLProduct, qty: int):
            if mysql_product.stock_reserved < qty:
                return False, f"Cannot release more than reserved: requested {qty}, reserved {mysql_product.stock_reserved}"
            mysql_product.stock_reserved -= qty
            return True, f"Successfully released {qty} reserved items"
        success, _ = await self._manage_inventory("release", product_id, quantity, action)
        return success

    async def confirm_inventory(self, product_id: str, quantity: int) -> bool:
        async def action(mysql_product: MySQLProduct, qty: int):
            if mysql_product.stock_reserved < qty or mysql_product.stock < qty:
                return False, f"Cannot confirm: requested {qty}, reserved {mysql_product.stock_reserved}, total stock {mysql_product.stock}"
            mysql_product.stock -= qty
            mysql_product.stock_reserved -= qty
            return True, f"Successfully confirmed and deducted {qty} items"
        success, _ = await self._manage_inventory("confirm", product_id, quantity, action)
        return success

    async def get_product_inventory(self, product_id: str) -> Optional[ProductInventoryResponse]:
        """제품의 재고 정보 조회 (MySQL Read DB 사용)"""
        with self.tracer.start_as_current_span("service.product.get_product_inventory") as span:
            span.set_attribute("app.product.id", product_id)
            span.set_attribute(SpanAttributes.DB_SYSTEM, "mysql")
            try:
                db = await self._get_read_db()
                mysql_product = await db.get(MySQLProduct, product_id)

                if not mysql_product:
                    logger.warning("Product inventory not found in MySQL.", extra={"product_id": product_id})
                    span.set_attribute("app.product.found_in_mysql", False)
                    span.set_status(Status(StatusCode.ERROR, "Product inventory not found"))
                    return None
                
                span.set_attribute("app.product.found_in_mysql", True)
                span.set_attribute("app.inventory.stock", mysql_product.stock)
                span.set_attribute("app.inventory.stock_reserved", mysql_product.stock_reserved)
                available = mysql_product.stock - mysql_product.stock_reserved
                span.set_attribute("app.inventory.available_stock", available)
                span.set_status(Status(StatusCode.OK))
                
                return ProductInventoryResponse(
                    product_id=product_id,
                    stock=mysql_product.stock,
                    stock_reserved=mysql_product.stock_reserved,
                    available_stock=available
                )
            except Exception as e:
                error_message = f"Error getting product inventory for {product_id}: {str(e)}"
                logger.error("Error getting product inventory", extra={"product_id": product_id, "error": str(e)}, exc_info=True)
                span.record_exception(e)
                span.set_status(Status(StatusCode.ERROR, description=error_message))
                raise

    async def update_product(self, product_id: str, product_update: ProductUpdate) -> Optional[ProductResponse]:
        with self.tracer.start_as_current_span("service.product.update_product") as span:
            span.set_attribute("app.product.id", product_id)
            span.set_attribute("app.product.update_fields_count", len(product_update.dict(exclude_unset=True)))
            try:
                collection = await self._get_write_collection()
                span.set_attribute(SpanAttributes.DB_MONGODB_COLLECTION, collection.name)
                
                current_product = await collection.find_one({"_id": ObjectId(product_id)})
                if not current_product:
                    logger.warning("Product not found for update.", extra={"product_id": product_id})
                    span.set_attribute("app.product.found", False)
                    span.set_status(Status(StatusCode.ERROR, "Product not found for update"))
                    return None
                
                span.set_attribute("app.product.found", True)
                update_data = product_update.dict(exclude_unset=True)
                update_data["updated_at"] = datetime.now(timezone.utc).isoformat()

                await collection.update_one({"_id": ObjectId(product_id)}, {"$set": update_data})
                
                updated_product_mongo = await collection.find_one({"_id": ObjectId(product_id)})
                
                if updated_product_mongo:
                    updated_product_mongo["product_id"] = str(updated_product_mongo["_id"])
                    del updated_product_mongo["_id"]
                    logger.info("Product updated successfully.", extra={"product_id": product_id})
                    span.set_status(Status(StatusCode.OK))
                    return ProductResponse(**updated_product_mongo)
                else:
                    logger.error("Product disappeared after update attempt.", extra={"product_id": product_id})
                    span.set_status(Status(StatusCode.ERROR, f"Product {product_id} disappeared after update attempt."))
                    return None

            except Exception as e:
                error_message = f"Error updating product {product_id}: {str(e)}"
                logger.error("Error updating product", extra={"product_id": product_id, "error": str(e)}, exc_info=True)
                span.record_exception(e)
                span.set_status(Status(StatusCode.ERROR, description=error_message))
                raise

    async def delete_product(self, product_id: str) -> bool:
        with self.tracer.start_as_current_span("service.product.delete_product") as span:
            span.set_attribute("app.product.id", product_id)
            try:
                collection = await self._get_write_collection()
                span.set_attribute(SpanAttributes.DB_MONGODB_COLLECTION, collection.name)
                result = await collection.delete_one({"_id": ObjectId(product_id)})
                
                if result.deleted_count > 0:
                    logger.info("Product deleted successfully from MongoDB.", extra={"product_id": product_id, "deleted_count": result.deleted_count})
                    span.set_attribute("app.db.deleted_count", result.deleted_count)
                    span.set_status(Status(StatusCode.OK))
                    return True
                else:
                    logger.warning("Product not found in MongoDB for deletion.", extra={"product_id": product_id, "deleted_count": 0})
                    span.set_attribute("app.db.deleted_count", 0)
                    span.set_status(Status(StatusCode.ERROR, "Product not found for deletion"))
                    return False
            except Exception as e:
                error_message = f"Error deleting product {product_id}: {str(e)}"
                logger.error("Error deleting product", extra={"product_id": product_id, "error": str(e)}, exc_info=True)
                span.record_exception(e)
                span.set_status(Status(StatusCode.ERROR, description=error_message))
                raise

    async def get_products(self, skip: int = 0, limit: int = 100) -> List[ProductResponse]:
        """모든 제품 조회 (Elasticsearch 우선, 실패 시 MongoDB 폴백)"""
        with self.tracer.start_as_current_span("service.product.get_products_list") as span:
            span.set_attribute("app.pagination.skip", skip)
            span.set_attribute("app.pagination.limit", limit)
            products_response_list = []
            try:
                span.add_event("Attempting Elasticsearch search for product list")
                es = await self._get_es()
                es_query = {"query": {"match_all": {}}, "from": skip, "size": limit}
                response = await es.search(index="my_db.products", body=es_query)
                
                for hit in response.get('hits', {}).get('hits', []):
                    product_data = hit['_source']
                    product_data['product_id'] = hit['_id']
                    if 'variants' in product_data and isinstance(product_data['variants'], list):
                        variants = []
                        for var_item in product_data['variants']:
                            if isinstance(var_item, dict):
                                variants.append({
                                    "attributes": var_item.get("attributes", {}),
                                    "color": var_item.get("color"), "id": var_item.get("id"),
                                    "inventory": var_item.get("inventory", 0),
                                    "price": var_item.get("price", {"amount": 0.0, "currency": "USD"}),
                                    "sku": var_item.get("sku"), "storage": var_item.get("storage")
                                })
                        product_data['variants'] = variants
                    products_response_list.append(ProductResponse(**product_data))
                
                logger.info("Retrieved products from Elasticsearch.", extra={"count": len(products_response_list), "skip": skip, "limit": limit})
                span.set_attribute("app.products.source", "elasticsearch")
                span.set_attribute("app.products.retrieved_count", len(products_response_list))
                span.set_status(Status(StatusCode.OK))
                return products_response_list

            except Exception as es_error:
                logger.error("Error getting products from Elasticsearch.", extra={"skip": skip, "limit": limit, "error": str(es_error)}, exc_info=True)
                span.record_exception(es_error)
                span.add_event("Elasticsearch_search_failed_falling_back_to_mongodb", {
                    "elasticsearch.error_type": type(es_error).__name__,
                    "elasticsearch.error_message": str(es_error)
                })

                try:
                    collection = await self._get_read_collection()
                    span.set_attribute(SpanAttributes.DB_MONGODB_COLLECTION, collection.name)
                    mongo_cursor = collection.find().skip(skip).limit(limit)
                    async for product_mongo in mongo_cursor:
                        product_mongo["product_id"] = str(product_mongo["_id"])
                        del product_mongo["_id"]
                        if 'variants' in product_mongo and isinstance(product_mongo['variants'], list):
                            variants = []
                            for var_item in product_mongo['variants']:
                                if isinstance(var_item, dict):
                                    variants.append({
                                        "attributes": var_item.get("attributes", {}),
                                        "color": var_item.get("color"), "id": var_item.get("id"),
                                        "inventory": var_item.get("inventory", 0),
                                        "price": var_item.get("price", {"amount": 0.0, "currency": "USD"}),
                                        "sku": var_item.get("sku"), "storage": var_item.get("storage")
                                    })
                            product_mongo['variants'] = variants
                        products_response_list.append(ProductResponse(**product_mongo))
                    
                    logger.info("Retrieved products from MongoDB (fallback).", extra={"count": len(products_response_list), "skip": skip, "limit": limit})
                    span.set_attribute("app.products.source", "mongodb_fallback")
                    span.set_attribute("app.products.retrieved_count_mongodb", len(products_response_list))
                    span.set_status(Status(StatusCode.OK))
                    return products_response_list
                except Exception as mongo_error:
                    error_message = f"Error getting products from MongoDB after ES fallback (skip={skip}, limit={limit}): {mongo_error}"
                    logger.error("Error getting products from MongoDB after ES fallback.", extra={"skip": skip, "limit": limit, "error": str(mongo_error)}, exc_info=True)
                    span.record_exception(mongo_error)
                    span.set_status(Status(StatusCode.ERROR, description=error_message))
                    raise

    async def check_products_exist(self, product_ids: List[str]) -> ProductsExistResponse:
        with self.tracer.start_as_current_span("service.product.check_products_exist") as span:
            span.set_attribute("app.request.product_ids_count", len(product_ids))
            if product_ids:
                span.set_attribute("app.request.example_ids", str(product_ids[:min(3, len(product_ids))]))
            
            existing_found_ids = []
            missing_checked_ids = []
            try:
                collection = await self._get_read_collection()
                span.set_attribute(SpanAttributes.DB_MONGODB_COLLECTION, collection.name)

                for p_id_str in product_ids:
                    try:
                        obj_id = ObjectId(p_id_str)
                        product = await collection.find_one({"_id": obj_id})
                        if product:
                            existing_found_ids.append(p_id_str)
                        else:
                            missing_checked_ids.append(p_id_str)
                    except Exception:
                        logger.warning("Invalid product ID format or error checking existence for ID.", extra={"product_id": p_id_str}, exc_info=False)
                        missing_checked_ids.append(p_id_str)
                        span.add_event("invalid_product_id_format_in_check_exist", {"product_id": p_id_str})
                
                span.set_attribute("app.response.existing_ids_count", len(existing_found_ids))
                span.set_attribute("app.response.missing_ids_count", len(missing_checked_ids))
                span.set_status(Status(StatusCode.OK))
                return ProductsExistResponse(existing_ids=existing_found_ids, missing_ids=missing_checked_ids)

            except Exception as e:
                error_message = f"Error checking product existence for {len(product_ids)} IDs: {str(e)}"
                logger.error("Error checking product existence.", extra={"product_ids_count": len(product_ids), "error": str(e)}, exc_info=True)
                span.record_exception(e)
                span.set_status(Status(StatusCode.ERROR, description=error_message))
                raise


    async def get_product_mongodb_only(self, product_id: str) -> Optional[ProductResponse]:
        """MongoDB에서만 제품 ID로 제품 조회 (benchmark test용)"""
        with self.tracer.start_as_current_span("service.product.get_product_mongodb_only") as span:
            span.set_attribute("app.product.id", product_id)
            span.set_attribute("app.product.source_requested", "mongodb_only")
            try:
                collection = await self._get_read_collection()
                span.set_attribute(SpanAttributes.DB_MONGODB_COLLECTION, collection.name)
                product_mongo = await collection.find_one({"_id": ObjectId(product_id)})
                
                if product_mongo:
                    product_mongo["product_id"] = str(product_mongo["_id"])
                    del product_mongo["_id"]
                    response_data = {
                        key: product_mongo.get(key, ProductResponse.__fields__[key].default)
                        for key in ProductResponse.__fields__ if key in product_mongo or ProductResponse.__fields__[key].default is not None
                    }
                    response_data.update(product_mongo)
                    response_data["product_id"] = product_mongo["product_id"]

                    logger.info("Product found directly in MongoDB (benchmark).", extra={"product_id": product_id})
                    span.set_attribute("app.product.found", True)
                    span.set_status(Status(StatusCode.OK))
                    return ProductResponse(**response_data)
                else:
                    logger.warning("Product not found in MongoDB (benchmark).", extra={"product_id": product_id})
                    span.set_attribute("app.product.found", False)
                    span.set_status(Status(StatusCode.ERROR, "Product not found in MongoDB (benchmark)"))
                    return None
            except Exception as e:
                error_message = f"Error getting product (benchmark) {product_id} from MongoDB: {str(e)}"
                logger.error("Error getting product (benchmark) from MongoDB.", extra={"product_id": product_id, "error": str(e)}, exc_info=True)
                span.record_exception(e)
                span.set_status(Status(StatusCode.ERROR, description=error_message))
                raise