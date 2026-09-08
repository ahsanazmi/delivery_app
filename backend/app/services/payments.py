import hashlib
import hmac
from decimal import Decimal
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.order import Order
from app.models.payment import Payment, PaymentStatus


def verify_signature(payload: str, signature: str | None, secret: str) -> bool:
    if not signature:
        return False
    expected = hmac.new(secret.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)


def create_payment_record(db: Session, *, user_id: UUID, order_id: UUID, amount: Decimal, currency: str = "INR") -> Payment:
    payment = Payment(
        user_id=user_id,
        order_id=order_id,
        amount=amount,
        currency=currency,
        payment_status=PaymentStatus.PENDING,
    )
    db.add(payment)
    db.commit()
    db.refresh(payment)
    return payment


def verify_payment(db: Session, *, payment: Payment, payload: dict) -> Payment:
    signature = payload.get("signature")
    razorpay_order_id = payload.get("razorpay_order_id") or payment.razorpay_order_id
    razorpay_payment_id = payload.get("razorpay_payment_id") or payment.razorpay_payment_id
    if not razorpay_order_id or not razorpay_payment_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Missing Razorpay identifiers")

    if not settings.RAZORPAY_KEY_SECRET:
        payment.payment_status = PaymentStatus.PAID
        payment.is_verified = True
        payment.razorpay_payment_id = razorpay_payment_id
        payment.razorpay_order_id = razorpay_order_id
        payment.razorpay_signature = signature
    else:
        payload_to_verify = f"{razorpay_order_id}|{razorpay_payment_id}"
        if not verify_signature(payload_to_verify, signature, settings.RAZORPAY_KEY_SECRET):
            payment.payment_status = PaymentStatus.FAILED
            payment.failure_reason = "Signature verification failed"
            db.commit()
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Payment verification failed")
        payment.payment_status = PaymentStatus.PAID
        payment.is_verified = True
        payment.razorpay_payment_id = razorpay_payment_id
        payment.razorpay_order_id = razorpay_order_id
        payment.razorpay_signature = signature

    order = db.scalar(select(Order).where(Order.id == payment.order_id))
    if order:
        order.payment_status = "paid"
        order.is_paid = True
    db.commit()
    db.refresh(payment)
    return payment


def refund_payment(db: Session, payment: Payment, *, reason: str | None = None) -> Payment:
    payment.payment_status = PaymentStatus.REFUND_PENDING
    payment.refund_status = "requested"
    payment.failure_reason = reason
    order = db.scalar(select(Order).where(Order.id == payment.order_id))
    if order:
        order.payment_status = "refunded"
    db.commit()
    db.refresh(payment)
    return payment
