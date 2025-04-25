# fastapi_payment/app/services/payment_service.py
from typing import List, Optional, Dict, Any
from datetime import datetime
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from fastapi import HTTPException, Depends
import json
from app.schemas.payment_schemas import (
    PaymentBase, PaymentCreate, PaymentUpdate, PaymentResponse,
    TransactionBase, TransactionCreate, TransactionResponse,
    PaymentStatus, PaymentMethod, PaymentWithTransactions
)
from app.models.payment_model import Payment, PaymentTransaction
from app.config.payment_database import get_async_mysql_db
from app.config.payment_logging import logger
import uuid
from app.models.outbox import Outbox


class PaymentService:
    def __init__(self, db: AsyncSession):
        self.db = db
    
    async def get_all_payments(self) -> List[PaymentResponse]:
        """모든 결제 조회"""
        try:
            logger.info("Fetching all payments")
            result = await self.db.execute(select(Payment))
            payments = result.scalars().all()
            
            logger.info(f"Found {len(payments)} payments")
            return [self._convert_to_payment_response(payment) for payment in payments]
            
        except Exception as e:
            logger.error(f"Error getting all payments: {str(e)}")
            raise HTTPException(status_code=500, detail=str(e))

    def _convert_to_payment_response(self, payment: Payment) -> PaymentResponse:
        """Convert Payment model to PaymentResponse schema"""
        return PaymentResponse(
            payment_id=payment.payment_id,
            order_id=payment.order_id,
            amount=payment.amount,
            currency=payment.currency,
            payment_method=PaymentMethod(payment.payment_method.value),  # Convert to PaymentMethod enum
            payment_status=PaymentStatus(payment.payment_status.value),  # Convert to PaymentStatus enum
            created_at=payment.created_at,
            updated_at=payment.updated_at
        )

    async def create_payment(self, payment_data: PaymentCreate) -> PaymentResponse:
        """새로운 결제 생성"""
        try:
            logger.info(f"Creating payment for order: {payment_data.order_id}")
            
            # 테스트용: stock_reserved가 10인 경우 실패 시뮬레이션 (SAGA rollback pattern)
            if payment_data.stock_reserved == 10:
                logger.warning("Simulating payment failure for SAGA testing (stock_reserved = 10)")
                raise Exception("Simulated payment failure for SAGA testing - stock_reserved = 10")
            
            # 트랜잭션 시작
            async with self.db.begin():
                # 1. Payment 생성
                payment = Payment(
                    order_id=payment_data.order_id,
                    amount=payment_data.amount,
                    currency=payment_data.currency,
                    payment_method=payment_data.payment_method,
                    payment_status=PaymentStatus.PENDING
                )
                self.db.add(payment)
                await self.db.flush()  # payment_id를 얻기 위해 flush
                
                # 2. Outbox 이벤트 생성
                payment_created_event = {
                    'type': "payment_success",
                    'payment_id': payment.payment_id,
                    'order_id': payment.order_id,
                    'amount': payment.amount,
                    'currency': payment.currency,
                    'payment_method': payment.payment_method.value,  # Enum 값을 문자열로 변환
                    'payment_status': payment.payment_status.value,  # Enum 값을 문자열로 변환
                    'created_at': datetime.utcnow().isoformat()
                }
                
                outbox_event = Outbox(
                    id=str(uuid.uuid4()),
                    aggregatetype="payment",
                    aggregateid=str(payment.payment_id),
                    type="payment_success",
                    payload=payment_created_event
                )
                self.db.add(outbox_event)
                
            
            # 트랜잭션 외부에서 조회 (트랜잭션이 완료된 후)
            refreshed_payment = await self.db.get(Payment, payment.payment_id)

            logger.info(f"Payment created successfully: {refreshed_payment.payment_id}")
            return self._convert_to_payment_response(refreshed_payment)
            
        except Exception as e:
            logger.error(f"Error creating payment for order {payment_data.order_id}: {str(e)}")
            raise HTTPException(status_code=500, detail=str(e))

    async def get_payment(self, payment_id: int) -> Optional[PaymentResponse]:
        """결제 ID로 결제 조회"""
        try:
            logger.info(f"Fetching payment: {payment_id}")
            payment = await self.db.get(Payment, payment_id)
            
            if payment:
                logger.info(f"Payment found: {payment_id}")
                return self._convert_to_payment_response(payment)
                    
            logger.warning(f"Payment not found: {payment_id}")
            return None
                
        except Exception as e:
            logger.error(f"Error getting payment {payment_id}: {str(e)}")
            raise HTTPException(status_code=500, detail=str(e))

    async def update_payment(
        self,
        payment_id: int,
        payment_update: PaymentUpdate
    ) -> Optional[PaymentResponse]:
        """결제 상태 업데이트"""
        try:
            logger.info(f"Updating payment: {payment_id}")
            payment = await self.db.get(Payment, payment_id)
            
            if not payment:
                logger.warning(f"Payment not found for update: {payment_id}")
                return None
            
            for field, value in payment_update.dict(exclude_unset=True).items():
                setattr(payment, field, value)
            
            if payment_update.payment_status == PaymentStatus.PAID:
                payment.payment_date = datetime.utcnow()
            
            payment.updated_at = datetime.utcnow()
            await self.db.commit()
            await self.db.refresh(payment)
            
            logger.info(f"Payment updated successfully: {payment_id}")
            return self._convert_to_payment_response(payment)
            
        except Exception as e:
            logger.error(f"Error updating payment {payment_id}: {str(e)}")
            raise HTTPException(status_code=500, detail=str(e))

    async def create_transaction(self, transaction_data: TransactionCreate) -> TransactionResponse:
        """결제 트랜잭션 생성"""
        try:
            logger.info(f"Creating transaction for payment: {transaction_data.payment_id}")
            
            # JSON 데이터 직렬화
            request_json = json.dumps(transaction_data.request_data) if transaction_data.request_data else None
            response_json = json.dumps(transaction_data.response_data) if transaction_data.response_data else None
            
            transaction = PaymentTransaction(
                payment_id=transaction_data.payment_id,
                transaction_type=transaction_data.transaction_type,
                amount=transaction_data.amount,
                status=transaction_data.status,
                payment_gateway=transaction_data.payment_gateway,
                pg_transaction_id=transaction_data.pg_transaction_id,
                request_data=request_json,
                response_data=response_json
            )
            
            self.db.add(transaction)
            await self.db.commit()
            await self.db.refresh(transaction)
            
            logger.info(f"Transaction created successfully for payment: {transaction_data.payment_id}")
            return TransactionResponse.from_orm(transaction)
            
        except Exception as e:
            logger.error(f"Error creating transaction: {str(e)}")
            raise HTTPException(status_code=500, detail=str(e))

    async def get_payment_transactions(self, payment_id: int) -> List[TransactionResponse]:
        """결제의 모든 트랜잭션 조회"""
        try:
            logger.info(f"Fetching transactions for payment: {payment_id}")
            result = await self.db.execute(
                select(PaymentTransaction)
                .where(PaymentTransaction.payment_id == payment_id)
                .order_by(PaymentTransaction.created_at)
            )
            
            transactions = result.scalars().all()
            
            # JSON 데이터 역직렬화
            for transaction in transactions:
                if transaction.request_data:
                    transaction.request_data = json.loads(transaction.request_data)
                if transaction.response_data:
                    transaction.response_data = json.loads(transaction.response_data)
            
            logger.info(f"Found {len(transactions)} transactions for payment: {payment_id}")
            return [TransactionResponse.from_orm(t) for t in transactions]
            
        except Exception as e:
            logger.error(f"Error getting transactions for payment {payment_id}: {str(e)}")
            raise HTTPException(status_code=500, detail=str(e))

    async def process_payment(
        self,
        order_id: str,
        amount: float,
        payment_method: PaymentMethod,
        payment_gateway: str,
        payment_data: Dict[str, Any]
    ) -> PaymentWithTransactions:
        """결제 처리 프로세스"""
        try:
            logger.info(f"Processing payment for order: {order_id}")
            
            # 1. 결제 생성
            payment_create = PaymentCreate(
                order_id=order_id,
                amount=amount,
                currency="KRW",
                payment_method=payment_method
            )
            payment = await self.create_payment(payment_create)
            
            # 2. 외부 결제 시스템 호출 (시뮬레이션)
            logger.info(f"Calling payment gateway for payment: {payment.payment_id}")
            pg_response = {
                "success": True,
                "payment_id": f"pg_{payment.payment_id}_{datetime.now().timestamp()}",
                "status": "PAID"
            }
            
            # 3. 결제 트랜잭션 생성
            transaction_create = TransactionCreate(
                payment_id=payment.payment_id,
                transaction_type="payment",
                amount=amount,
                status="success" if pg_response["success"] else "failed",
                payment_gateway=payment_gateway,
                pg_transaction_id=pg_response.get("payment_id"),
                request_data=payment_data,
                response_data=pg_response
            )
            transaction = await self.create_transaction(transaction_create)
            
            # 4. 결제 상태 업데이트
            payment_status = PaymentStatus.PAID if pg_response["success"] else PaymentStatus.FAILED
            payment_update = PaymentUpdate(
                payment_status=payment_status,
                external_payment_id=pg_response.get("payment_id"),
                payment_date=datetime.utcnow() if pg_response["success"] else None
            )
            updated_payment = await self.update_payment(payment.payment_id, payment_update)
            
            # 5. 결제와 트랜잭션 정보를 포함한 응답 생성
            payment_with_transactions = PaymentWithTransactions(
                **updated_payment.dict(),
                transactions=[transaction]
            )
            
            logger.info(f"Payment processed successfully: {payment.payment_id}")
            return payment_with_transactions
            
        except Exception as e:
            logger.error(f"Error processing payment for order {order_id}: {str(e)}")
            raise HTTPException(status_code=500, detail=str(e))