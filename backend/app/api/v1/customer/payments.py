from uuid import UUID

from fastapi import APIRouter, Depends, Query

from app.api.v1.deps import DbSession, require_customer
from app.models.user import User
from app.schemas.payment import CustomerPaymentRead, PaymentMethodOption
from app.services.payments import list_customer_payments, list_payment_methods, record_order_payment

router = APIRouter()


@router.get("/payment-methods", response_model=list[PaymentMethodOption])
def get_payment_methods(db: DbSession, current_user: User = Depends(require_customer)) -> list[PaymentMethodOption]:
    return [PaymentMethodOption(**method) for method in list_payment_methods()]


@router.get("/payments", response_model=list[CustomerPaymentRead])
def get_payment_history(
    db: DbSession,
    current_user: User = Depends(require_customer),
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=20, ge=1, le=100),
) -> list[CustomerPaymentRead]:
    """Customer Payment History (Phase 26). Authenticate: require_customer.
    Ownership: list_customer_payments filters by Payment.user_id — a
    customer can only ever see their own payments, the same guarantee
    every other payment endpoint on this router already enforces."""
    offset = (page - 1) * limit
    payments = list_customer_payments(db, current_user.id, offset=offset, limit=limit)
    return [CustomerPaymentRead(**payment) for payment in payments]


@router.post("/orders/{order_id}/payment", response_model=CustomerPaymentRead)
def record_payment(order_id: UUID, db: DbSession, current_user: User = Depends(require_customer)) -> CustomerPaymentRead:
    result = record_order_payment(db, current_user.id, order_id)
    return CustomerPaymentRead(**result)
