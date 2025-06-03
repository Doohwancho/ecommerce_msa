from concurrent import futures
import grpc
from app.services.product_service import ProductService # Assuming this is your business logic
import product_pb2
import product_pb2_grpc

from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode
from opentelemetry.semconv.trace import SpanAttributes # For RPC semantic conventions

import logging

# Initialize a logger for this module
logger = logging.getLogger(__name__) # Replaced with import from app.config.logging

class ProductServiceServicer(product_pb2_grpc.ProductServiceServicer):
    def __init__(self, product_service: ProductService):
        self.product_service = product_service
        # Get a tracer for this servicer instance
        self.tracer = trace.get_tracer("app.grpc.ProductServiceServicer", "0.1.0") # Or use __name__

    async def GetProduct(self, request, context):
        # GrpcInstrumentorServer creates a parent span. This is a child span.
        with self.tracer.start_as_current_span("grpc.GetProduct.process") as span:
            # Standard RPC attributes (GrpcInstrumentorServer might also set these on its span)
            span.set_attribute(SpanAttributes.RPC_SYSTEM, "grpc")
            span.set_attribute(SpanAttributes.RPC_SERVICE, "product.ProductService") # Full gRPC service name
            span.set_attribute(SpanAttributes.RPC_METHOD, "GetProduct")
            
            # Application-specific request attributes
            span.set_attribute("app.request.product_id", request.product_id)
            
            try:
                product = await self.product_service.get_product(request.product_id)
                
                if not product:
                    error_detail = f"Product {request.product_id} not found"
                    span.set_attribute("app.error.type", "not_found")
                    span.set_status(Status(StatusCode.ERROR, description=error_detail))
                    logger.warning("Product not found in GetProduct.", extra={"product_id": request.product_id})
                    context.set_code(grpc.StatusCode.NOT_FOUND)
                    context.set_details(error_detail)
                    return product_pb2.ProductResponse() # Return empty response as per gRPC spec for NOT_FOUND

                # Application-specific response attributes
                span.set_attribute("app.response.product.title", product.title)
                span.set_attribute("app.response.product.price", product.price.amount) # Assuming product.price is an object
                span.set_status(Status(StatusCode.OK))
                
                logger.info("Successfully retrieved product in GetProduct.", extra={"product_id": request.product_id, "product_title": product.title})
                return product_pb2.ProductResponse(
                    product_id=product.product_id,
                    title=product.title,
                    price=product.price.amount # Adapt to your product_pb2.Product definition
                )
            except Exception as e:
                error_msg = f"Unhandled error in GetProduct for ID '{request.product_id}': {str(e)}"
                logger.error("Unhandled error in GetProduct.", 
                             extra={"product_id": request.product_id, "error": str(e)}, 
                             exc_info=True)
                span.record_exception(e) # Record exception on the span
                span.set_status(Status(StatusCode.ERROR, description=error_msg))
                
                context.set_code(grpc.StatusCode.INTERNAL)
                context.set_details(f"Internal server error: {str(e)}") # Be cautious about exposing raw error details
                return product_pb2.ProductResponse()

    async def CheckProductAvailability(self, request, context):
        with self.tracer.start_as_current_span("grpc.CheckProductAvailability.process") as span:
            span.set_attribute(SpanAttributes.RPC_SYSTEM, "grpc")
            span.set_attribute(SpanAttributes.RPC_SERVICE, "product.ProductService")
            span.set_attribute(SpanAttributes.RPC_METHOD, "CheckProductAvailability")
            
            span.set_attribute("app.request.product_id", request.product_id)
            span.set_attribute("app.request.quantity", request.quantity)
            
            try:
                # The check_availability method in ProductService now returns a tuple: (bool, Optional[ProductResponse])
                # We are interested in the boolean part here.
                is_available, _ = await self.product_service.check_availability(
                    request.product_id,
                    request.quantity
                )
                
                span.set_attribute("app.response.available", is_available)
                span.set_status(Status(StatusCode.OK))
                
                logger.info("Checked product availability.", 
                            extra={"product_id": request.product_id, "quantity": request.quantity, "available": is_available})
                return product_pb2.ProductAvailabilityResponse(
                    available=is_available,
                    message="Product is available" if is_available else "Product is not available"
                )
            except Exception as e:
                error_msg = f"Error in CheckProductAvailability for ID '{request.product_id}': {str(e)}"
                logger.error("Error in CheckProductAvailability.", 
                             extra={"product_id": request.product_id, "quantity": request.quantity, "error": str(e)}, 
                             exc_info=True)
                span.record_exception(e)
                span.set_status(Status(StatusCode.ERROR, description=error_msg))
                
                context.set_code(grpc.StatusCode.INTERNAL)
                context.set_details(f"Internal server error: {str(e)}")
                return product_pb2.ProductAvailabilityResponse(available=False, message=f"Error: {str(e)}")

    # Apply similar robust tracing and logging to other inventory methods:
    # CheckAndReserveInventory, ReserveInventory, ReleaseInventory, ConfirmInventory

    async def CheckAndReserveInventory(self, request, context):
        with self.tracer.start_as_current_span("grpc.CheckAndReserveInventory.process") as span:
            span.set_attribute(SpanAttributes.RPC_SYSTEM, "grpc")
            span.set_attribute(SpanAttributes.RPC_SERVICE, "product.ProductService")
            span.set_attribute(SpanAttributes.RPC_METHOD, "CheckAndReserveInventory")

            span.set_attribute("app.request.product_id", request.product_id)
            span.set_attribute("app.request.quantity", request.quantity)

            try:
                success, message = await self.product_service.check_and_reserve_inventory(
                    request.product_id,
                    request.quantity
                )
                
                span.set_attribute("app.response.success", success)
                span.set_attribute("app.response.message", message)
                
                if success:
                    span.set_status(Status(StatusCode.OK))
                    logger.info("CheckAndReserveInventory: SUCCESS.", 
                                extra={"product_id": request.product_id, "quantity": request.quantity, "response_detail": message})
                else:
                    # If not successful due to business logic (e.g., out of stock), it's not necessarily a span ERROR.
                    # The gRPC status code might be FAILED_PRECONDITION or ABORTED.
                    # For simplicity, if 'success' is false, we might still mark OTel span as OK if the operation completed as designed.
                    # However, if 'success=false' implies an unexpected issue or a client correctable one, ERROR might be suitable.
                    # Let's assume for now that a 'false' success is a valid business outcome handled by the message.
                    # If it should be an error, change span status and log level.
                    span.set_status(Status(StatusCode.OK, description=f"Reservation attempt completed: {message}")) # Or ERROR if 'false' is an error.
                    logger.warning("CheckAndReserveInventory: FAILED.", 
                                   extra={"product_id": request.product_id, "quantity": request.quantity, "response_detail": message})
                    # Potentially set a different gRPC status code if not 'success'
                    if "not available" in message.lower() or "insufficient" in message.lower():
                         context.set_code(grpc.StatusCode.FAILED_PRECONDITION)
                         context.set_details(message)

                return product_pb2.InventoryResponse(success=success, message=message)
            except Exception as e:
                error_msg = f"Error in CheckAndReserveInventory for ID '{request.product_id}': {str(e)}"
                logger.error("Error in CheckAndReserveInventory.", 
                             extra={"product_id": request.product_id, "quantity": request.quantity, "error": str(e)}, 
                             exc_info=True)
                span.record_exception(e)
                span.set_status(Status(StatusCode.ERROR, description=error_msg))
                
                context.set_code(grpc.StatusCode.INTERNAL)
                context.set_details(f"Internal server error: {str(e)}")
                return product_pb2.InventoryResponse(success=False, message=f"Error: {str(e)}")

    # ... (Implement similar pattern for ReserveInventory, ReleaseInventory, ConfirmInventory) ...
    # Example for one more:
    async def ReserveInventory(self, request, context):
        with self.tracer.start_as_current_span("grpc.ReserveInventory.process") as span:
            span.set_attribute(SpanAttributes.RPC_SYSTEM, "grpc")
            span.set_attribute(SpanAttributes.RPC_SERVICE, "product.ProductService")
            span.set_attribute(SpanAttributes.RPC_METHOD, "ReserveInventory")

            span.set_attribute("app.request.product_id", request.product_id)
            span.set_attribute("app.request.quantity", request.quantity)
            
            try:
                success = await self.product_service.reserve_inventory(
                    request.product_id,
                    request.quantity
                )
                message = "Inventory reserved successfully" if success else "Failed to reserve inventory"
                
                span.set_attribute("app.response.success", success)
                span.set_attribute("app.response.message", message)

                if success:
                    span.set_status(Status(StatusCode.OK))
                    logger.info("ReserveInventory: SUCCESS.", 
                                extra={"product_id": request.product_id, "quantity": request.quantity})
                else:
                    span.set_status(Status(StatusCode.OK, description=message)) # Or ERROR
                    logger.warning("ReserveInventory: FAILED.", 
                                   extra={"product_id": request.product_id, "quantity": request.quantity, "response_detail": message})
                    context.set_code(grpc.StatusCode.FAILED_PRECONDITION) # Example
                    context.set_details(message)

                return product_pb2.InventoryResponse(success=success, message=message)
            except Exception as e:
                error_msg = f"Error in ReserveInventory for ID '{request.product_id}': {str(e)}"
                logger.error("Error in ReserveInventory.", 
                             extra={"product_id": request.product_id, "quantity": request.quantity, "error": str(e)}, 
                             exc_info=True)
                span.record_exception(e)
                span.set_status(Status(StatusCode.ERROR, description=error_msg))
                context.set_code(grpc.StatusCode.INTERNAL)
                context.set_details(f"Internal server error: {str(e)}")
                return product_pb2.InventoryResponse(success=False, message=f"Error: {str(e)}")


    async def GetProductInventory(self, request, context):
        with self.tracer.start_as_current_span("grpc.GetProductInventory.process") as span:
            span.set_attribute(SpanAttributes.RPC_SYSTEM, "grpc")
            span.set_attribute(SpanAttributes.RPC_SERVICE, "product.ProductService")
            span.set_attribute(SpanAttributes.RPC_METHOD, "GetProductInventory")
            
            span.set_attribute("app.request.product_id", request.product_id)
            
            try:
                inventory = await self.product_service.get_product_inventory(request.product_id)
                
                if not inventory:
                    error_detail = f"Product inventory for {request.product_id} not found"
                    span.set_attribute("app.error.type", "not_found")
                    span.set_status(Status(StatusCode.ERROR, description=error_detail))
                    logger.warning("Product inventory not found in GetProductInventory.", 
                                   extra={"product_id": request.product_id})
                    context.set_code(grpc.StatusCode.NOT_FOUND)
                    context.set_details(error_detail)
                    return product_pb2.ProductInventoryResponse()

                span.set_attribute("app.response.inventory.stock", inventory.stock)
                span.set_attribute("app.response.inventory.stock_reserved", inventory.stock_reserved)
                span.set_attribute("app.response.inventory.available_stock", inventory.available_stock)
                span.set_status(Status(StatusCode.OK))
                
                logger.info("Successfully retrieved inventory for product.", 
                            extra={"product_id": request.product_id, "stock": inventory.stock, "available_stock": inventory.available_stock})
                return product_pb2.ProductInventoryResponse(
                    product_id=inventory.product_id,
                    stock=inventory.stock,
                    stock_reserved=inventory.stock_reserved,
                    available_stock=inventory.available_stock
                )
            except Exception as e:
                error_msg = f"Error in GetProductInventory for ID '{request.product_id}': {str(e)}"
                logger.error("Error in GetProductInventory.", 
                             extra={"product_id": request.product_id, "error": str(e)}, 
                             exc_info=True)
                span.record_exception(e)
                span.set_status(Status(StatusCode.ERROR, description=error_msg))
                
                context.set_code(grpc.StatusCode.INTERNAL)
                context.set_details(f"Internal server error: {str(e)}")
                return product_pb2.ProductInventoryResponse()

