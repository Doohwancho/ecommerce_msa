from concurrent import futures
import grpc
import logging
from app.services.product_service import ProductService
import product_pb2 
import product_pb2_grpc

class ProductServiceServicer(product_pb2_grpc.ProductServiceServicer):
    def __init__(self, product_service: ProductService):
        self.product_service = product_service

    async def GetProduct(self, request, context):
        try:
            product = await self.product_service.get_product(request.product_id)
            if not product:
                context.set_code(grpc.StatusCode.NOT_FOUND)
                context.set_details(f"Product {request.product_id} not found")
                return product_pb2.ProductResponse()
                
            return product_pb2.ProductResponse(
                product_id=product.product_id,
                title=product.title,
                price=product.price.amount
            )
        except Exception as e:
            context.set_code(grpc.StatusCode.INTERNAL)
            context.set_details(str(e))
            return product_pb2.ProductResponse()

    async def CheckProductAvailability(self, request, context):
        try:
            available = await self.product_service.check_availability(
                request.product_id, 
                request.quantity
            )
            return product_pb2.ProductAvailabilityResponse(
                available=available,
                message="Product is available" if available else "Product is not available"
            )
        except Exception as e:
            context.set_code(grpc.StatusCode.INTERNAL)
            context.set_details(str(e))
            return product_pb2.ProductAvailabilityResponse(available=False)

    async def CheckAndReserveInventory(self, request, context):
        try:
            success, message = await self.product_service.check_and_reserve_inventory(
                request.product_id, 
                request.quantity
            )
            
            return product_pb2.InventoryResponse(
                success=success,
                message=message
            )
        except Exception as e:
            context.set_code(grpc.StatusCode.INTERNAL)
            context.set_details(str(e))
            return product_pb2.InventoryResponse(success=False, message=str(e))

    async def ReserveInventory(self, request, context):
        try:
            success = await self.product_service.reserve_inventory(
                request.product_id, 
                request.quantity
            )
            
            message = "Inventory reserved successfully" if success else "Failed to reserve inventory"
            return product_pb2.InventoryResponse(
                success=success,
                message=message
            )
        except Exception as e:
            context.set_code(grpc.StatusCode.INTERNAL)
            context.set_details(str(e))
            return product_pb2.InventoryResponse(success=False, message=str(e))
    
    async def ReleaseInventory(self, request, context):
        try:
            success = await self.product_service.release_inventory(
                request.product_id, 
                request.quantity
            )
            
            message = "Reserved inventory released successfully" if success else "Failed to release inventory"
            return product_pb2.InventoryResponse(
                success=success,
                message=message
            )
        except Exception as e:
            context.set_code(grpc.StatusCode.INTERNAL)
            context.set_details(str(e))
            return product_pb2.InventoryResponse(success=False, message=str(e))
    
    async def ConfirmInventory(self, request, context):
        try:
            success = await self.product_service.confirm_inventory(
                request.product_id, 
                request.quantity
            )
            
            message = "Inventory confirmed successfully" if success else "Failed to confirm inventory"
            return product_pb2.InventoryResponse(
                success=success,
                message=message
            )
        except Exception as e:
            context.set_code(grpc.StatusCode.INTERNAL)
            context.set_details(str(e))
            return product_pb2.InventoryResponse(success=False, message=str(e))

    async def GetProductInventory(self, request, context):
        try:
            inventory = await self.product_service.get_product_inventory(request.product_id)
            if not inventory:
                context.set_code(grpc.StatusCode.NOT_FOUND)
                context.set_details(f"Product inventory {request.product_id} not found")
                return product_pb2.ProductInventoryResponse()
                
            return product_pb2.ProductInventoryResponse(
                product_id=inventory.product_id,
                stock=inventory.stock,
                stock_reserved=inventory.stock_reserved,
                available_stock=inventory.available_stock
            )
        except Exception as e:
            context.set_code(grpc.StatusCode.INTERNAL)
            context.set_details(str(e))
            return product_pb2.ProductInventoryResponse()

async def serve():
    server = grpc.aio.server(futures.ThreadPoolExecutor(max_workers=10))
    # Create an instance of the business logic service
    product_service = ProductService()
    # Create the gRPC servicer with the business logic service
    servicer = ProductServiceServicer(product_service)
    # Add the servicer to the server
    product_pb2_grpc.add_ProductServiceServicer_to_server(servicer, server)
    # Start the server
    server.add_insecure_port('[::]:50051')
    await server.start()
    await server.wait_for_termination() 