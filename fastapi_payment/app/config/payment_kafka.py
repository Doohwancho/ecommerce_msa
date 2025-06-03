from aiokafka import AIOKafkaConsumer
import asyncio
import json
from typing import Callable, Dict
import logging

from opentelemetry import trace, propagate
from opentelemetry.trace import Status, StatusCode, SpanKind
from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator
from opentelemetry.semconv.trace import SpanAttributes

logger = logging.getLogger(__name__)

class KafkaConsumer:
    def __init__(self, bootstrap_servers: str, group_id: str, topic: str = 'dbserver.order'):
        self.bootstrap_servers = bootstrap_servers
        self.group_id = group_id
        self.topic_to_subscribe = topic
        self.consumer: AIOKafkaConsumer = None
        self.handlers: Dict[str, Callable] = {}
        self.tracer = trace.get_tracer("app.config.payment_kafka.KafkaConsumer", "0.1.0")
        self._running = False
        logger.info("KafkaConsumer initialized.", 
                    extra={"group_id": self.group_id, "topic": self.topic_to_subscribe, "bootstrap_servers": self.bootstrap_servers})

    def register_handler(self, event_type: str, handler: Callable):
        self.handlers[event_type] = handler
        logger.info("Handler registered.", 
                    extra={"group_id": self.group_id, "event_type": event_type, "handler_name": handler.__name__})

    async def start(self):
        if self._running:
            logger.warning("KafkaConsumer.start called but already running.", extra={"group_id": self.group_id})
            return

        with self.tracer.start_as_current_span(f"{self.group_id}.KafkaConsumer.start_consumer_instance") as span:
            span.set_attribute(SpanAttributes.MESSAGING_SYSTEM, "kafka")
            span.set_attribute(SpanAttributes.MESSAGING_KAFKA_CONSUMER_GROUP, self.group_id)
            span.set_attribute(SpanAttributes.MESSAGING_DESTINATION, self.topic_to_subscribe)
            span.set_attribute("app.kafka.bootstrap_servers", self.bootstrap_servers)
            
            logger.info("Attempting to create AIOKafkaConsumer.", 
                        extra={"group_id": self.group_id, "topic": self.topic_to_subscribe})
            try:
                self.consumer = AIOKafkaConsumer(
                    self.topic_to_subscribe,
                    bootstrap_servers=self.bootstrap_servers,
                    group_id=self.group_id,
                    auto_offset_reset='latest',
                    value_deserializer=lambda m: m.decode('utf-8', errors='replace') if isinstance(m, (bytes, bytearray)) else str(m),
                    enable_auto_commit=False
                )
                await self.consumer.start()
                self._running = True
                asyncio.create_task(self.consume_messages())
                logger.info("Kafka consumer task created and started.", 
                            extra={"group_id": self.group_id, "topic": self.topic_to_subscribe})
                span.set_status(Status(StatusCode.OK))
            except Exception as e:
                logger.error("Failed to start Kafka consumer.", 
                             extra={"group_id": self.group_id, "topic": self.topic_to_subscribe, "error": str(e)},
                             exc_info=True)
                if span.is_recording():
                    span.record_exception(e)
                    span.set_status(Status(StatusCode.ERROR, description=f"Failed to start consumer: {str(e)}"))
                self._running = False
                raise

    async def consume_messages(self):
        if not self.consumer:
            logger.error("Consumer not initialized. Cannot consume messages.", extra={"group_id": self.group_id})
            return

        logger.info("Starting message consumption loop.", 
                    extra={"group_id": self.group_id, "topic": self.topic_to_subscribe})
        propagator = TraceContextTextMapPropagator()

        try:
            async for msg in self.consumer:
                log_meta = {
                    "group_id": self.group_id,
                    "topic": msg.topic, 
                    "partition": msg.partition, 
                    "offset": msg.offset, 
                    "key": msg.key
                }
                logger.info("Kafka message received (raw).", extra=log_meta)

                carrier = {}
                header_log = {}
                if msg.headers:
                    for key, value_bytes in msg.headers:
                        decoded_value = value_bytes.decode('utf-8', errors='replace') if value_bytes is not None else None
                        header_log[key] = decoded_value
                        if key.lower() == 'traceparent' and decoded_value:
                            carrier['traceparent'] = decoded_value
                        elif key.lower() == 'tracestate' and decoded_value:
                            carrier['tracestate'] = decoded_value
                    logger.info("Decoded Kafka Message Headers.", extra=dict(log_meta, headers=header_log))
                    if 'traceparent' not in carrier:
                        logger.warning("'traceparent' not found or is null in message headers.", extra=dict(log_meta, headers=header_log))
                else:
                    logger.warning("No Kafka message headers found.", extra=log_meta)

                parent_context = propagator.extract(carrier=carrier)
                raw_payload_str = msg.value
                actual_message_payload = None

                if isinstance(raw_payload_str, str):
                    logger.debug("Raw string payload from Kafka (repr).", extra=dict(log_meta, raw_payload_repr=repr(raw_payload_str)))
                    try:
                        parsed_payload = json.loads(raw_payload_str)
                        if isinstance(parsed_payload, str):
                            logger.warning("Payload was a double-encoded string. Attempting second parse.", 
                                           extra=dict(log_meta, first_parse_preview=parsed_payload[:200]))
                            actual_message_payload = json.loads(parsed_payload)
                        else:
                            actual_message_payload = parsed_payload
                    except json.JSONDecodeError as e_json:
                        logger.error("Failed to parse JSON string payload. Skipping message.", 
                                     extra=dict(log_meta, raw_payload_preview=raw_payload_str[:500], error=str(e_json)), exc_info=True)
                        await self.consumer.commit()
                        continue
                else:
                    logger.error("Expected string payload from deserializer, but got different type. Skipping.", 
                                 extra=dict(log_meta, payload_type=str(type(raw_payload_str)), value_preview=str(raw_payload_str)[:200]))
                    await self.consumer.commit()
                    continue
                
                logger.debug("Final processed message payload.", 
                            extra=dict(log_meta, payload_type=str(type(actual_message_payload)), payload_preview=str(actual_message_payload)[:500]))

                if not isinstance(actual_message_payload, dict):
                    logger.error("Message payload is NOT a dict after processing. Skipping.", 
                                 extra=dict(log_meta, payload_type=str(type(actual_message_payload)), value_preview=str(actual_message_payload)[:200]))
                    await self.consumer.commit()
                    continue
                
                event_type_from_header = header_log.get('eventType')
                final_event_type = event_type_from_header or actual_message_payload.get('type')
                
                if final_event_type and final_event_type != event_type_from_header and not event_type_from_header:
                     logger.info("Using eventType from payload 'type' field.", extra=dict(log_meta, event_type=final_event_type))

                if not final_event_type:
                    logger.error("Could not determine event_type. Skipping message.", extra=log_meta)
                    await self.consumer.commit()
                    continue

                with self.tracer.start_as_current_span(
                    f"{self.group_id}.message.process.{final_event_type}", # Span name includes group_id
                    context=parent_context,
                    kind=SpanKind.CONSUMER,
                    attributes={
                        SpanAttributes.MESSAGING_SYSTEM: "kafka",
                        SpanAttributes.MESSAGING_CONSUMER_ID: self.group_id,
                        SpanAttributes.MESSAGING_DESTINATION: msg.topic,
                        SpanAttributes.MESSAGING_KAFKA_PARTITION: msg.partition,
                        SpanAttributes.MESSAGING_KAFKA_MESSAGE_OFFSET: msg.offset,
                        SpanAttributes.MESSAGING_KAFKA_MESSAGE_KEY: msg.key.decode('utf-8', 'replace') if msg.key else None,
                        "app.event.type": final_event_type,
                    }
                ) as processing_span:
                    try:
                        payload_preview_for_span = json.dumps(actual_message_payload, ensure_ascii=False)[:256]
                    except:
                        payload_preview_for_span = str(actual_message_payload)[:256]
                    processing_span.set_attribute("app.message.payload_preview", payload_preview_for_span)

                    log_meta_with_event = dict(log_meta, event_type=final_event_type)
                    logger.info("Processing event.", extra=log_meta_with_event)

                    if final_event_type in self.handlers:
                        handler_to_call = self.handlers[final_event_type]
                        logger.info("Calling handler for event.", 
                                    extra=dict(log_meta_with_event, handler_name=handler_to_call.__name__))
                        try:
                            await handler_to_call(actual_message_payload)
                            logger.info("Handler completed successfully.", 
                                        extra=dict(log_meta_with_event, handler_name=handler_to_call.__name__))
                            if processing_span.is_recording():
                                processing_span.set_status(Status(StatusCode.OK))
                        except Exception as e_handler:
                            logger.error("Error in handler.", 
                                         extra=dict(log_meta_with_event, handler_name=handler_to_call.__name__, error=str(e_handler)), 
                                         exc_info=True)
                            if processing_span.is_recording():
                                processing_span.record_exception(e_handler)
                                processing_span.set_status(Status(StatusCode.ERROR, f"HandlerExecutionFailed: {str(e_handler)}"))
                    else:
                        logger.warning("No handler registered for event_type. Skipping.", extra=log_meta_with_event)
                        if processing_span.is_recording():
                            processing_span.set_status(Status(StatusCode.OK, f"NoHandlerForEventType_{final_event_type}"))
                    
                    await self.consumer.commit()
                    logger.info("Offset committed after processing event.", extra=log_meta_with_event)

        except asyncio.CancelledError:
            logger.info("Consume messages task cancelled.", extra={"group_id": self.group_id, "topic": self.topic_to_subscribe})
        except Exception as e_loop:
            logger.critical("CRITICAL Kafka consumer loop error.", 
                            extra={"group_id": self.group_id, "topic": self.topic_to_subscribe, "error": str(e_loop)}, 
                            exc_info=True)
            self._running = False # Ensure flag is set on critical loop error
        finally:
            logger.info("Consume_messages loop ending.", extra={"group_id": self.group_id, "topic": self.topic_to_subscribe, "is_running_flag": self._running})
            if self._running: # If loop exited but _running is still true (unexpected exit)
                logger.warning("Consume_messages loop exited unexpectedly while still marked as running. Attempting to stop consumer.", 
                               extra={"group_id": self.group_id, "topic": self.topic_to_subscribe})
                await self.stop() # Ensure cleanup if loop crashes

    async def stop(self):
        if not self._running and not self.consumer:
            logger.info("KafkaConsumer.stop called but not running or not initialized.", extra={"group_id": self.group_id})
            return
        
        with self.tracer.start_as_current_span(f"{self.group_id}.KafkaConsumer.stop_consumer_instance") as span:
            span.set_attribute(SpanAttributes.MESSAGING_SYSTEM, "kafka")
            span.set_attribute(SpanAttributes.MESSAGING_KAFKA_CONSUMER_GROUP, self.group_id)
            try:
                current_running_status = self._running
                self._running = False # Set running to False immediately

                if self.consumer:
                    logger.info("Stopping Kafka consumer.", extra={"group_id": self.group_id, "was_running": current_running_status})
                    await self.consumer.stop()
                    logger.info("Kafka consumer stopped successfully.", extra={"group_id": self.group_id})
                    self.consumer = None # Clear consumer instance
                else:
                    logger.info("Kafka consumer was already None.", extra={"group_id": self.group_id, "was_running": current_running_status})
                
                span.set_status(Status(StatusCode.OK))
            except Exception as e:
                logger.error("Error stopping Kafka consumer.", 
                             extra={"group_id": self.group_id, "error": str(e)}, 
                             exc_info=True)
                if span.is_recording():
                    span.record_exception(e)
                    span.set_status(Status(StatusCode.ERROR, f"KafkaConsumerStopFailed: {str(e)}"))