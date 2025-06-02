from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
from datetime import datetime
from enum import Enum

class PaymentStatus(str, Enum):
    PENDING = "pending"
    AUTHORIZED = "authorized"
    PAID = "paid"
    FAILED = "failed"
    REFUNDED = "refunded"
    PARTIALLY_REFUNDED = "partially_refunded"
    CANCELED = "canceled"

class PaymentMethod(str, Enum):
    CREDIT_CARD = "credit_card"
    DEBIT_CARD = "debit_card"
    BANK_TRANSFER = "bank_transfer"
    VIRTUAL_ACCOUNT = "virtual_account"
    MOBILE_PAYMENT = "mobile_payment"
    POINT = "point"

# 기본 결제 정보 스키마
class PaymentBase(BaseModel):
    order_id: str  # 주문 ID는 문자열로 변경 (MSA 환경 고려)
    amount: float
    currency: str = "KRW"
    payment_method: PaymentMethod

# 결제 생성 요청 스키마
class PaymentCreate(PaymentBase):
    pass
    # stock_reserved: int = Field(..., description="Number of items reserved for this payment")

# 결제 상태 업데이트 스키마
class PaymentUpdate(BaseModel):
    payment_status: Optional[PaymentStatus] = None
    external_payment_id: Optional[str] = None
    payment_date: Optional[datetime] = None

# 결제 처리 요청 스키마
class PaymentProcessRequest(PaymentBase):
    payment_gateway: str  # 'toss', 'inicis', 'kakaopay' 등
    payment_data: Dict[str, Any] = Field(..., description="결제 게이트웨이에 전달할 데이터")

# 환불 요청 스키마
class RefundRequest(BaseModel):
    payment_id: int
    amount: float
    reason: Optional[str] = None

# 결제 응답 스키마
class PaymentResponse(PaymentBase):
    payment_id: int
    payment_status: PaymentStatus
    external_payment_id: Optional[str] = None
    payment_date: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime
    
    class Config:
        orm_mode = True

# 트랜잭션 기본 스키마
class TransactionBase(BaseModel):
    payment_id: int
    transaction_type: str
    amount: float
    status: str
    payment_gateway: str
    pg_transaction_id: Optional[str] = None
    request_data: Optional[Dict[str, Any]] = None
    response_data: Optional[Dict[str, Any]] = None

# 트랜잭션 생성 스키마
class TransactionCreate(TransactionBase):
    pass

# 트랜잭션 응답 스키마
class TransactionResponse(TransactionBase):
    transaction_id: int
    created_at: datetime
    
    class Config:
        orm_mode = True

# 트랜잭션이 포함된 결제 응답 스키마
class PaymentWithTransactions(PaymentResponse):
    transactions: List[TransactionResponse] = []