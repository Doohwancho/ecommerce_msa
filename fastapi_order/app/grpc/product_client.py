import grpc
import product_pb2 
import product_pb2_grpc
from fastapi import HTTPException
import logging
from typing import List, Tuple, Optional
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
from grpc import RpcError
import asyncio
from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# gRPC 채널 옵션
GRPC_CHANNEL_OPTIONS = [
    ('grpc.max_send_message_length', 50 * 1024 * 1024),  # 50MB
    ('grpc.max_receive_message_length', 50 * 1024 * 1024),  # 50MB
    ('grpc.keepalive_time_ms', 10000),  # 10 seconds
    ('grpc.keepalive_timeout_ms', 5000),  # 5 seconds
    ('grpc.keepalive_permit_without_calls', True),
    ('grpc.http2.min_ping_interval_without_data_ms', 5000),  # 5 seconds
    ('grpc.dns_min_time_between_resolutions_ms', 10000),  # 10 seconds
]

class ProductClient:
    def __init__(self):
        self.channel = None
        self.stub = None
        self.default_timeout = 5  # 기본 timeout 5초
        self.tracer = trace.get_tracer(__name__)
        
    async def _ensure_channel(self):
        if self.channel is None:
            self.channel = grpc.aio.insecure_channel('product-service:50051', options=GRPC_CHANNEL_OPTIONS)
            self.stub = product_pb2_grpc.ProductServiceStub(self.channel)
            logger.info("Created new gRPC channel to product-service")
        
    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=4, max=10),
        retry=retry_if_exception_type((RpcError, ConnectionError)),
        reraise=True
    )
    async def get_product(self, product_id: str):
        with self.tracer.start_as_current_span("grpc.client.get_product") as span:
            try:
                span.set_attribute("product.id", product_id)
                await self._ensure_channel()
                
                async with asyncio.timeout(self.default_timeout):
                    request = product_pb2.ProductRequest(product_id=product_id)
                    response = await self.stub.GetProduct(request)
                    
                    if not response.product_id:
                        span.set_status(Status(StatusCode.ERROR, "Product not found"))
                        raise HTTPException(status_code=404, detail="Product not found")
                    
                    span.set_attributes({
                        "product.title": response.title,
                        "product.price": response.price
                    })
                    span.set_status(Status(StatusCode.OK))
                    return response
            except asyncio.TimeoutError:
                span.set_status(Status(StatusCode.ERROR, "Product service timeout"))
                logger.error(f"Timeout while getting product {product_id}")
                raise HTTPException(status_code=504, detail="Product service timeout")
            except grpc.RpcError as e:
                span.set_status(Status(StatusCode.ERROR, str(e)))
                logger.error(f"gRPC error while getting product: {e}")
                if e.code() == grpc.StatusCode.NOT_FOUND:
                    raise HTTPException(status_code=404, detail="Product not found")
                elif e.code() == grpc.StatusCode.UNAVAILABLE:
                    logger.error("Product service is unavailable")
                    raise HTTPException(status_code=503, detail="Product service unavailable")
                else:
                    logger.error(f"Unexpected gRPC error: {e}")
                    raise HTTPException(status_code=500, detail="Internal server error")
            except Exception as e:
                span.set_status(Status(StatusCode.ERROR, str(e)))
                logger.error(f"Unexpected error while getting product: {e}")
                raise HTTPException(status_code=500, detail="Internal server error")
        
    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=4, max=10),
        retry=retry_if_exception_type((RpcError, ConnectionError)),
        reraise=True
    )
    async def check_availability(self, product_id: str, quantity: int) -> Tuple[bool, product_pb2.ProductResponse]:
        with self.tracer.start_as_current_span("grpc.client.check_availability") as span:
            try:
                span.set_attributes({
                    "product.id": product_id,
                    "request.quantity": quantity
                })
                
                await self._ensure_channel()
                
                async with asyncio.timeout(self.default_timeout):
                    product = await self.get_product(product_id)
                    if not product:
                        span.set_status(Status(StatusCode.ERROR, f"Product {product_id} not found"))
                        logger.error(f"Product {product_id} not found")
                        return False, None
                    
                    inventory = await self.get_product_inventory(product_id)
                    if not inventory:
                        span.set_status(Status(StatusCode.ERROR, f"Inventory information not found for product {product_id}"))
                        logger.error(f"Inventory information not found for product {product_id}")
                        return False, product
                    
                    available = inventory.available_stock >= quantity
                    span.set_attributes({
                        "inventory.available_stock": inventory.available_stock,
                        "inventory.required": quantity,
                        "inventory.available": available
                    })
                    
                    if not available:
                        logger.warning(f"Product {product_id} has insufficient stock. Required: {quantity}, Available: {inventory.available_stock}")
                    else:
                        logger.info(f"Product {product_id} has sufficient stock. Required: {quantity}, Available: {inventory.available_stock}")
                    
                    span.set_status(Status(StatusCode.OK))
                    return available, product
            except asyncio.TimeoutError:
                span.set_status(Status(StatusCode.ERROR, "Product service timeout"))
                logger.error(f"Timeout while checking availability for product {product_id}")
                raise HTTPException(status_code=504, detail="Product service timeout")
            except grpc.RpcError as e:
                span.set_status(Status(StatusCode.ERROR, str(e)))
                logger.error(f"gRPC error while checking availability: {e}")
                if e.code() == grpc.StatusCode.UNAVAILABLE:
                    logger.error("Product service is unavailable")
                    raise HTTPException(status_code=503, detail="Product service unavailable")
                else:
                    logger.error(f"Unexpected gRPC error: {e}")
                    raise HTTPException(status_code=500, detail="Internal server error")
            except Exception as e:
                span.set_status(Status(StatusCode.ERROR, str(e)))
                logger.error(f"Unexpected error while checking availability: {e}")
                raise HTTPException(status_code=500, detail="Internal server error")

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=4, max=10),
        retry=retry_if_exception_type((RpcError, ConnectionError)),
        reraise=True
    )
    async def check_and_reserve_inventory(self, product_id: str, quantity: int) -> tuple[bool, str]:
        with self.tracer.start_as_current_span("grpc.client.check_and_reserve_inventory") as span:
            try:
                span.set_attributes({
                    "product.id": product_id,
                    "request.quantity": quantity
                })
                
                await self._ensure_channel()
                
                async with asyncio.timeout(10):  # 10초
                    request = product_pb2.InventoryRequest(
                        product_id=product_id,
                        quantity=quantity
                    )
                    
                    response = await self.stub.CheckAndReserveInventory(request)
                    
                    span.set_attributes({
                        "response.success": response.success,
                        "response.message": response.message
                    })
                    
                    if not response.success:
                        logger.warning(f"Failed to check and reserve inventory for product {product_id}: {response.message}")
                    
                    span.set_status(Status(StatusCode.OK))
                    return response.success, response.message
            except asyncio.TimeoutError:
                span.set_status(Status(StatusCode.ERROR, "Service timeout while reserving inventory"))
                logger.error(f"Timeout while checking and reserving inventory for product {product_id}")
                return False, "Service timeout while reserving inventory"
            except grpc.RpcError as e:
                span.set_status(Status(StatusCode.ERROR, str(e)))
                logger.error(f"gRPC error while checking and reserving inventory: {e}")
                if e.code() == grpc.StatusCode.UNAVAILABLE:
                    logger.error("Product service is unavailable")
                    raise HTTPException(status_code=503, detail="Product service unavailable")
                else:
                    logger.error(f"Unexpected gRPC error: {e}")
                    raise HTTPException(status_code=500, detail="Internal server error")
            except Exception as e:
                span.set_status(Status(StatusCode.ERROR, str(e)))
                logger.error(f"Error calling CheckAndReserveInventory gRPC method: {str(e)}")
                return False, str(e)

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=4, max=10),
        retry=retry_if_exception_type((RpcError, ConnectionError)),
        reraise=True
    )
    async def release_inventory(self, product_id: str, quantity: int) -> bool:
        with self.tracer.start_as_current_span("grpc.client.release_inventory") as span:
            try:
                span.set_attributes({
                    "product.id": product_id,
                    "request.quantity": quantity
                })
                
                await self._ensure_channel()
                
                async with asyncio.timeout(self.default_timeout):
                    request = product_pb2.InventoryRequest(
                        product_id=product_id,
                        quantity=quantity
                    )
                    
                    response = await self.stub.ReleaseInventory(request)
                    
                    span.set_attributes({
                        "response.success": response.success,
                        "response.message": response.message
                    })
                    
                    if not response.success:
                        logger.warning(f"Failed to release inventory for product {product_id}: {response.message}")
                    
                    span.set_status(Status(StatusCode.OK))
                    return response.success
            except asyncio.TimeoutError:
                span.set_status(Status(StatusCode.ERROR, "Timeout while releasing inventory"))
                logger.error(f"Timeout while releasing inventory for product {product_id}")
                return False
            except Exception as e:
                span.set_status(Status(StatusCode.ERROR, str(e)))
                logger.error(f"Error calling ReleaseInventory gRPC method: {str(e)}")
                return False

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=4, max=10),
        retry=retry_if_exception_type((RpcError, ConnectionError)),
        reraise=True
    )
    async def get_product_inventory(self, product_id: str) -> Optional[product_pb2.ProductInventoryResponse]:
        with self.tracer.start_as_current_span("grpc.client.get_product_inventory") as span:
            try:
                span.set_attribute("product.id", product_id)
                
                await self._ensure_channel()
                
                async with asyncio.timeout(self.default_timeout):
                    request = product_pb2.ProductRequest(product_id=product_id)
                    response = await self.stub.GetProductInventory(request)
                    
                    if not response.product_id:
                        span.set_status(Status(StatusCode.ERROR, f"Product inventory {product_id} not found"))
                        return None
                    
                    span.set_attributes({
                        "inventory.stock": response.stock,
                        "inventory.stock_reserved": response.stock_reserved,
                        "inventory.available_stock": response.available_stock
                    })
                    
                    span.set_status(Status(StatusCode.OK))
                    return response
            except asyncio.TimeoutError:
                span.set_status(Status(StatusCode.ERROR, "Product service timeout"))
                logger.error(f"Timeout while getting product inventory for product {product_id}")
                raise HTTPException(status_code=504, detail="Product service timeout")
            except grpc.RpcError as e:
                span.set_status(Status(StatusCode.ERROR, str(e)))
                logger.error(f"gRPC error while getting product inventory: {e}")
                if e.code() == grpc.StatusCode.NOT_FOUND:
                    return None
                elif e.code() == grpc.StatusCode.UNAVAILABLE:
                    logger.error("Product service is unavailable")
                    raise HTTPException(status_code=503, detail="Product service unavailable")
                else:
                    logger.error(f"Unexpected gRPC error: {e}")
                    raise HTTPException(status_code=500, detail="Internal server error")
            except Exception as e:
                span.set_status(Status(StatusCode.ERROR, str(e)))
                logger.error(f"Unexpected error while getting product inventory: {e}")
                raise HTTPException(status_code=500, detail="Internal server error")

    async def close(self):
        if self.channel:
            logger.info("Closing gRPC channel")
            await self.channel.close()
            self.channel = None
            self.stub = None