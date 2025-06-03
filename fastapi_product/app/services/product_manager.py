# fastapi-product/app/services/product_manager.py
import asyncio
import datetime
import json
import logging
import os
import uuid
from typing import Callable, Dict # Optional 제거 (사용 안 됨)


from app.config.database import WriteSessionLocal # SQLAlchemyInstrumentor가 DB 세션 자동 계측
from app.config.kafka_consumer import ProductModuleKafkaConsumer # 수정된 컨슈머 클래스 임포트
from app.models.outbox import Outbox
from app.services.product_service import ProductService

# OpenTelemetry API 임포트
from opentelemetry import propagate, trace
from opentelemetry.semconv.trace import SpanAttributes
from opentelemetry.trace import SpanKind, Status, StatusCode
import logging

logger = logging.getLogger(__name__) 


class ProductManager:
    def __init__(self):
        self.kafka_consumer: ProductModuleKafkaConsumer | None = None # 타입 명시
        self.max_retries = 3
        self.retry_delay = 1  # seconds
        # Tracer는 __init__ 시점에 OTel 설정이 완료되었다고 가정하고 가져옴
        self.tracer = trace.get_tracer(
            "app.services.product_manager.ProductManager", "0.1.0"
        )
        logger.info("ProductManager instance created.")

    async def initialize_kafka(self, bootstrap_servers: str, group_id: str):
        with self.tracer.start_as_current_span("ProductManager.initialize_kafka") as span: # 스팬 이름 일관성
            span.set_attribute("app.kafka.bootstrap_servers", bootstrap_servers)
            span.set_attribute("app.kafka.consumer_group", group_id)
            try:
                # OrderModule의 Outbox에서 'aggregatetype="order"'로 발행된 이벤트가 오는 토픽
                # 보통 'order_success', 'order_failed' 이벤트가 여기로 옴
                order_module_events_topic = os.getenv("ORDER_MODULE_EVENTS_TOPIC", "dbserver.order") 
                subscribed_topics = [order_module_events_topic]
                span.set_attribute("app.kafka.subscribed_topics", ",".join(subscribed_topics))
                
                self.kafka_consumer = ProductModuleKafkaConsumer( # 클래스 이름 확인
                    bootstrap_servers=bootstrap_servers,
                    group_id=group_id,
                    topics=subscribed_topics # 생성자에 토픽 리스트 전달
                )

                # ProductModuleKafkaConsumer는 event_type만으로 핸들러를 구분 (topic은 생성 시 지정)
                self.kafka_consumer.register_handler(
                    event_type='order_success', # OrderModule Outbox의 'type' 필드와 일치
                    handler=self.handle_order_success 
                )
                self.kafka_consumer.register_handler(
                    event_type='order_failed',  # OrderModule Outbox의 'type' 필드와 일치
                    handler=self.handle_order_failed
                )
                
                await self.kafka_consumer.start()
                logger.info("ProductManager: Kafka consumer initialized.", extra={
                    "group_id": group_id,
                    "topics": subscribed_topics
                })
                span.set_status(Status(StatusCode.OK))
            except Exception as e:
                logger.error("ProductManager: Failed to initialize Kafka consumer", extra={"error": str(e)}, exc_info=True)
                if span.is_recording():
                    span.record_exception(e)
                    span.set_status(Status(StatusCode.ERROR, "Kafka init failed in ProductManager"))
                raise
    

    async def _process_event_with_retries(
        self,
        event_name: str,
        event_data: dict,
        handler_logic_method: Callable,
        parent_context=None, 
        message_attributes: Dict = None, 
        compensation_method: Callable | None = None
    ):
        span_name = f"{message_attributes.get(SpanAttributes.MESSAGING_DESTINATION_NAME, 'unknown_topic')} {message_attributes.get('app.event_type', event_name)} process"
        
        current_order_id = str(event_data.get("order_id", "unknown_order"))
        attributes_for_span = {
            "app.event.name_handled": event_name,
            "app.order_id": current_order_id,
        }
        if message_attributes:
            attributes_for_span.update(message_attributes)

        with self.tracer.start_as_current_span(
            name=span_name,
            context=parent_context, 
            kind=SpanKind.CONSUMER, 
            attributes=attributes_for_span 
        ) as span:
            # Payload preview should be in message_attributes if available from consumer
            # No need to add it again here unless enhancing.

            retry_count = 0
            last_exception = None
            while retry_count <= self.max_retries:
                current_attempt = retry_count + 1
                span.set_attribute("app.retry.attempt", current_attempt)
                try:
                    logger.info("Processing event", extra={
                        "event_name": event_name,
                        "order_id": current_order_id, # Use local var
                        "attempt": current_attempt,
                        "max_attempts": self.max_retries + 1
                    })
                    await handler_logic_method(event_data) 
                    span.set_status(Status(StatusCode.OK))
                    logger.info("Successfully processed event", extra={
                        "event_name": event_name,
                        "order_id": current_order_id, # Use local var
                        "attempt": current_attempt
                    })
                    return
                except ValueError as ve:
                    error_msg = f"Data error processing event: {ve}"
                    logger.error(error_msg, extra={
                        "event_name": event_name,
                        "order_id": current_order_id, # Use local var
                        "attempt": current_attempt,
                        "error": str(ve)
                    }, exc_info=True)
                    if span.is_recording():
                        span.record_exception(ve)
                        span.set_status(Status(StatusCode.ERROR, error_msg))
                        span.set_attribute("app.error.type", "validation_error")
                    if compensation_method:
                        await compensation_method(
                            event_data,
                            failure_type=f"{event_name}_data_validation_failed",
                            reason=f"Data error: {ve}"
                        )
                    return
                except Exception as e:
                    last_exception = e
                    retry_count += 1
                    error_message = f"Error processing event (attempt {current_attempt} failed)"
                    logger.error(error_message, extra={
                        "event_name": event_name,
                        "order_id": current_order_id, # Use local var
                        "attempt_failed": current_attempt,
                        "next_attempt": retry_count +1 if retry_count <= self.max_retries else "max_retries_exceeded",
                        "error": str(e)
                    }, exc_info=True)
                    if span.is_recording():
                        span.record_exception(e)
                        span.add_event(
                            "handler_retry_exception",
                            {
                                "exception.message": str(e),
                                "retry.attempt_number_failed": current_attempt,
                            },
                        )

                    if retry_count > self.max_retries:
                        final_error_msg = f"CRITICAL: Failed to process event after {self.max_retries + 1} attempts."
                        logger.critical(final_error_msg, extra={
                            "event_name": event_name,
                            "order_id": current_order_id, # Use local var
                            "attempts": self.max_retries + 1,
                            "last_error": str(last_exception)
                        })
                        if span.is_recording():
                            span.set_status(Status(StatusCode.ERROR, final_error_msg))
                            span.set_attribute("app.error.type", "max_retries_exceeded")
                        if compensation_method:
                            await compensation_method(
                                event_data,
                                failure_type=f"{event_name}_max_retries_exceeded",
                                reason=f"Max retries exceeded: {last_exception}"
                            )
                        return

                    sleep_duration = self.retry_delay * (2 ** (retry_count - 1))
                    logger.info("Retrying event after delay", extra={
                        "event_name": event_name,
                        "order_id": current_order_id, # Use local var
                        "delay_seconds": sleep_duration,
                        "next_attempt": retry_count + 1
                    })
                    if span.is_recording(): 
                        span.add_event("retrying_handler_after_delay", {"delay_seconds": sleep_duration})
                    await asyncio.sleep(sleep_duration)

    async def _handle_order_success_logic(self, event_data: dict):
        # The current span here is a child of the CONSUMER span from _process_event_with_retries.
        with self.tracer.start_as_current_span( # Simplified span name
            "ProductManager._handle_order_success_logic" 
        ) as span:
            items = event_data.get("items", [])
            order_id = event_data.get("order_id", "unknown_order_id")
            span.set_attribute("app.order_id", str(order_id))
            span.set_attribute("app.items_count", len(items))
            if not items:
                logger.warning("No items found in 'order_success' event. Nothing to confirm.", extra={"order_id": order_id})
                span.set_status(Status(StatusCode.OK, "No items to confirm"))
                return 

            product_service = ProductService()
            for item_idx, item_data in enumerate(items):
                with self.tracer.start_as_current_span(f"ProductManager._handle_order_success_logic_item_{item_idx}") as item_span:
                    product_id = item_data.get("product_id")
                    quantity = item_data.get("quantity")
                    item_span.set_attribute("app.product_id", str(product_id))
                    item_span.set_attribute("app.quantity", quantity)

                    if not product_id or not isinstance(quantity, (int, float)) or quantity <= 0:
                        logger.warning("Invalid item data in order_success. Skipping.", extra={
                            "order_id": order_id,
                            "item_data": item_data
                        })
                        item_span.set_status(Status(StatusCode.ERROR, "Invalid item data for stock confirmation"))
                        continue

                    logger.info("Confirming inventory for product", extra={
                        "product_id": product_id,
                        "quantity": quantity,
                        "order_id": order_id
                    })
                    success = await product_service.confirm_inventory(
                        product_id=str(product_id), quantity=int(quantity)
                    )
                    if success:
                        logger.info("Inventory confirmed for product", extra={
                            "product_id": product_id,
                            "quantity": quantity
                        })
                        item_span.set_status(Status(StatusCode.OK))
                    else:
                        logger.error("Failed to confirm inventory for product.", extra={
                            "product_id": product_id,
                            "quantity": quantity,
                            "order_id": order_id
                        })
                        item_span.set_status(Status(StatusCode.ERROR, "Inventory confirmation failed"))
                        # This failure might require a SAGA compensation if critical
                        # For now, just logging and marking item span as error.
                        # The overall handler span status will be set at the end of _process_event_with_retries.

    async def handle_order_success(self, event_data: dict, parent_context=None, message_attributes: Dict = None):
        await self._process_event_with_retries(
            event_name="order_success",
            event_data=event_data,
            handler_logic_method=self._handle_order_success_logic,
            parent_context=parent_context,
            message_attributes=message_attributes,
            compensation_method=self.create_compensation_event_for_product_failure 
        )

    async def _handle_order_failed_logic(self, event_data: dict):
        with self.tracer.start_as_current_span( # Simplified span name
            "ProductManager._handle_order_failed_logic" 
        ) as span: 
            order_id = event_data.get("order_id", "unknown_order_id")
            reason = event_data.get("reason", event_data.get("error_message", "No reason provided"))
            items = event_data.get("items", []) 

            span.set_attribute("app.order_id", str(order_id))
            span.set_attribute("app.failure_reason", str(reason))
            span.set_attribute("app.items_count_at_failure", len(items))

            logger.info("Processing 'order_failed' event: rolling back inventory if necessary.", extra={
                "order_id": order_id,
                "reason": reason,
                "item_count": len(items)
            })

            if not items:
                logger.warning("No items found in 'order_failed' event. Nothing to roll back specifically for items.", extra={"order_id": order_id})

            product_service = ProductService()
            all_rollbacks_successful = True # Track overall rollback success for this handler
            for item_idx, item_data in enumerate(items):
                with self.tracer.start_as_current_span(f"ProductManager._handle_order_failed_logic_item_{item_idx}") as item_span:
                    product_id = item_data.get("product_id")
                    quantity = item_data.get("quantity") 
                    item_span.set_attribute("app.product_id", str(product_id))
                    item_span.set_attribute("app.quantity_to_rollback", quantity)

                    if not product_id or not isinstance(quantity, (int, float)) or quantity <= 0:
                        logger.warning("Invalid item data in order_failed for rollback. Skipping.", extra={
                            "order_id": order_id,
                            "item_data": item_data
                        })
                        item_span.set_status(Status(StatusCode.ERROR, "Invalid item data for inventory rollback"))
                        all_rollbacks_successful = False # Mark overall as failed if any item fails
                        continue
                    
                    logger.info("Rolling back reserved inventory for product", extra={
                        "product_id": product_id,
                        "quantity": quantity,
                        "order_id": order_id
                    })
                    rollback_success = await product_service.release_inventory( 
                        product_id=str(product_id), quantity=int(quantity)
                    ) 
                    if rollback_success:
                        logger.info("Inventory rolled back for product", extra={
                            "product_id": product_id, 
                            "quantity": quantity
                        })
                        item_span.set_status(Status(StatusCode.OK))
                    else:
                        logger.error("Failed to rollback inventory for product.", extra={
                            "product_id": product_id,
                            "quantity": quantity,
                            "order_id": order_id
                        })
                        item_span.set_status(Status(StatusCode.ERROR, "Inventory rollback failed"))
                        all_rollbacks_successful = False # Mark overall as failed
            
            # Create an Outbox event indicating the outcome of inventory adjustment for the failed order
            # The status should reflect if all rollbacks were successful or not
            outbox_event_status = "completed" if all_rollbacks_successful else "failed_partial" # Or "failed_complete" if no items processed
            if not items: # If there were no items, it's vacuously completed
                 outbox_event_status = "completed_no_items"

            await self.create_outbox_event_for_product_module(
                event_data=event_data, 
                event_type="product_inventory_adjustment_for_order_failure", 
                status=outbox_event_status 
            )
            
            # Set overall span status based on rollback success
            # _process_event_with_retries will set its span to OK if this method doesn't raise an exception.
            # If we want this handler's span (ProductManager._handle_order_failed_logic) to reflect partial failure,
            # we could set it here. However, _process_event_with_retries will set its span status.
            # For now, rely on logs and item_span statuses for partial failures.
            # If !all_rollbacks_successful, it might be an ERROR for this span.
            if not all_rollbacks_successful and items: # only error if there were items and they failed
                 span.set_status(Status(StatusCode.ERROR, "One or more inventory rollbacks failed for order_failed event"))
            else:
                 span.set_status(Status(StatusCode.OK)) # All rollbacks successful or no items to rollback

            logger.info(f"'order_failed' event processing finished with overall rollback status: {outbox_event_status}.", extra={"order_id": order_id})


    async def handle_order_failed(self, event_data: dict, parent_context=None, message_attributes: Dict = None):
        await self._process_event_with_retries(
            event_name="order_failed",
            event_data=event_data,
            handler_logic_method=self._handle_order_failed_logic,
            parent_context=parent_context,
            message_attributes=message_attributes,
            compensation_method=self.create_compensation_event_for_product_failure
        )

    async def create_compensation_event_for_product_failure(self, original_event_data: dict, failure_type: str, reason: str):
        current_span = trace.get_current_span()
        
        with self.tracer.start_as_current_span(
            "ProductManager.create_compensation_event_for_product_failure",
        ) as span:
            order_id = original_event_data.get("order_id", "unknown_order")
            span.set_attribute("app.order_id", str(order_id))
            span.set_attribute("app.failure_type", failure_type)
            span.set_attribute("app.failure_reason", reason)

            logger.warning("Creating compensation event for product failure", extra={
                "order_id": order_id,
                "failure_type": failure_type,
                "reason": reason
            })

            event_payload = {
                "original_event_trace_id": f"{current_span.get_span_context().trace_id:x}" if current_span.is_recording() else None,
                "original_event_span_id": f"{current_span.get_span_context().span_id:x}" if current_span.is_recording() else None,
                "order_id": order_id,
                "failure_details": {
                    "failed_module": "product-service",
                    "event_type_failed": original_event_data.get("type", original_event_data.get("event_name", "unknown")), # Use event_name if type not present
                    "failure_type": failure_type, 
                    "reason": reason,
                },
                "timestamp": datetime.datetime.utcnow().isoformat() + "Z",
            }

            # Determine a more specific aggregatetype for compensation related to product processing
            # Example: if original event was "order_success" that failed in product_service
            original_event_name = original_event_data.get("event_name", "unknown_event") # from _process_event_with_retries
            
            outbox_aggregatetype = "product_compensation"
            outbox_event_type = f"product_processing_failed_for_{original_event_name}"

            # Inject current OTel context into a carrier dictionary
            carrier = {}
            propagate.inject(carrier)

            outbox_event = Outbox(
                id=str(uuid.uuid4()), # Ensure ID is string for consistency
                aggregatetype=outbox_aggregatetype, 
                aggregateid=str(order_id), 
                type=outbox_event_type, 
                payload=json.dumps(event_payload, ensure_ascii=False),
                # Use the defined model fields for trace propagation
                traceparent_for_header=carrier.get("traceparent"),
                tracestate_for_header=carrier.get("tracestate")
            )
            
            # No longer need to set kafka_headers as a separate attribute
            # outbox_event.kafka_headers = json.dumps(carrier)

            async with WriteSessionLocal() as session:
                try:
                    session.add(outbox_event)
                    await session.commit()
                    logger.info("Compensation event stored in Outbox for product failure.", extra={
                        "outbox_event_id": str(outbox_event.id),
                        "order_id": order_id,
                        "failure_type": failure_type,
                        "outbox_event_type": outbox_event_type
                    })
                    span.set_status(Status(StatusCode.OK))
                except Exception as e_db:
                    logger.error("Failed to store compensation event in Outbox", extra={
                        "order_id": order_id,
                        "error": str(e_db)
                    }, exc_info=True)
                    if span.is_recording():
                        span.record_exception(e_db)
                        span.set_status(Status(StatusCode.ERROR, "Failed to store compensation event"))

    async def create_outbox_event_for_product_module(self, event_data: dict, event_type: str, status: str):
        current_span = trace.get_current_span()
        
        with self.tracer.start_as_current_span(
            f"ProductManager.create_outbox_event.{event_type}.{status}",
        ) as span:
            order_id = event_data.get("order_id", "unknown_order")
            span.set_attribute("app.order_id", str(order_id))
            span.set_attribute("app.event.created_type", event_type)
            span.set_attribute("app.event.created_status", status)

            logger.info(f"Creating Outbox event for product module: {event_type}, status: {status}", extra={
                "order_id": order_id
            })

            payload = {
                "order_id": order_id,
                "source_module": "product-service",
                "event_type_processed": event_data.get("type", event_data.get("event_name", "unknown")), # The event that ProductManager processed
                "resulting_event_type": event_type, 
                "status": status, 
                "timestamp": datetime.datetime.utcnow().isoformat() + "Z",
            }
            
            # Inject current OTel context into a carrier dictionary
            carrier = {}
            propagate.inject(carrier)

            outbox_event = Outbox(
                id=str(uuid.uuid4()), # Ensure ID is string
                aggregatetype="product_process_outcome", 
                aggregateid=str(order_id),
                type=event_type, 
                payload=json.dumps(payload, ensure_ascii=False),
                # Use the defined model fields for trace propagation
                traceparent_for_header=carrier.get("traceparent"),
                tracestate_for_header=carrier.get("tracestate")
            )

            async with WriteSessionLocal() as session:
                try:
                    session.add(outbox_event)
                    await session.commit()
                    logger.info("Product module Outbox event stored.", extra={
                        "outbox_event_id": str(outbox_event.id),
                        "order_id": order_id,
                        "type": event_type,
                        "status": status
                    })
                    span.set_status(Status(StatusCode.OK))
                except Exception as e_db:
                    logger.error("Failed to store product module Outbox event", extra={
                        "order_id": order_id,
                        "error": str(e_db)
                    }, exc_info=True)
                    if span.is_recording():
                        span.record_exception(e_db)
                        span.set_status(Status(StatusCode.ERROR, "Failed to store product Outbox event"))


    async def _store_failed_event(self, event_type: str, event_data: dict, error_msg: str):
        # This method is not directly used by the refactored compensation logic
        # but kept for potential other uses or if specific "failed event" storage is needed
        # outside of SAGA compensation Outbox events.
        current_span = trace.get_current_span()
        with self.tracer.start_as_current_span("ProductManager._store_failed_event") as span:
            order_id = event_data.get("order_id", "unknown_order")
            logger.error("Storing details of a failed event processing.", extra={
                "event_type": event_type,
                "order_id": order_id,
                "error_message": error_msg,
                "event_data_preview": json.dumps(event_data)[:256]
            })
            span.set_attribute("app.event.type", event_type)
            span.set_attribute("app.order_id", str(order_id))
            span.set_attribute("app.error.message", error_msg)
            # Potentially write to a specific "dead letter" table or log for later analysis
            # For now, this is primarily for logging and tracing.
            span.set_status(Status(StatusCode.ERROR, "Failed event stored/logged"))

    async def stop(self):
        if self.kafka_consumer:
            await self.kafka_consumer.stop()
        logger.info("ProductManager (and its ProductModuleKafkaConsumer) stopped.")