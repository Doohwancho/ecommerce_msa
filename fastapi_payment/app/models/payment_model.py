from sqlalchemy import Column, Integer, String, Float, DateTime, ForeignKey, Boolean, Enum, Text
from app.config.payment_database import Base  
import enum
from datetime import datetime


class PaymentStatusEnum(enum.Enum):
    PENDING = "pending"
    AUTHORIZED = "authorized"
    PAID = "paid"
    FAILED = "failed"
    REFUNDED = "refunded"
    PARTIALLY_REFUNDED = "partially_refunded"
    CANCELED = "canceled"

class PaymentMethodEnum(enum.Enum):
    CREDIT_CARD = "credit_card"
    DEBIT_CARD = "debit_card"
    BANK_TRANSFER = "bank_transfer"
    VIRTUAL_ACCOUNT = "virtual_account"
    MOBILE_PAYMENT = "mobile_payment"
    POINT = "point"

class Payment(Base):
    __tablename__ = "payments"
    
    payment_id = Column(Integer, primary_key=True, index=True)
    order_id = Column(String(50), nullable=False, index=True)  # FK 대신 문자열 ID 사용
    amount = Column(Float, nullable=False)
    currency = Column(String(3), nullable=False, default="KRW")
    payment_method = Column(Enum(PaymentMethodEnum), nullable=False)
    payment_status = Column(Enum(PaymentStatusEnum), nullable=False, default=PaymentStatusEnum.PENDING)
    external_payment_id = Column(String(100), nullable=True)  # PG사 결제 ID
    payment_date = Column(DateTime, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    
class PaymentTransaction(Base):
    __tablename__ = "payment_transactions"
    
    transaction_id = Column(Integer, primary_key=True, index=True)
    payment_id = Column(Integer, ForeignKey("payments.payment_id"), nullable=False)
    transaction_type = Column(String(50), nullable=False)  # 'payment', 'refund', 'cancel' 등
    amount = Column(Float, nullable=False)
    status = Column(String(50), nullable=False)
    payment_gateway = Column(String(50), nullable=False)  # 'toss', 'inicis', 'kakaopay' 등
    pg_transaction_id = Column(String(100), nullable=True)
    request_data = Column(Text, nullable=True)  # JSON 형태의 요청 데이터
    response_data = Column(Text, nullable=True)  # JSON 형태의 응답 데이터
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    