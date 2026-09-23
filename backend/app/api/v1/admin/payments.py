from datetime import date
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request

from app.api.v1.deps import DbSession, require_admin
from app.models.user import User
from app.schemas.admin import (
    AdminPaymentDetail,
    AdminPaymentListResponse,
    AdminPaymentMethodValue,
    AdminPaymentStatusValue,
    AdminRefundCreateRequest,
)
from app.services.admin_payments import admin_refund_payment, get_admin_payment_detail, list_admin_payments

router = APIRouter()


@router.get("/payments", response_model=AdminPaymentListResponse)
def list_payments(
    db: DbSession,
    search: str | None = Query(default=None),
    method: AdminPaymentMethodValue | None = Query(default=None),
    status_filter: AdminPaymentStatusValue | None = Query(default=None, alias="status"),
    date_from: date | None = Query(default=None),
    date_to: date | None = Query(default=None),
    order_number: str | None = Query(default=None),
    customer: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=20, ge=1, le=100),
    current_admin: User = Depends(require_admin),
) -> AdminPaymentListResponse:
    return list_admin_payments(
        db, search=search, method_filter=method, status_filter=status_filter,
        date_from=date_from, date_to=date_to, order_number=order_number, customer=customer,
        page=page, limit=limit,
    )


# Registered after the plain list on purpose — same established convention
# as every other admin list-then-detail route pair.
@router.get("/payments/{payment_id}", response_model=AdminPaymentDetail)
def get_payment(payment_id: UUID, db: DbSession, current_admin: User = Depends(require_admin)) -> AdminPaymentDetail:
    return get_admin_payment_detail(db, payment_id)


@router.post("/payments/{payment_id}/refund", response_model=AdminPaymentDetail)
def refund_payment(
    payment_id: UUID,
    payload: AdminRefundCreateRequest,
    db: DbSession,
    request: Request,
    current_admin: User = Depends(require_admin),
) -> AdminPaymentDetail:
    ip_address = request.client.host if request.client else None
    return admin_refund_payment(db, current_admin, payment_id, payload.amount, payload.reason, ip_address)
