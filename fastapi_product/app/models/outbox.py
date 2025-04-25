from sqlalchemy import Column, String, JSON
import uuid
from app.config.database import Base


class Outbox(Base):
    __tablename__ = "outbox"
    
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    aggregatetype = Column(String(255), nullable=False)  # Debezium이 필요로 하는 필드
    aggregateid = Column(String(255), nullable=False)    # Debezium이 필요로 하는 필드
    type = Column(String(255), nullable=False)           # 이벤트 타입
    payload = Column(JSON, nullable=False)               # 이벤트 데이터