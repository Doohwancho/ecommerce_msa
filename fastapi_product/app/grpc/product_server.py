from concurrent import futures
import grpc
import logging
from app.services.product_service import ProductService
import product_pb2 
import product_pb2_grpc
from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode

class ProductServiceServicer(product_pb2_grpc.ProductServiceServicer):
    def __init__(self, product_service: ProductService):
        self.product_service = product_service
        self.tracer = trace.get_tracer(__name__)

    async def GetProduct(self, request, context):
        with self.tracer.start_as_current_span("grpc.server.get_product") as span:
            try:
                span.set_attribute("product.id", request.product_id)
                
                product = await self.product_service.get_product(request.product_id)
                if not product:
                    span.set_status(Status(StatusCode.ERROR, f"Product {request.product_id} not found"))
                    context.set_code(grpc.StatusCode.NOT_FOUND)
                    context.set_details(f"Product {request.product_id} not found")
                    return product_pb2.ProductResponse()
                
                # 상품 정보 추적
                span.set_attributes({
                    "product.title": product.title,
                    "product.price": product.price.amount
                })
                span.set_status(Status(StatusCode.OK))
                
                return product_pb2.ProductResponse(
                    product_id=product.product_id,
                    title=product.title,
                    price=product.price.amount
                )
            except Exception as e:
                span.set_status(Status(StatusCode.ERROR, str(e)))
                context.set_code(grpc.StatusCode.INTERNAL)
                context.set_details(str(e))
                return product_pb2.ProductResponse()

    async def CheckProductAvailability(self, request, context):
        with self.tracer.start_as_current_span("grpc.server.check_availability") as span:
            try:
                span.set_attributes({
                    "product.id": request.product_id,
                    "request.quantity": request.quantity
                })
                
                available = await self.product_service.check_availability(
                    request.product_id, 
                    request.quantity
                )
                
                span.set_attribute("response.available", available)
                span.set_status(Status(StatusCode.OK))
                
                return product_pb2.ProductAvailabilityResponse(
                    available=available,
                    message="Product is available" if available else "Product is not available"
                )
            except Exception as e:
                span.set_status(Status(StatusCode.ERROR, str(e)))
                context.set_code(grpc.StatusCode.INTERNAL)
                context.set_details(str(e))
                return product_pb2.ProductAvailabilityResponse(available=False)

    async def CheckAndReserveInventory(self, request, context):
        with self.tracer.start_as_current_span("grpc.server.check_and_reserve_inventory") as span:
            try:
                span.set_attributes({
                    "product.id": request.product_id,
                    "request.quantity": request.quantity
                })
                
                success, message = await self.product_service.check_and_reserve_inventory(
                    request.product_id, 
                    request.quantity
                )
                
                span.set_attributes({
                    "response.success": success,
                    "response.message": message
                })
                span.set_status(Status(StatusCode.OK))
                
                return product_pb2.InventoryResponse(
                    success=success,
                    message=message
                )
            except Exception as e:
                span.set_status(Status(StatusCode.ERROR, str(e)))
                context.set_code(grpc.StatusCode.INTERNAL)
                context.set_details(str(e))
                return product_pb2.InventoryResponse(success=False, message=str(e))

    async def ReserveInventory(self, request, context):
        with self.tracer.start_as_current_span("grpc.server.reserve_inventory") as span:
            try:
                span.set_attributes({
                    "product.id": request.product_id,
                    "request.quantity": request.quantity
                })
                
                success = await self.product_service.reserve_inventory(
                    request.product_id, 
                    request.quantity
                )
                
                message = "Inventory reserved successfully" if success else "Failed to reserve inventory"
                span.set_attributes({
                    "response.success": success,
                    "response.message": message
                })
                span.set_status(Status(StatusCode.OK))
                
                return product_pb2.InventoryResponse(
                    success=success,
                    message=message
                )
            except Exception as e:
                span.set_status(Status(StatusCode.ERROR, str(e)))
                context.set_code(grpc.StatusCode.INTERNAL)
                context.set_details(str(e))
                return product_pb2.InventoryResponse(success=False, message=str(e))
    
    async def ReleaseInventory(self, request, context):
        with self.tracer.start_as_current_span("grpc.server.release_inventory") as span:
            try:
                span.set_attributes({
                    "product.id": request.product_id,
                    "request.quantity": request.quantity
                })
                
                success = await self.product_service.release_inventory(
                    request.product_id, 
                    request.quantity
                )
                
                message = "Reserved inventory released successfully" if success else "Failed to release inventory"
                span.set_attributes({
                    "response.success": success,
                    "response.message": message
                })
                span.set_status(Status(StatusCode.OK))
                
                return product_pb2.InventoryResponse(
                    success=success,
                    message=message
                )
            except Exception as e:
                span.set_status(Status(StatusCode.ERROR, str(e)))
                context.set_code(grpc.StatusCode.INTERNAL)
                context.set_details(str(e))
                return product_pb2.InventoryResponse(success=False, message=str(e))
    
    async def ConfirmInventory(self, request, context):
        with self.tracer.start_as_current_span("grpc.server.confirm_inventory") as span:
            try:
                span.set_attributes({
                    "product.id": request.product_id,
                    "request.quantity": request.quantity
                })
                
                success = await self.product_service.confirm_inventory(
                    request.product_id, 
                    request.quantity
                )
                
                message = "Inventory confirmed successfully" if success else "Failed to confirm inventory"
                span.set_attributes({
                    "response.success": success,
                    "response.message": message
                })
                span.set_status(Status(StatusCode.OK))
                
                return product_pb2.InventoryResponse(
                    success=success,
                    message=message
                )
            except Exception as e:
                span.set_status(Status(StatusCode.ERROR, str(e)))
                context.set_code(grpc.StatusCode.INTERNAL)
                context.set_details(str(e))
                return product_pb2.InventoryResponse(success=False, message=str(e))

    async def GetProductInventory(self, request, context):
        with self.tracer.start_as_current_span("grpc.server.get_product_inventory") as span:
            try:
                span.set_attribute("product.id", request.product_id)
                
                inventory = await self.product_service.get_product_inventory(request.product_id)
                if not inventory:
                    span.set_status(Status(StatusCode.ERROR, f"Product inventory {request.product_id} not found"))
                    context.set_code(grpc.StatusCode.NOT_FOUND)
                    context.set_details(f"Product inventory {request.product_id} not found")
                    return product_pb2.ProductInventoryResponse()
                
                # 재고 정보 추적
                span.set_attributes({
                    "inventory.stock": inventory.stock,
                    "inventory.stock_reserved": inventory.stock_reserved,
                    "inventory.available_stock": inventory.available_stock
                })
                span.set_status(Status(StatusCode.OK))
                
                return product_pb2.ProductInventoryResponse(
                    product_id=inventory.product_id,
                    stock=inventory.stock,
                    stock_reserved=inventory.stock_reserved,
                    available_stock=inventory.available_stock
                )
            except Exception as e:
                span.set_status(Status(StatusCode.ERROR, str(e)))
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