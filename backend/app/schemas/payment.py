from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.models.payment import PaymentProvider, PaymentStatus


class PaymentCreate(BaseModel):
    order_id: UUID
    amount: Decimal = Field(gt=0)
    currency: str = "INR"
    provider: PaymentProvider = PaymentProvider.RAZORPAY


class PaymentVerify(BaseModel):
    payment_id: str | None = None
    order_id: UUID | None = None
    razorpay_order_id: str | None = None
    razorpay_payment_id: str | None = None
    signature: str | None = None


class PaymentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    order_id: UUID
    user_id: UUID
    provider: PaymentProvider
    payment_status: PaymentStatus
    amount: Decimal
    currency: str
    razorpay_order_id: str | None
    razorpay_payment_id: str | None
    is_verified: bool
    failure_reason: str | None
    refund_id: str | None
    refund_status: str | None
    created_at: datetime
    updated_at: datetime
