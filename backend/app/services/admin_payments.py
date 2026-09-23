from datetime import date, datetime, time
from decimal import Decimal
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.order import Order, OrderStatus
from app.models.payment import Payment, PaymentProvider, PaymentStatus
from app.models.refund import Refund, RefundStatus
from app.models.user import User
from app.schemas.admin import (
    AdminPaymentDetail,
    AdminPaymentListResponse,
    AdminPaymentMethodValue,
    AdminPaymentStatusValue,
    AdminPaymentSummary,
    AdminRefundRecord,
)
from app.services.admin_audit_log import record_admin_audit_log
from app.services.payment.exceptions import RefundError
from app.services.payment.payment_service import PaymentService

_ZERO = Decimal("0.00")


def _derived_status(payment: Payment, order_status: OrderStatus) -> AdminPaymentStatusValue:
    if payment.payment_status == PaymentStatus.PENDING and order_status == OrderStatus.CANCELLED:
        return "CANCELLED"
    return payment.payment_status.value.upper()  # type: ignore[return-value]


def _transaction_reference(payment: Payment) -> str | None:
    # Never the signature (see this phase's "never expose secret
    # payment-provider credentials") — just enough to look the payment up
    # on the provider's own dashboard if needed.
    return payment.razorpay_payment_id or payment.razorpay_order_id


def _provider_name(payment: Payment) -> str | None:
    # Admin Payment Management (Phase 27) — distinct from `method`; see
    # AdminPaymentSummary.provider's own note. COD has no external
    # provider at all, so None (not "cod") is the honest answer here.
    return "Razorpay" if payment.provider == PaymentProvider.RAZORPAY else None


def _latest_refund_status(refunds: list) -> str | None:
    if not refunds:
        return None
    return max(refunds, key=lambda r: r.created_at).status.value


def _to_summary(payment: Payment, order: Order, *, latest_refund_status: str | None = None) -> AdminPaymentSummary:
    return AdminPaymentSummary(
        id=payment.id,
        order_id=payment.order_id,
        order_number=order.order_number,
        customer_name=order.customer_name,
        amount=payment.amount,
        method=payment.provider.value,  # type: ignore[arg-type]
        provider=_provider_name(payment),
        status=_derived_status(payment, order.status),
        transaction_reference=_transaction_reference(payment),
        latest_refund_status=latest_refund_status,
        created_at=payment.created_at,
        paid_at=payment.paid_at,
    )


def list_admin_payments(
    db: Session,
    *,
    search: str | None,
    method_filter: AdminPaymentMethodValue | None,
    status_filter: AdminPaymentStatusValue | None,
    date_from: date | None,
    date_to: date | None,
    order_number: str | None = None,
    customer: str | None = None,
    page: int,
    limit: int,
) -> AdminPaymentListResponse:
    conditions = []
    if method_filter is not None:
        conditions.append(Payment.provider == PaymentProvider(method_filter))
    if date_from is not None:
        conditions.append(Payment.created_at >= datetime.combine(date_from, time.min))
    if date_to is not None:
        conditions.append(Payment.created_at <= datetime.combine(date_to, time.max))
    if status_filter is not None:
        if status_filter == "CANCELLED":
            conditions.append(Payment.payment_status == PaymentStatus.PENDING)
            conditions.append(Order.status == OrderStatus.CANCELLED)
        else:
            conditions.append(Payment.payment_status == PaymentStatus(status_filter.lower()))
            if status_filter == "PENDING":
                # A PENDING payment whose order is CANCELLED is displayed
                # (and filterable) as CANCELLED instead — don't double-list it.
                conditions.append(Order.status != OrderStatus.CANCELLED)
    # Admin Payment Management (Phase 27) — explicit, dedicated Order ID /
    # Customer filters, additive alongside the existing combined `search`
    # (unchanged, still covers transaction-reference lookups too) rather
    # than replacing it, so nothing already depending on `search` breaks.
    if order_number:
        conditions.append(Order.order_number.ilike(f"%{order_number.strip()}%"))
    if customer:
        pattern = f"%{customer.strip()}%"
        conditions.append(Order.customer_name.ilike(pattern) | Order.customer_email.ilike(pattern))

    base = select(Payment, Order).join(Order, Order.id == Payment.order_id).where(*conditions)
    if search:
        pattern = f"%{search.strip()}%"
        base = base.where(
            Order.order_number.ilike(pattern)
            | Order.customer_name.ilike(pattern)
            | Payment.razorpay_payment_id.ilike(pattern)
            | Payment.razorpay_order_id.ilike(pattern)
        )

    total = db.scalar(select(func.count()).select_from(base.subquery())) or 0

    offset = (page - 1) * limit
    rows = db.execute(base.order_by(Payment.created_at.desc()).offset(offset).limit(limit)).all()

    # Batched, not per-row — one extra query for the whole page rather
    # than an N+1 lazy-load of payment.refunds per row (the same
    # reasoning list_user_orders' own selectinload already applies to its
    # relationships). Refund rows are globally sorted by created_at desc,
    # so the first one seen per payment_id is necessarily that payment's
    # own most recent refund.
    payment_ids = [payment.id for payment, _ in rows]
    latest_refund_status_by_payment: dict = {}
    if payment_ids:
        refund_rows = db.execute(
            select(Refund.payment_id, Refund.status)
            .where(Refund.payment_id.in_(payment_ids))
            .order_by(Refund.created_at.desc())
        ).all()
        for payment_id, refund_status in refund_rows:
            latest_refund_status_by_payment.setdefault(payment_id, refund_status.value)

    items = [
        _to_summary(payment, order, latest_refund_status=latest_refund_status_by_payment.get(payment.id))
        for payment, order in rows
    ]
    return AdminPaymentListResponse(items=items, total=total, page=page, limit=limit)


