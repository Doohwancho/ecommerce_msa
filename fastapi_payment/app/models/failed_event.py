from sqlalchemy import Column, String, Text, DateTime, func
from sqlalchemy.dialects.postgresql import UUID
from app.config.payment_database import Base
import uuid

class FailedEvent(Base):
    __tablename__ = "failed_events"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    event_type = Column(String(255), nullable=False, index=True)
    event_data = Column(Text, nullable=False)  # JSON string of the original event data
    error_message = Column(Text, nullable=False)
    status = Column(String(50), nullable=False, default='pending_review')  # pending_review, reviewed, resolved
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    def __repr__(self):
        return f"<FailedEvent(id={self.id}, event_type='{self.event_type}', status='{self.status}')>" 