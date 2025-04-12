import grpc  # 이 부분을 수정
import product_pb2 
import product_pb2_grpc
from fastapi import HTTPException
import logging
from typing import List, Tuple

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
        
    async def check_availability(self, product_id: str, quantity: int) -> Tuple[bool, product_pb2.ProductResponse]:
        try:
            await self._ensure_channel()
            
            # Get the product to check its stock
            product = await self.get_product(product_id)
            if not product:
                logger.error(f"Product {product_id} not found")
                return False, None
                
            # Check if stock is sufficient
            if product.stock < quantity:
                logger.warning(f"Product {product_id} has insufficient stock. Required: {quantity}, Available: {product.stock}")
                return False, product
                
            logger.info(f"Product {product_id} has sufficient stock. Required: {quantity}, Available: {product.stock}")
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
        
    async def close(self):
        if self.channel:
            logger.info("Closing gRPC channel")
            await self.channel.close()
            self.channel = None
            self.stub = None

