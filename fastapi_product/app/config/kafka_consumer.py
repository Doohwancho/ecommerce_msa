# fastapi-product/app/config/kafka_consumer.py
from aiokafka import AIOKafkaConsumer
import asyncio
import json
from typing import Callable, Dict, List

from opentelemetry import trace, propagate
from opentelemetry.trace import Status, StatusCode, SpanKind
from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator
from opentelemetry.semconv.trace import SpanAttributes

import logging

logger = logging.getLogger(__name__)

class ProductModuleKafkaConsumer:
    def __init__(self, bootstrap_servers: str, group_id: str, topics: List[str]):
        self.bootstrap_servers = bootstrap_servers
        self.group_id = group_id
        self.topics_to_subscribe = topics
        self.consumer: AIOKafkaConsumer = None
        self.handlers: Dict[str, Callable] = {}
        self.tracer = trace.get_tracer("app.config.product_kafka_consumer.ProductModuleKafkaConsumer", "0.1.0")
        self._running = False
        logger.info("ProductModuleKafkaConsumer initialized.", extra={"group_id": self.group_id, "topics": self.topics_to_subscribe})

    def register_handler(self, event_type: str, handler: Callable):
        self.handlers[event_type] = handler
        logger.info("Handler registered for event type.", 
                    extra={"group_id": self.group_id, "event_type": event_type, "handler_name": handler.__name__})

    async def start(self):
        if self._running:
            logger.warning("ProductModuleKafkaConsumer.start called but already running.", extra={"group_id": self.group_id})
            return
        if not self.topics_to_subscribe:
            logger.warning("No topics to subscribe to. Consumer not starting.", extra={"group_id": self.group_id})
            return

        with self.tracer.start_as_current_span(f"{self.group_id}.ProductModuleKafkaConsumer.start_instance") as span:
            span.set_attribute("app.kafka.consumer_group", self.group_id)
            span.set_attribute("app.kafka.subscribed_topics", ",".join(self.topics_to_subscribe))
            try:
                self.consumer = AIOKafkaConsumer(
                    *self.topics_to_subscribe,
                    bootstrap_servers=self.bootstrap_servers,
                    group_id=self.group_id,
                    auto_offset_reset='latest',
                    value_deserializer=lambda m: m.decode('utf-8', errors='replace') if isinstance(m, (bytes, bytearray)) else str(m),
                    enable_auto_commit=False
                )
                await self.consumer.start()
                self._running = True
                asyncio.create_task(self._consume_loop())
                logger.info("Kafka consumer task created.", 
                            extra={"group_id": self.group_id, "topics": self.topics_to_subscribe})
                span.set_status(Status(StatusCode.OK))
            except Exception as e:
                logger.error("Failed to start ProductModuleKafkaConsumer.", 
                             extra={"group_id": self.group_id, "error": str(e)}, exc_info=True)
                if span.is_recording(): span.record_exception(e); span.set_status(Status(StatusCode.ERROR, str(e)))
                self._running = False
                raise

    async def _consume_loop(self):
        if not self.consumer:
            logger.error("Consumer not initialized for ProductModule.", extra={"group_id": self.group_id})
            return

        logger.info("Starting consumption loop for ProductModule.", 
                    extra={"group_id": self.group_id, "topics": self.topics_to_subscribe})
        propagator = TraceContextTextMapPropagator()

        try:
            async for msg in self.consumer:
                logger.info("Product module Kafka message received.", 
                            extra={"group_id": self.group_id, "topic": msg.topic, "offset": msg.offset})

                carrier = {}
                header_log_for_debug = {}
                if msg.headers:
                    for key, value_bytes in msg.headers:
                        decoded_value = value_bytes.decode('utf-8', errors='replace') if value_bytes is not None else None
                        header_log_for_debug[key] = decoded_value
                        if key.lower() == 'traceparent' and decoded_value:
                            carrier['traceparent'] = decoded_value
                        elif key.lower() == 'tracestate' and decoded_value:
                            carrier['tracestate'] = decoded_value
                    logger.info("Decoded Kafka Headers (ProductModule).", 
                                extra={"group_id": self.group_id, "headers": header_log_for_debug})
                    if 'traceparent' not in carrier:
                        logger.warning("'traceparent' header NOT FOUND in ProductModule. New trace will start.", 
                                       extra={"group_id": self.group_id})
                else:
                    logger.warning("NO KAFKA HEADERS found in ProductModule. New trace will start.", 
                                   extra={"group_id": self.group_id})

                parent_context = propagator.extract(carrier=carrier)
                
                raw_payload_str = msg.value
                actual_payload_to_handle = None

                if isinstance(raw_payload_str, str):
                    logger.info("Raw string payload from Kafka.", 
                                extra={"group_id": self.group_id, "payload_repr": repr(raw_payload_str)})
                    try:
                        parsed_payload = json.loads(raw_payload_str)
                        if isinstance(parsed_payload, str):
                            logger.warning("Payload from topic was double-encoded. Second parse.", 
                                           extra={"group_id": self.group_id, "topic": msg.topic})
                            actual_payload_to_handle = json.loads(parsed_payload)
                        else:
                            actual_payload_to_handle = parsed_payload
                    except json.JSONDecodeError as e_json:
                        logger.error("Failed to parse JSON from topic. Skipping.", 
                                     extra={"group_id": self.group_id, "topic": msg.topic, "error": str(e_json)})
                        await self.consumer.commit()
                        continue
                else:
                    logger.error("Expected string payload but got different type. Skipping.", 
                                 extra={"group_id": self.group_id, "payload_type": str(type(raw_payload_str))})
                    await self.consumer.commit()
                    continue
                
                if not isinstance(actual_payload_to_handle, dict):
                    logger.error("Final payload is NOT dict. Skipping.", 
                                 extra={"group_id": self.group_id, "payload_type": str(type(actual_payload_to_handle))})
                    await self.consumer.commit()
                    continue
                
                event_type_from_header = header_log_for_debug.get('eventType')
                final_event_type = event_type_from_header or actual_payload_to_handle.get('type')
                
                if not final_event_type:
                    logger.error("Could not determine event_type. Skipping.", 
                                 extra={"group_id": self.group_id, "topic": msg.topic})
                    await self.consumer.commit()
                    continue

                # Prepare message attributes to pass to the handler
                message_attributes = {
                    SpanAttributes.MESSAGING_SYSTEM: "kafka",
                    SpanAttributes.MESSAGING_DESTINATION_NAME: msg.topic,
                    SpanAttributes.MESSAGING_DESTINATION_KIND: "topic",
                    SpanAttributes.MESSAGING_OPERATION: "process",
                    SpanAttributes.MESSAGING_MESSAGE_ID: str(msg.offset),
                    SpanAttributes.MESSAGING_KAFKA_PARTITION: msg.partition,
                    SpanAttributes.MESSAGING_KAFKA_CONSUMER_GROUP: self.group_id,
                    "app.event_type": final_event_type,
                    "app.message.key": msg.key.decode('utf-8', errors='ignore') if msg.key else None,
                }
                try:
                    message_attributes["app.message.payload_preview"] = json.dumps(actual_payload_to_handle, ensure_ascii=False)[:256]
                except: # pylint: disable=bare-except
                    message_attributes["app.message.payload_preview"] = str(actual_payload_to_handle)[:256]

                # The CONSUMER span creation is now delegated to the handler, which receives parent_context.
                try:
                    logger.info("Resolved final_event_type for message.", 
                                extra={"group_id": self.group_id, "event_type": final_event_type, "offset": msg.offset})

                    handler_to_call = self.handlers.get(final_event_type)
                    if handler_to_call:
                        logger.info("Calling handler for event.", 
                                    extra={"group_id": self.group_id, "handler_name": handler_to_call.__name__, "event_type": final_event_type})
                        # Pass parent_context and message_attributes to the handler
                        await handler_to_call(
                            actual_payload_to_handle,
                            parent_context=parent_context,
                            message_attributes=message_attributes
                        )
                        logger.info("Handler for event completed successfully.", 
                                    extra={"group_id": self.group_id, "event_type": final_event_type})
                    else:
                        logger.warning("No handler for event_type. Skipping.", 
                                       extra={"group_id": self.group_id, "event_type": final_event_type, "topic": msg.topic})
                except Exception as e_handler: # Catching exceptions from handler execution
                    logger.error("Error during handler execution for event.", 
                                 extra={"group_id": self.group_id, "event_type": final_event_type, "error": str(e_handler)}, 
                                 exc_info=True)
                    # No span to update status here, handler should manage its own span's status if one was created.
                
                await self.consumer.commit()
                logger.info("Offset committed.", 
                            extra={"group_id": self.group_id, "offset": msg.offset, "topic": msg.topic})

        except asyncio.CancelledError:
            logger.info("Consume loop cancelled for ProductModule.", extra={"group_id": self.group_id})
        except Exception as e_loop:
            logger.error("CRITICAL Kafka consumer loop error for ProductModule.", 
                         extra={"group_id": self.group_id, "error": str(e_loop)}, exc_info=True)
            self._running = False
        finally:
            logger.info("Consume loop ending for ProductModule.", extra={"group_id": self.group_id})
            if self._running:
                logger.warning("ProductModule consume_messages loop exited unexpectedly. Attempting to stop consumer.", 
                               extra={"group_id": self.group_id})
                await self.stop()

    async def stop(self):
        if not self._running and not self.consumer:
            logger.info("ProductModuleKafkaConsumer.stop called but not running or not initialized.", 
                        extra={"group_id": self.group_id})
            return
        
        tracer_for_stop = self.tracer
        with tracer_for_stop.start_as_current_span(f"{self.group_id}.ProductModuleKafkaConsumer.stop_instance") as span:
            try:
                current_running_status = self._running
                self._running = False 

                if self.consumer:
                    logger.info("Stopping ProductModuleKafkaConsumer.", 
                                extra={"group_id": self.group_id, "was_running": current_running_status})
                    await self.consumer.stop()
                    logger.info("ProductModuleKafkaConsumer stopped successfully.", extra={"group_id": self.group_id})
                    self.consumer = None 
                else:
                    logger.info("ProductModuleKafkaConsumer was already None.", 
                                extra={"group_id": self.group_id, "was_running": current_running_status})
                
                span.set_status(Status(StatusCode.OK))
            except Exception as e:
                logger.error("Error stopping ProductModuleKafkaConsumer.", 
                             extra={"group_id": self.group_id, "error": str(e)}, exc_info=True)
                if span.is_recording():
                    span.record_exception(e)
                    span.set_status(Status(StatusCode.ERROR, f"KafkaConsumerStopFailed: {str(e)}"))