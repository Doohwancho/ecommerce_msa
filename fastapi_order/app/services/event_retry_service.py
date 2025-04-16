import asyncio
import logging
import json
from datetime import datetime, timedelta
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update
from app.models.failed_event import FailedEvent
from app.config.kafka import get_kafka_producer, ORDER_CREATED_TOPIC
from kafka.errors import KafkaError
from app.config.database import get_async_mysql_db

logger = logging.getLogger(__name__)

class EventRetryService:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.kafka_producer = get_kafka_producer()
        self.max_retries = 5
        self.retry_delay_hours = 1

    async def retry_failed_events(self):
        """Retry failed events that haven't exceeded max retries"""
        try:
            # Get pending events that haven't exceeded max retries
            query = select(FailedEvent).where(
                FailedEvent.status == 'pending',
                FailedEvent.retry_count < self.max_retries,
                FailedEvent.last_retry_at < datetime.utcnow() - timedelta(hours=self.retry_delay_hours)
            )
            result = await self.session.execute(query)
            failed_events = result.scalars().all()

            for event in failed_events:
                try:
                    # Update status to processing
                    await self.session.execute(
                        update(FailedEvent)
                        .where(FailedEvent.id == event.id)
                        .values(
                            status='processing',
                            last_retry_at=datetime.utcnow()
                        )
                    )
                    await self.session.commit()

                    # Retry publishing the event
                    if event.event_type == 'order_created':
                        try:
                            # Parse event_data from string to dict
                            event_data = json.loads(event.event_data)
                            self.kafka_producer.send(ORDER_CREATED_TOPIC, event_data)
                            self.kafka_producer.flush()
                        except json.JSONDecodeError as e:
                            logger.error(f"Failed to parse event data for event {event.id}: {str(e)}")
                            raise

                    # Update status to completed
                    await self.session.execute(
                        update(FailedEvent)
                        .where(FailedEvent.id == event.id)
                        .values(status='completed')
                    )
                    await self.session.commit()
                    logger.info(f"Successfully retried event {event.id}")

                except (KafkaError, json.JSONDecodeError) as e:
                    # Update retry count and status
                    await self.session.execute(
                        update(FailedEvent)
                        .where(FailedEvent.id == event.id)
                        .values(
                            retry_count=FailedEvent.retry_count + 1,
                            status='pending' if event.retry_count + 1 < self.max_retries else 'failed',
                            error_message=str(e)
                        )
                    )
                    await self.session.commit()
                    logger.error(f"Failed to retry event {event.id}: {str(e)}")

        except Exception as e:
            logger.error(f"Error in retry service: {str(e)}")
            await self.session.rollback()

    async def start_retry_loop(self):
        """Start the retry loop"""
        while True:
            await self.retry_failed_events()
            await asyncio.sleep(self.retry_delay_hours * 3600)  # Sleep for retry_delay_hours

async def start_event_retry_service():
    """Start the event retry service"""
    async for session in get_async_mysql_db():
        event_retry_service = EventRetryService(session)
        await event_retry_service.start_retry_loop() 