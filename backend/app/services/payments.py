import hashlib
import hmac
import logging
from decimal import Decimal
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.core.config import settings
from app.models.notification import NotificationType
from app.models.order import Order
from app.models.payment import Payment, PaymentProvider, PaymentStatus
from app.services.notifications import notify_admins, notify_customer_payment_failed

logger = logging.getLogger(__name__)


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
    if payment.provider != PaymentProvider.RAZORPAY:
        # A customer can never mark a Cash on Delivery payment as paid — that
        # can only happen server-side when a rider/admin marks the order
        # delivered (see services.orders._settle_cod_payment_on_delivery).
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This payment is Cash on Delivery and cannot be verified online.",
        )
    signature = payload.get("signature")
    razorpay_order_id = payload.get("razorpay_order_id") or payment.razorpay_order_id
    razorpay_payment_id = payload.get("razorpay_payment_id") or payment.razorpay_payment_id
    if not razorpay_order_id or not razorpay_payment_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Missing Razorpay identifiers")

    order = db.scalar(select(Order).where(Order.id == payment.order_id))

    if not settings.RAZORPAY_KEY_SECRET:
        # Never fabricate a successful online payment. Without a configured
        # secret there is no way to actually verify anything Razorpay sent us,
        # so the honest answer is "can't verify this," not "looks good."
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Online payment verification is not configured yet.",
        )
    else:
        payload_to_verify = f"{razorpay_order_id}|{razorpay_payment_id}"
        if not verify_signature(payload_to_verify, signature, settings.RAZORPAY_KEY_SECRET):
            payment.payment_status = PaymentStatus.FAILED
            payment.failure_reason = "Signature verification failed"
            # Logging & Error Handling (Phase 26) — order/payment ids only,
            # never the signature or the RAZORPAY_KEY_SECRET used to check
            # it (payment secrets are on the never-log list).
            logger.warning(
                "Payment error: signature verification failed for payment %s (order %s)",
                payment.id, payment.order_id,
            )
            # Admin Portal Phase 20 — added before the commit below so the
            # alert persists atomically with the failure itself.
            notify_admins(
                db, NotificationType.PAYMENT_FAILURE, "Payment failure",
                f"Payment verification failed for order {payment.order_id}.", order_id=payment.order_id,
            )
            # Notification Event Integration (Phase 20) — the customer's own
            # side of the same failure, not just an admin alert.
            if order:
                notify_customer_payment_failed(
                    db, user_id=payment.user_id, order_id=payment.order_id, order_number=order.order_number,
                )
            db.commit()
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Payment verification failed")
        payment.payment_status = PaymentStatus.PAID
        payment.is_verified = True
        payment.razorpay_payment_id = razorpay_payment_id
        payment.razorpay_order_id = razorpay_order_id
        payment.razorpay_signature = signature

    if order:
        order.payment_status = "paid"
        order.is_paid = True
    db.commit()
    db.refresh(payment)
    return payment


def list_payment_methods() -> list[dict]:
    online_available = bool(settings.RAZORPAY_KEY_ID and settings.RAZORPAY_KEY_SECRET)
    return [
        {"method": "cod", "label": "Cash on Delivery", "available": True},
        {"method": "online", "label": "Pay Online", "available": online_available},
    ]


def _to_customer_payment(payment: Payment) -> dict:
    return {
        "payment_id": payment.id,
        "order_id": payment.order_id,
        # Customer Payment History (Phase 26) — the order's own
        # human-readable reference, not just its UUID, so the app can show
        # "Order ORD-..." the same way the orders list already does.
        # payment.order is always present (order_id is a NOT-NULL FK with
        # ON DELETE CASCADE — a Payment never outlives its Order), and
        # already sitting in this session's identity map from whatever
        # query produced `payment`, so this is never an extra round trip.
        "order_number": payment.order.order_number,
        "amount": payment.amount,
        "method": "cod" if payment.provider == PaymentProvider.COD else "online",
        "status": payment.payment_status,
        "transaction_reference": payment.razorpay_payment_id or payment.razorpay_order_id,
        "created_at": payment.created_at,
        "updated_at": payment.updated_at,
        # Razorpay Order Creation (Phase 12) — the mobile app's Razorpay
        # Checkout SDK needs this public key_id to open the payment sheet
        # for the provider order_id already returned as
        # transaction_reference above. None for COD (nothing to check out)
        # and None if Razorpay simply isn't configured, rather than an
        # empty string — settings.RAZORPAY_KEY_ID defaults to "".
        "razorpay_key_id": (settings.RAZORPAY_KEY_ID or None) if payment.provider == PaymentProvider.RAZORPAY else None,
    }


def list_customer_payments(db: Session, user_id: UUID, *, offset: int = 0, limit: int = 20) -> list[dict]:
    """Customer Payment History (Phase 26) — every payment ever opened for
    an order this customer placed, newest first. Scoped by
    Payment.user_id, the same column every other customer-facing payment
    endpoint in this router already filters/checks ownership on (see
    _get_owned_payment_or_404 in app/api/v1/endpoints/payments.py) — a
    customer can only ever see their own payments, never another
    customer's, by construction of the query itself, not a post-hoc
    check. joinedload(Payment.order) avoids an N+1 for order_number
    (see _to_customer_payment's own note) across a whole page of rows,
    the same reasoning list_user_orders already applies to its own
    relationships.
    """
    payments = (
        db.query(Payment)
        .options(joinedload(Payment.order))
        .filter(Payment.user_id == user_id)
        .order_by(Payment.created_at.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )
    return [_to_customer_payment(payment) for payment in payments]


def record_order_payment(db: Session, user_id: UUID, order_id: UUID) -> dict:
    """Create (or return the existing) payment record for an order.

    Checkout Payment Decision (Phase 6) — the method is never taken from
    the client here either; it's derived from the order's own
    `payment_method`, which was fixed at order-creation time and already
    validated there (create_order() refuses to open a "razorpay" order at
    all if online payment isn't actually configured). Delegates to
    PaymentService (Payment System Phase 4/5) for both methods now,
    rather than this function's own previous hand-rolled COD-only path —
    for "razorpay" this makes a real call to open a Razorpay order; for
    "cod" it's the same simple record-keeping insert as before.
    """
    from app.services.payment.exceptions import PaymentError, ProviderNotConfiguredError, ProviderRequestError
    from app.services.payment.payment_service import PaymentService

    order = db.query(Order).filter(Order.id == order_id, Order.user_id == user_id).first()
    if not order:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Order not found")

    service = PaymentService()
    try:
        payment = service.create_payment_for_order(db, order=order, method=order.payment_method)
    except ProviderNotConfiguredError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc
    except ProviderRequestError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail="Unable to reach the payment provider right now."
        ) from exc
    except PaymentError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return _to_customer_payment(payment)
