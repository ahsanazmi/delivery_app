from uuid import UUID

from fastapi import APIRouter, HTTPException, Request, status

from app.api.v1.deps import CurrentUser, DbSession
from app.core.config import settings
from app.models.order import Order
from app.models.payment import Payment, PaymentStatus
from app.schemas.payment import PaymentCreate, PaymentRead, PaymentVerify
from app.services.payments import create_payment_record, refund_payment, verify_payment

router = APIRouter()


@router.post("", response_model=PaymentRead, status_code=status.HTTP_201_CREATED)
def create_payment(payload: PaymentCreate, db: DbSession, current_user: CurrentUser) -> PaymentRead:
    order = db.get(Order, payload.order_id)
    if not order or order.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Order not found")

    payment = create_payment_record(db, user_id=current_user.id, order_id=payload.order_id, amount=payload.amount, currency=payload.currency)
    payment.provider = payload.provider
    if settings.RAZORPAY_KEY_ID:
        payment.razorpay_order_id = f"order_{payment.id}"
        payment.payment_status = PaymentStatus.PENDING
    else:
        payment.razorpay_order_id = "mock_razorpay_order"
    db.commit()
    db.refresh(payment)
    return payment


@router.post("/verify", response_model=PaymentRead)
def verify_payment_endpoint(payload: PaymentVerify, db: DbSession, current_user: CurrentUser) -> PaymentRead:
    payment = db.query(Payment).filter(Payment.order_id == payload.order_id, Payment.user_id == current_user.id).first()
    if not payment:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Payment not found")
    return verify_payment(db, payment=payment, payload=payload.model_dump())


@router.post("/webhook", status_code=status.HTTP_200_OK)
def razorpay_webhook(request: Request, db: DbSession) -> dict[str, str]:
    body = request.body()
    signature = request.headers.get("x-razorpay-signature")
    if not signature:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Missing Razorpay signature")

    event = request.headers.get("x-razorpay-event")
    if event == "payment.authorized":
        return {"status": "accepted"}

    if body:
        payload = body.decode("utf-8")
        if settings.RAZORPAY_KEY_SECRET and not signature:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid webhook signature")
        return {"status": "received", "message": "Webhook accepted for processing"}
    return {"status": "received"}


@router.post("/{payment_id}/refund", response_model=PaymentRead)
def refund_payment_endpoint(payment_id: UUID, db: DbSession, current_user: CurrentUser, reason: str | None = None) -> PaymentRead:
    payment = db.get(Payment, payment_id)
    if not payment or payment.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Payment not found")
    return refund_payment(db, payment, reason=reason)
