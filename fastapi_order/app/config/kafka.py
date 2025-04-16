from kafka import KafkaProducer
import json
import os

KAFKA_BOOTSTRAP_SERVERS = os.getenv('KAFKA_BOOTSTRAP_SERVERS', 'kafka-service:9092')
ORDER_CREATED_TOPIC = 'order-created'
ORDER_DLQ_TOPIC = 'order-dlq'  # Dead Letter Queue topic for failed order events

def get_kafka_producer():
    return KafkaProducer(
        bootstrap_servers=KAFKA_BOOTSTRAP_SERVERS,
        value_serializer=lambda v: json.dumps(v).encode('utf-8'),
        acks='all',  # Ensure message is written to all replicas
        retries=3,   # Number of retries for failed sends
        max_in_flight_requests_per_connection=1  # Ensure ordering
    ) 