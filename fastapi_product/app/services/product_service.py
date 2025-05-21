from typing import List, Optional, Dict, Any # Added Dict, Any for clarity
from bson import ObjectId
from datetime import datetime, timezone
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.config.elasticsearch import elasticsearch_config
from app.schemas.product import ProductCreate, ProductUpdate, ProductResponse, ProductsExistResponse, ProductInventoryResponse
from app.config.database import (
    get_write_product_collection, get_read_product_collection,
    get_mysql_db, get_read_mysql_db # Removed get_read_db, get_write_db if they are duplicates
)
from app.models.product import Product as MySQLProduct
from app.config.logging import logger # Your configured logger

# OTel imports
from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode
from opentelemetry.semconv.trace import SpanAttributes # For semantic conventions

class ProductService:
    def __init__(self):
        self.write_collection = None
        self.read_collection = None
        self.write_db_session: Optional[AsyncSession] = None # Type hint for clarity
        self.read_db_session: Optional[AsyncSession] = None  # Type hint for clarity
        # Initialize tracer for this service
        self.tracer = trace.get_tracer("app.services.ProductService", "0.1.0")

    async def _get_db_connection(self, getter_func, db_type: str, instance_role: str, span_name_suffix: str) -> Any:
        # Helper to get DB/ES connections with tracing
        # This internal method assumes it's called within an active span of a public method.
        # For more detailed tracing of connection acquisition itself, especially if it's complex or slow:
        with self.tracer.start_as_current_span(f"service.product.get_connection.{span_name_suffix}") as conn_span:
            conn_span.set_attribute(SpanAttributes.DB_SYSTEM, db_type)
            conn_span.set_attribute("app.db.role", instance_role)
            try:
                connection = await getter_func()
                if connection is None:
                    error_msg = f"{db_type.capitalize()} {instance_role} connection failed: getter returned None"
                    logger.error(error_msg) # Log before raising
                    conn_span.set_status(Status(StatusCode.ERROR, error_msg))
                    raise ConnectionError(error_msg) # Use a more specific exception
                conn_span.set_status(Status(StatusCode.OK))
                return connection
            except Exception as e:
                # This will catch ConnectionError from above or any other exception from getter_func
                logger.error(f"Failed to get {db_type} {instance_role} connection: {e}", exc_info=True)
                conn_span.record_exception(e)
                conn_span.set_status(Status(StatusCode.ERROR, f"Failed to get {db_type} {instance_role} connection"))
                raise # Re-raise to be handled by the calling public method's trace

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
        # Elasticsearch client acquisition is often lightweight if connection pool is managed by client library.
        # Tracing here is useful if elasticsearch_config.get_client() has significant logic/IO.
        # ElasticsearchInstrumentor will trace the actual ES operations.
        return await self._get_db_connection(
            elasticsearch_config.get_client, "elasticsearch", "client", "es_client"
        )

    async def create_product(self, product: ProductCreate) -> ProductResponse:
        """새로운 제품 생성 (MongoDB와 MySQL에 동시 저장)"""
        # This span is a parent to spans created by _get_write_collection, _get_write_db,
        # and auto-instrumented Pymongo/SQLAlchemy calls.
        with self.tracer.start_as_current_span("service.product.create_product") as span:
            span.set_attribute("app.product.request.title", product.title)
            span.set_attribute("app.product.request.sku", product.sku)
            span.set_attribute("app.product.request.brand", product.brand)
            product_id = None # Initialize to handle potential early exit

            try:
                # MongoDB write
                product_dict = product.dict()
                current_time_iso = datetime.now(timezone.utc).isoformat()
                product_dict["created_at"] = current_time_iso
                product_dict["updated_at"] = current_time_iso
                
                mongo_payload = product_dict.copy()
                if "stock" in mongo_payload: # MongoDB에서는 stock 정보 제외
                    del mongo_payload["stock"]
                
                span.add_event("Attempting MongoDB insert")
                collection = await self._get_write_collection()
                # PymongoInstrumentor traces insert_one
                result = await collection.insert_one(mongo_payload)
                product_id = str(result.inserted_id)
                span.set_attribute("app.product.id", product_id) # Set product_id as soon as available
                span.set_attribute(SpanAttributes.DB_MONGODB_COLLECTION, collection.name)
                logger.info(f"Product {product_id} created in MongoDB.")
                span.add_event("MongoDB insert successful", {"mongodb.document_id": product_id})

                # MySQL write
                span.add_event("Attempting MySQL insert")
                db = await self._get_write_db()
                # SQLAlchemyInstrumentor traces execute, commit, refresh
                
                # Check if product_id already exists in MySQL to prevent unique constraint violation
                # This select for update also locks the potential row or gap.
                stmt_check = select(MySQLProduct).where(MySQLProduct.product_id == product_id).with_for_update()
                existing_result = await db.execute(stmt_check)
                if existing_result.scalar_one_or_none():
                    error_msg = f"IntegrityError: Product with ID {product_id} (from MongoDB) already exists in MySQL."
                    logger.error(error_msg)
                    span.set_attribute("app.error.type", "data_integrity_violation")
                    span.set_status(Status(StatusCode.ERROR, error_msg))
                    # This is a critical data consistency issue, might require specific error handling or cleanup.
                    raise ValueError(error_msg) # Or a custom exception

                mysql_product = MySQLProduct(
                    product_id=product_id,
                    title=product.title,
                    description=product.description,
                    price=int(product.price.amount),
                    stock=product.stock,
                    stock_reserved=0,
                    created_at=datetime.now(timezone.utc) # Ensure UTC for DB
                )
                db.add(mysql_product)
                await db.commit()
                await db.refresh(mysql_product) # To get any DB-generated fields like auto-updated 'updated_at'
                logger.info(f"Product {product_id} created in MySQL.")
                span.add_event("MySQL insert successful")
                
                span.set_status(Status(StatusCode.OK))
                logger.info(f"Product {product_id} created successfully in both MongoDB and MySQL.")
                
                response_data = mongo_payload.copy() # Start with MongoDB data (stock excluded)
                response_data["product_id"] = product_id
                return ProductResponse(**response_data)

            except Exception as e:
                error_message = f"Error creating product (ID attempt: {product_id if product_id else 'N/A'}): {str(e)}"
                logger.error(error_message, exc_info=True)
                span.record_exception(e)
                span.set_status(Status(StatusCode.ERROR, description=error_message))
                # Re-raise to be handled by the API layer (which should convert to HTTPException)
                raise # Consider wrapping in a service-specific exception if needed

    async def get_product(self, product_id: str) -> Optional[ProductResponse]:
        """제품 ID로 제품 조회 (Elasticsearch 먼저 시도, 없으면 MongoDB 조회)"""
        with self.tracer.start_as_current_span("service.product.get_product") as span:
            span.set_attribute("app.product.request.id", product_id)
            try:
                # 1. Elasticsearch lookup
                span.add_event("Attempting Elasticsearch lookup")
                es = await self._get_es()
                # ElasticsearchInstrumentor traces es.get
                try:
                    es_response = await es.get(index="my_db.products", id=product_id) # Ensure index name is correct
                    if es_response and es_response.get('found', False):
                        product_data = es_response['_source']
                        product_data['product_id'] = product_id # Ensure product_id is present
                        
                        # Reconstruct variants if necessary (example from user code)
                        if 'variants' in product_data and isinstance(product_data['variants'], list):
                            variants = []
                            for var_item in product_data['variants']:
                                if isinstance(var_item, dict): # Ensure variant item is a dict
                                    variants.append({
                                        "attributes": var_item.get("attributes", {}),
                                        "color": var_item.get("color"), "id": var_item.get("id"),
                                        "inventory": var_item.get("inventory", 0),
                                        "price": var_item.get("price", {"amount": 0.0, "currency": "USD"}),
                                        "sku": var_item.get("sku"), "storage": var_item.get("storage")
                                    })
                            product_data['variants'] = variants

                        logger.info(f"Product {product_id} found in Elasticsearch.")
                        span.set_attribute("app.product.source", "elasticsearch")
                        span.set_status(Status(StatusCode.OK))
                        return ProductResponse(**product_data)
                except Exception as es_error: # Catch specific ES errors like NotFoundError if possible
                    logger.warning(f"Product {product_id} not found or error in Elasticsearch: {str(es_error)}", exc_info=False) # exc_info might be too verbose for not found
                    span.add_event("Elasticsearch_lookup_failed_or_not_found", {
                        "elasticsearch.error_type": type(es_error).__name__,
                        "elasticsearch.error_message": str(es_error)
                    })
                    # Do not set span status to ERROR here yet, will try MongoDB

                # 2. Fallback to MongoDB
                span.add_event("Falling back to MongoDB lookup")
                collection = await self._get_read_collection()
                # PymongoInstrumentor traces find_one
                product_mongo = await collection.find_one({"_id": ObjectId(product_id)})
                
                if product_mongo:
                    product_mongo["product_id"] = str(product_mongo["_id"])
                    del product_mongo["_id"]
                    # Ensure all fields for ProductResponse are present or have defaults
                    # This transformation logic should ideally be robust
                    response_data = {
                        key: product_mongo.get(key, ProductResponse.__fields__[key].default)
                        for key in ProductResponse.__fields__ if key in product_mongo or ProductResponse.__fields__[key].default is not None
                    }
                    response_data.update(product_mongo) # Override defaults with actual values
                    response_data["product_id"] = product_mongo["product_id"] # Ensure it's set

                    logger.info(f"Product {product_id} found in MongoDB after ES miss.")
                    span.set_attribute("app.product.source", "mongodb")
                    span.set_status(Status(StatusCode.OK))
                    return ProductResponse(**response_data)

                logger.warning(f"Product {product_id} not found in any source.")
                span.set_attribute("app.product.found", False)
                # If not found is an error for this operation's contract with its caller
                span.set_status(Status(StatusCode.ERROR, "Product not found in any source"))
                return None

            except Exception as e:
                error_message = f"Error getting product {product_id}: {str(e)}"
                logger.error(error_message, exc_info=True)
                span.record_exception(e)
                span.set_status(Status(StatusCode.ERROR, description=error_message))
                raise

    # --- Inventory Management Methods (MySQL specific) ---
    # These methods will have their SQLAlchemy calls traced by SQLAlchemyInstrumentor.
    # The manual spans here provide business context.

    async def _manage_inventory(
        self, operation_name: str, product_id: str, quantity: int,
        action: callable # (mysql_product, quantity) -> bool or custom result
    ) -> tuple[bool, str]:
        with self.tracer.start_as_current_span(f"service.product.inventory.{operation_name}") as span:
            span.set_attribute("app.product.id", product_id)
            span.set_attribute("app.request.quantity", quantity)
            span.set_attribute(SpanAttributes.DB_SYSTEM, "mysql")

            try:
                db = await self._get_write_db() # All inventory ops use write DB with FOR UPDATE
                
                # Lock the product row for update
                span.add_event("Acquiring row lock in MySQL")
                stmt = select(MySQLProduct).where(MySQLProduct.product_id == product_id).with_for_update()
                result = await db.execute(stmt)
                mysql_product: Optional[MySQLProduct] = result.scalar_one_or_none()

                if not mysql_product:
                    message = f"Product {product_id} not found in MySQL for inventory operation."
                    logger.warning(message)
                    span.set_attribute("app.product.found_in_mysql", False)
                    span.set_status(Status(StatusCode.ERROR, message)) # Not found is an error for inventory ops
                    return False, message

                span.set_attribute("app.product.found_in_mysql", True)
                span.set_attribute("app.mysql.initial_stock", mysql_product.stock)
                span.set_attribute("app.mysql.initial_stock_reserved", mysql_product.stock_reserved)

                # Perform the specific inventory action (reserve, release, confirm)
                success, message = await action(mysql_product, quantity) # Pass db if action needs it for commit

                if success:
                    await db.commit() # Commit changes if action was successful
                    await db.refresh(mysql_product) # Refresh to get updated state
                    span.set_attribute("app.mysql.final_stock", mysql_product.stock)
                    span.set_attribute("app.mysql.final_stock_reserved", mysql_product.stock_reserved)
                    span.set_status(Status(StatusCode.OK))
                    logger.info(f"Inventory operation '{operation_name}' for product {product_id} (qty: {quantity}): SUCCESS - {message}")
                else:
                    # Business logic failure (e.g., insufficient stock).
                    # Span status might be OK if op completed as designed, or ERROR if this is a failure for the caller.
                    # Let's consider it a client-side correctable error or a precondition failure.
                    span.set_status(Status(StatusCode.ERROR, message)) # Or OK if it's not an "error" for the span
                    logger.warning(f"Inventory operation '{operation_name}' for product {product_id} (qty: {quantity}): FAILED - {message}")
                    await db.rollback() # Rollback any potential changes made by 'action' if it wasn't purely a check

                return success, message
            except Exception as e:
                error_message = f"Error during inventory operation '{operation_name}' for product {product_id}: {str(e)}"
                logger.error(error_message, exc_info=True)
                span.record_exception(e)
                span.set_status(Status(StatusCode.ERROR, description=error_message))
                # Attempt to rollback in case of unexpected error during commit or other issues
                if 'db' in locals() and db.in_transaction():
                    try:
                        await db.rollback()
                        span.add_event("Transaction rolled back due to exception")
                    except Exception as rb_exc:
                        logger.error(f"Failed to rollback transaction during error handling: {rb_exc}", exc_info=True)
                        span.record_exception(rb_exc) # Record rollback error too

                return False, f"Unexpected error: {str(e)}" # Return a generic error message

    async def check_availability(self, product_id: str, quantity: int) -> tuple[bool, Optional[ProductResponse]]:
        """제품이 지정된 수량만큼 재고가 있는지 확인 (uses get_product which checks MySQL inventory)"""
        # This method calls get_product which internally gets inventory from MySQL.
        # The span for get_product will cover the underlying DB calls.
        # We can add a span here if check_availability has more logic than just calling get_product.
        # For now, assuming get_product's tracing is sufficient for the DB part.
        with self.tracer.start_as_current_span("service.product.check_availability") as span:
            span.set_attribute("app.product.id", product_id)
            span.set_attribute("app.request.quantity", quantity)
            try:
                # Get product details (this might internally fetch inventory from MySQL via ProductResponse if defined so)
                # The current get_product fetches from ES/Mongo. Inventory should come from MySQL.
                # Let's use get_product_inventory for a more direct check.
                inventory_info = await self.get_product_inventory(product_id)
                
                if not inventory_info:
                    logger.warning(f"Product inventory not found for ID {product_id} during availability check.")
                    span.set_attribute("app.product.found", False)
                    span.set_status(Status(StatusCode.ERROR, "Product inventory not found"))
                    return False, None # Product itself not found or inventory info missing

                span.set_attribute("app.product.found", True)
                is_available = inventory_info.available_stock >= quantity
                
                span.set_attribute("app.inventory.available_stock_checked", inventory_info.available_stock)
                span.set_attribute("app.inventory.is_available", is_available)
                span.set_status(Status(StatusCode.OK))
                logger.info(f"Product {product_id} availability check: requested={quantity}, available={inventory_info.available_stock}, result={is_available}")
                
                # To return ProductResponse, we might need to fetch full product details if only inventory was checked
                # For now, this matches the original return signature loosely, but returning full ProductResponse
                # might require another call to get_product if inventory_info doesn't have all fields.
                # Let's assume the caller only cares about the boolean for now, or get_product is called by caller.
                # For a consistent ProductResponse, we'd fetch it:
                product_details = await self.get_product(product_id) if is_available else None
                return is_available, product_details

            except Exception as e:
                error_message = f"Error checking availability for product {product_id}: {e}"
                logger.error(error_message, exc_info=True)
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
        success, _ = await self.check_and_reserve_inventory(product_id, quantity) # Uses the combined logic
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
                db = await self._get_read_db() # Use read replica for inventory lookup if possible
                # SQLAlchemyInstrumentor traces db.get
                mysql_product = await db.get(MySQLProduct, product_id) # Assuming product_id is primary key in MySQLProduct

                if not mysql_product:
                    logger.warning(f"Product inventory for {product_id} not found in MySQL.")
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
                logger.error(error_message, exc_info=True)
                span.record_exception(e)
                span.set_status(Status(StatusCode.ERROR, description=error_message))
                raise # Re-raise to be handled by API layer

    # Update other methods (update_product, delete_product, get_products, check_products_exist, get_product_mongodb_only)
    # with similar tracing patterns: wrap in a span, add attributes, log errors with exc_info=True,
    # record exceptions on spans, and set span status.

    async def update_product(self, product_id: str, product_update: ProductUpdate) -> Optional[ProductResponse]:
        with self.tracer.start_as_current_span("service.product.update_product") as span:
            span.set_attribute("app.product.id", product_id)
            span.set_attribute("app.product.update_fields_count", len(product_update.dict(exclude_unset=True)))
            try:
                collection = await self._get_write_collection()
                span.set_attribute(SpanAttributes.DB_MONGODB_COLLECTION, collection.name)
                
                # PymongoInstrumentor traces find_one and update_one
                current_product = await collection.find_one({"_id": ObjectId(product_id)})
                if not current_product:
                    logger.warning(f"Product {product_id} not found for update.")
                    span.set_attribute("app.product.found", False)
                    span.set_status(Status(StatusCode.ERROR, "Product not found for update"))
                    return None
                
                span.set_attribute("app.product.found", True)
                update_data = product_update.dict(exclude_unset=True)
                update_data["updated_at"] = datetime.now(timezone.utc).isoformat() # Ensure UTC

                await collection.update_one({"_id": ObjectId(product_id)}, {"$set": update_data})
                
                updated_product_mongo = await collection.find_one({"_id": ObjectId(product_id)})
                # This re-fetch might be optional if update_one result is sufficient or if a write-through cache is used.
                # For consistency, re-fetching confirms the update.
                
                if updated_product_mongo:
                    updated_product_mongo["product_id"] = str(updated_product_mongo["_id"])
                    del updated_product_mongo["_id"]
                    logger.info(f"Product {product_id} updated successfully.")
                    span.set_status(Status(StatusCode.OK))
                    return ProductResponse(**updated_product_mongo)
                else: # Should not happen if update was on existing and successful
                    error_msg = f"Product {product_id} disappeared after update attempt."
                    logger.error(error_msg)
                    span.set_status(Status(StatusCode.ERROR, error_msg))
                    return None

            except Exception as e:
                error_message = f"Error updating product {product_id}: {str(e)}"
                logger.error(error_message, exc_info=True)
                span.record_exception(e)
                span.set_status(Status(StatusCode.ERROR, description=error_message))
                raise

    async def delete_product(self, product_id: str) -> bool:
        with self.tracer.start_as_current_span("service.product.delete_product") as span:
            span.set_attribute("app.product.id", product_id)
            try:
                collection = await self._get_write_collection()
                span.set_attribute(SpanAttributes.DB_MONGODB_COLLECTION, collection.name)
                # PymongoInstrumentor traces delete_one
                result = await collection.delete_one({"_id": ObjectId(product_id)})
                
                if result.deleted_count > 0:
                    logger.info(f"Product {product_id} deleted successfully from MongoDB.")
                    span.set_attribute("app.db.deleted_count", result.deleted_count)
                    span.set_status(Status(StatusCode.OK))
                    # Also delete from MySQL? Current code only deletes from Mongo.
                    # If MySQL delete is needed, add that logic here, also traced.
                    # For example:
                    # db_mysql = await self._get_write_db()
                    # stmt_mysql_delete = delete(MySQLProduct).where(MySQLProduct.product_id == product_id)
                    # await db_mysql.execute(stmt_mysql_delete)
                    # await db_mysql.commit()
                    # logger.info(f"Product {product_id} also deleted from MySQL.")
                    return True
                else:
                    logger.warning(f"Product {product_id} not found in MongoDB for deletion.")
                    span.set_attribute("app.db.deleted_count", 0)
                    span.set_status(Status(StatusCode.ERROR, "Product not found for deletion")) # Not found is an error for delete op
                    return False
            except Exception as e:
                error_message = f"Error deleting product {product_id}: {str(e)}"
                logger.error(error_message, exc_info=True)
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
                # ElasticsearchInstrumentor traces es.search
                es_query = {"query": {"match_all": {}}, "from": skip, "size": limit}
                response = await es.search(index="my_db.products", body=es_query) # Ensure index name
                
                for hit in response.get('hits', {}).get('hits', []):
                    product_data = hit['_source']
                    product_data['product_id'] = hit['_id'] # ES _id is usually the product_id
                     # Data transformation for variants (copied from your get_product)
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
                
                logger.info(f"Retrieved {len(products_response_list)} products from Elasticsearch (skip={skip}, limit={limit}).")
                span.set_attribute("app.products.source", "elasticsearch")
                span.set_attribute("app.products.retrieved_count", len(products_response_list))
                span.set_status(Status(StatusCode.OK))
                return products_response_list

            except Exception as es_error:
                logger.error(f"Error getting products from Elasticsearch (skip={skip}, limit={limit}): {es_error}", exc_info=True) # Log ES error
                span.record_exception(es_error) # Record ES error on span
                span.add_event("Elasticsearch_search_failed_falling_back_to_mongodb", {
                    "elasticsearch.error_type": type(es_error).__name__,
                    "elasticsearch.error_message": str(es_error)
                })

                # Fallback to MongoDB
                try:
                    collection = await self._get_read_collection()
                    span.set_attribute(SpanAttributes.DB_MONGODB_COLLECTION, collection.name)
                    # PymongoInstrumentor traces find
                    mongo_cursor = collection.find().skip(skip).limit(limit)
                    async for product_mongo in mongo_cursor:
                        product_mongo["product_id"] = str(product_mongo["_id"])
                        del product_mongo["_id"]
                        # Data transformation for variants (copied from your get_product)
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
                    
                    logger.info(f"Retrieved {len(products_response_list)} products from MongoDB (fallback) (skip={skip}, limit={limit}).")
                    span.set_attribute("app.products.source", "mongodb_fallback")
                    span.set_attribute("app.products.retrieved_count_mongodb", len(products_response_list))
                    span.set_status(Status(StatusCode.OK)) # OK because we successfully fell back
                    return products_response_list
                except Exception as mongo_error:
                    error_message = f"Error getting products from MongoDB after ES fallback (skip={skip}, limit={limit}): {mongo_error}"
                    logger.error(error_message, exc_info=True)
                    span.record_exception(mongo_error) # Record the MongoDB error too
                    span.set_status(Status(StatusCode.ERROR, description=error_message))
                    raise # Re-raise the original ES error or a new one indicating full failure

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

                # Perform finds. PymongoInstrumentor will trace each find_one.
                # For many IDs, a single $in query might be more efficient if MongoDB supports it well for your use case.
                # Example with individual find_one for direct mapping to current logic:
                for p_id_str in product_ids:
                    # Create child span for each ID check if very granular detail is needed, or just rely on Pymongo spans.
                    # For now, let's keep it simpler and rely on PymongoInstrumentor for sub-traces.
                    try:
                        obj_id = ObjectId(p_id_str)
                        product = await collection.find_one({"_id": obj_id})
                        if product:
                            existing_found_ids.append(p_id_str)
                        else:
                            missing_checked_ids.append(p_id_str)
                    except Exception: # Handles invalid ObjectId format or other find_one errors for a specific ID
                        logger.warning(f"Invalid product ID format or error checking existence for ID: {p_id_str}", exc_info=False)
                        missing_checked_ids.append(p_id_str) # Assume missing if ID format is bad
                        span.add_event("invalid_product_id_format_in_check_exist", {"product_id": p_id_str})
                
                span.set_attribute("app.response.existing_ids_count", len(existing_found_ids))
                span.set_attribute("app.response.missing_ids_count", len(missing_checked_ids))
                span.set_status(Status(StatusCode.OK))
                return ProductsExistResponse(existing_ids=existing_found_ids, missing_ids=missing_checked_ids)

            except Exception as e:
                error_message = f"Error checking product existence for {len(product_ids)} IDs: {str(e)}"
                logger.error(error_message, exc_info=True)
                span.record_exception(e)
                span.set_status(Status(StatusCode.ERROR, description=error_message))
                raise # Re-raise to be handled by API layer


    async def get_product_mongodb_only(self, product_id: str) -> Optional[ProductResponse]:
        """MongoDB에서만 제품 ID로 제품 조회 (benchmark test용)"""
        with self.tracer.start_as_current_span("service.product.get_product_mongodb_only") as span:
            span.set_attribute("app.product.id", product_id)
            span.set_attribute("app.product.source_requested", "mongodb_only")
            try:
                collection = await self._get_read_collection()
                span.set_attribute(SpanAttributes.DB_MONGODB_COLLECTION, collection.name)
                # PymongoInstrumentor traces find_one
                product_mongo = await collection.find_one({"_id": ObjectId(product_id)})
                
                if product_mongo:
                    product_mongo["product_id"] = str(product_mongo["_id"])
                    del product_mongo["_id"]
                     # Data transformation (copied from your get_product)
                    response_data = {
                        key: product_mongo.get(key, ProductResponse.__fields__[key].default)
                        for key in ProductResponse.__fields__ if key in product_mongo or ProductResponse.__fields__[key].default is not None
                    }
                    response_data.update(product_mongo)
                    response_data["product_id"] = product_mongo["product_id"]

                    logger.info(f"Product {product_id} found directly in MongoDB (benchmark).")
                    span.set_attribute("app.product.found", True)
                    span.set_status(Status(StatusCode.OK))
                    return ProductResponse(**response_data)
                else:
                    logger.warning(f"Product {product_id} not found in MongoDB (benchmark).")
                    span.set_attribute("app.product.found", False)
                    span.set_status(Status(StatusCode.ERROR, "Product not found in MongoDB (benchmark)")) # Explicit not found
                    return None
            except Exception as e:
                error_message = f"Error getting product (benchmark) {product_id} from MongoDB: {str(e)}"
                logger.error(error_message, exc_info=True)
                span.record_exception(e)
                span.set_status(Status(StatusCode.ERROR, description=error_message))
                raise