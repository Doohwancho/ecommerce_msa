from sqlalchemy import Column, Integer, String, DateTime
from sqlalchemy.sql import func
from app.config.database import Base

class FailedEvent(Base):
    __tablename__ = "failed_events"

    id = Column(Integer, primary_key=True, index=True)
    event_type = Column(String(50), nullable=False)  # e.g., 'order_created'
    event_data = Column(String(500), nullable=False)    # Original event data
    error_message = Column(String(500), nullable=False)
    retry_count = Column(Integer, default=0)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    last_retry_at = Column(DateTime(timezone=True), nullable=True)
    status = Column(String(20), default='pending')   # pending, processing, failed, completed 