async def serve():
    # This function sets up the server. Tracing here is usually for the setup process itself.
    # GrpcInstrumentorServer will instrument the server once it starts handling requests.
    # ProductService instantiation can be traced if it's a complex/heavy operation.
    
    # Example: Tracing ProductService instantiation if it's significant
    # otel_tracer = trace.get_tracer("app.grpc.server_setup")
    # with otel_tracer.start_as_current_span("grpc.server.init_product_service"):
    #     product_service = ProductService()
    product_service = ProductService() # Assuming ProductService init is lightweight

    server = grpc.aio.server(
        futures.ThreadPoolExecutor(max_workers=10)
        # Add interceptors from GrpcInstrumentorServer if not applied globally
        # via GrpcInstrumentorServer().instrument_server(server)
        # However, GrpcInstrumentorServer().instrument() usually patches grpc.server globally.
    )
    
    servicer = ProductServiceServicer(product_service)
    product_pb2_grpc.add_ProductServiceServicer_to_server(servicer, server)
    
    listen_addr = '[::]:50051'
    server.add_insecure_port(listen_addr)
    logger.info("gRPC ProductService starting.", extra={"listen_addr": listen_addr})
    await server.start()
    
    try:
        await server.wait_for_termination()
    except KeyboardInterrupt:
        logger.info("gRPC ProductService stopping via KeyboardInterrupt.")
        await server.stop(0) # Graceful stop
    logger.info("gRPC ProductService stopped.")