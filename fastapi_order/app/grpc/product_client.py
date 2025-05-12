import grpc  # 이 부분을 수정
import product_pb2 
import product_pb2_grpc
from fastapi import HTTPException
import logging
from typing import List, Tuple, Optional
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
from grpc import RpcError

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
        try:
            await self._ensure_channel()
                
            request = product_pb2.ProductRequest(product_id=product_id)
            response = await self.stub.GetProduct(request)
            
            # Check if product exists
            if not response.product_id:
                raise HTTPException(status_code=404, detail="Product not found")
                
            return response
        except grpc.RpcError as e:
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
            logger.error(f"Unexpected error while getting product: {e}")
            raise HTTPException(status_code=500, detail="Internal server error")
        
    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=4, max=10),
        retry=retry_if_exception_type((RpcError, ConnectionError)),
        reraise=True
    )
    async def check_availability(self, product_id: str, quantity: int) -> Tuple[bool, product_pb2.ProductResponse]:
        try:
            await self._ensure_channel()
            
            # Get the product and its inventory information
            product = await self.get_product(product_id)
            if not product:
                logger.error(f"Product {product_id} not found")
                return False, None
                
            # Get inventory information
            inventory = await self.get_product_inventory(product_id)
            if not inventory:
                logger.error(f"Inventory information not found for product {product_id}")
                return False, product
            
            # Check if stock is sufficient
            if inventory.available_stock < quantity:
                logger.warning(f"Product {product_id} has insufficient stock. Required: {quantity}, Available: {inventory.available_stock}")
                return False, product
                
            logger.info(f"Product {product_id} has sufficient stock. Required: {quantity}, Available: {inventory.available_stock}")
            return True, product
        except grpc.RpcError as e:
            logger.error(f"gRPC error while checking availability: {e}")
            if e.code() == grpc.StatusCode.UNAVAILABLE:
                logger.error("Product service is unavailable")
                raise HTTPException(status_code=503, detail="Product service unavailable")
            else:
                logger.error(f"Unexpected gRPC error: {e}")
                raise HTTPException(status_code=500, detail="Internal server error")
        except Exception as e:
            logger.error(f"Unexpected error while checking availability: {e}")
            raise HTTPException(status_code=500, detail="Internal server error")

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=4, max=10),
        retry=retry_if_exception_type((RpcError, ConnectionError)),
        reraise=True
    )
    async def check_products_exist(self, product_ids: List[str]):
        try:
            await self._ensure_channel()
            
            request = product_pb2.ProductsExistRequest(product_ids=product_ids)
            response = await self.stub.CheckProductsExist(request)
            return response
        except grpc.RpcError as e:
            logger.error(f"gRPC error while checking products existence: {e}")
            if e.code() == grpc.StatusCode.UNAVAILABLE:
                logger.error("Product service is unavailable")
                raise HTTPException(status_code=503, detail="Product service unavailable")
            else:
                logger.error(f"Unexpected gRPC error: {e}")
                raise HTTPException(status_code=500, detail="Internal server error")
        except Exception as e:
            logger.error(f"Unexpected error while checking products existence: {e}")
            raise HTTPException(status_code=500, detail="Internal server error")

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=4, max=10),
        retry=retry_if_exception_type((RpcError, ConnectionError)),
        reraise=True
    )
    async def check_and_reserve_inventory(self, product_id: str, quantity: int) -> tuple[bool, str]:
        """
        제품 재고 확인과 예약을 한 번에 수행합니다.
        
        Args:
            product_id: 제품 ID
            quantity: 요청 수량
            
        Returns:
            tuple: (성공 여부, 메시지)
        """
        try:
            await self._ensure_channel()
            
            request = product_pb2.InventoryRequest(
                product_id=product_id,
                quantity=quantity
            )
            
            response = await self.stub.CheckAndReserveInventory(request)
            
            if not response.success:
                logger.warning(f"Failed to check and reserve inventory for product {product_id}: {response.message}")
            
            return response.success, response.message
        except grpc.RpcError as e:
            logger.error(f"gRPC error while checking and reserving inventory: {e}")
            if e.code() == grpc.StatusCode.UNAVAILABLE:
                logger.error("Product service is unavailable")
                raise HTTPException(status_code=503, detail="Product service unavailable")
            else:
                logger.error(f"Unexpected gRPC error: {e}")
                raise HTTPException(status_code=500, detail="Internal server error")
        except Exception as e:
            logger.error(f"Error calling CheckAndReserveInventory gRPC method: {str(e)}")
            return False, str(e)

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=4, max=10),
        retry=retry_if_exception_type((RpcError, ConnectionError)),
        reraise=True
    )
    async def release_inventory(self, product_id: str, quantity: int) -> bool:
        """
        SAGA 롤백을 위해 예약된 재고를 해제합니다.
        """
        try:
            await self._ensure_channel()
            
            request = product_pb2.InventoryRequest(
                product_id=product_id,
                quantity=quantity
            )
            
            response = await self.stub.ReleaseInventory(request)
            
            if not response.success:
                logger.warning(f"Failed to release inventory for product {product_id}: {response.message}")
            
            return response.success
        except Exception as e:
            logger.error(f"Error calling ReleaseInventory gRPC method: {str(e)}")
            return False

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=4, max=10),
        retry=retry_if_exception_type((RpcError, ConnectionError)),
        reraise=True
    )
    async def get_product_inventory(self, product_id: str) -> Optional[product_pb2.ProductInventoryResponse]:
        """
        제품의 재고 정보를 조회합니다.
        
        Args:
            product_id: 제품 ID
            
        Returns:
            Optional[ProductInventoryResponse]: 재고 정보 또는 None
        """
        try:
            await self._ensure_channel()
            
            request = product_pb2.ProductRequest(product_id=product_id)
            response = await self.stub.GetProductInventory(request)
            
            # Check if product exists
            if not response.product_id:
                return None
                
            return response
        except grpc.RpcError as e:
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
            logger.error(f"Unexpected error while getting product inventory: {e}")
            raise HTTPException(status_code=500, detail="Internal server error")

    async def close(self):
        if self.channel:
            logger.info("Closing gRPC channel")
            await self.channel.close()
            self.channel = None
            self.stub = None