def _refund_records(payment: Payment) -> list[AdminRefundRecord]:
    return [
        AdminRefundRecord(
            id=r.id, amount=r.amount, status=r.status.value, provider_refund_id=r.provider_refund_id,
            reason=r.reason, created_at=r.created_at,
        )
        for r in sorted(payment.refunds, key=lambda r: r.created_at, reverse=True)
    ]


def _refunded_amount(payment: Payment) -> Decimal:
    """Genuinely settled money only — matches
    refund_service.py's own _SETTLED_REFUND_STATUSES / what
    recompute_payment_refund_status() bases the Payment's own status on.
    Never counts a refund still PROCESSING at the provider as "already
    refunded" — it hasn't actually gone back to the customer yet."""
    return sum((r.amount for r in payment.refunds if r.status == RefundStatus.COMPLETED), _ZERO)


def _refundable_amount(payment: Payment) -> Decimal:
    """Refund E2E Test (Phase 36) — a real, previously-hidden bug: this
    used to be `payment.amount - _refunded_amount(payment)`, which only
    excluded genuinely COMPLETED refunds — a refund still PROCESSING at
    the provider (Phase 24's own honest "not yet confirmed settled"
    state) was invisible to this figure entirely, so the admin-facing
    "refundable_amount" could show more than a real refund attempt would
    actually be allowed to take. refund_service.create_refund()'s own
    validation was always correct (it uses _COMMITTED_REFUND_STATUSES —
    COMPLETED + PROCESSING — for exactly this reason); only this
    display-facing figure had drifted out of sync with it. Matches that
    same set now, so what the admin is told is refundable is always
    exactly what a new refund request would actually be allowed to
    take."""
    committed = sum((r.amount for r in payment.refunds if r.status in (RefundStatus.COMPLETED, RefundStatus.PROCESSING)), _ZERO)
    return payment.amount - committed


def get_admin_payment_detail(db: Session, payment_id: UUID) -> AdminPaymentDetail:
    payment = db.get(Payment, payment_id)
    if not payment:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Payment not found")
    order = db.get(Order, payment.order_id)
    if not order:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Order not found")
    rider = db.get(User, payment.collected_by_rider_id) if payment.collected_by_rider_id else None

    refunded_amount = _refunded_amount(payment)
    summary = _to_summary(payment, order, latest_refund_status=_latest_refund_status(payment.refunds))
    return AdminPaymentDetail(
        **summary.model_dump(),
        customer_email=order.customer_email,
        currency=payment.currency,
        is_verified=payment.is_verified,
        failure_reason=payment.failure_reason,
        collected_by_rider_name=rider.name if rider else None,
        collected_at=payment.collected_at,
        updated_at=payment.updated_at,
        refunded_amount=refunded_amount,
        refundable_amount=_refundable_amount(payment),
        refunds=_refund_records(payment),
    )


def admin_refund_payment(
    db: Session, admin: User, payment_id: UUID, amount: Decimal, reason: str, ip_address: str | None = None,
) -> AdminPaymentDetail:
    """Refund Architecture (Phase 23) — the single, controlled entry point
    for an admin-issued refund. Every validation this phase names is
    enforced by the layer it actually belongs to:

    - Payment is refundable / refund amount <= refundable amount / never
      exceeds captured minus previous refunds — refund_service.create_refund()'s
      own job (Phase 4), now also lock-guarded against a concurrent
      double-refund (Phase 23's own fix there).
    - Order state — fetched and included in the audit log's own record
      for every refund, so *why* an order was in whatever state it was in
      when refunded is always answerable later. Deliberately not used to
      *block* a refund: there's no order status a legitimate refund
      reason (a quality complaint on a DELIVERED order, an item swap
      mid-PREPARING, or Phase 22's own REFUND_PENDING reconciliation flow
      for a CANCELLED order) doesn't already cover.
    - Previous refunds — the same real, append-only Refund history
      returned by get_admin_payment_detail(), never a single mutable
      total.
    """
    payment = db.get(Payment, payment_id)
    if not payment:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Payment not found")
    order = db.get(Order, payment.order_id)
    if not order:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Order not found")

    refunded_before = _refunded_amount(payment)
    service = PaymentService()
    try:
        service.refund(db, payment=payment, amount=amount, reason=reason)
    except RefundError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc

    db.refresh(payment)
    refunded_after = _refunded_amount(payment)
    record_admin_audit_log(
        db, admin_id=admin.id, action="payment.refund", target_type="payment", target_id=str(payment.id),
        reason=reason, previous_state=f"order={order.status.value} refunded={refunded_before}",
        new_state=f"refunded={refunded_after}", ip_address=ip_address,
    )
    db.commit()

    return get_admin_payment_detail(db, payment_id)
