from datetime import date, datetime, time
from decimal import Decimal
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from app.models.order import Order, OrderStatus
from app.models.user import User, UserRole
from app.schemas.admin import (
    AdminCustomerDetail,
    AdminCustomerListResponse,
    AdminCustomerStatus,
    AdminCustomerSummary,
    AdminRecentOrder,
)
from app.services.admin_account_status import set_user_active_status

_ZERO = Decimal("0.00")
RECENT_ORDERS_LIMIT = 20


def _status_to_is_active(value: AdminCustomerStatus) -> bool:
    return value == "ACTIVE"


def _is_active_to_status(is_active: bool) -> AdminCustomerStatus:
    return "ACTIVE" if is_active else "SUSPENDED"


def _order_stats_by_customer(db: Session, user_ids: list[UUID]) -> dict[UUID, tuple[int, Decimal]]:
    """Batch-fetch {user_id: (order_count, total_spending)} for exactly the
    given ids in one query — avoids an N+1 of one aggregate query per row
    on the customer list page (same discipline as Phase 30's rider fixes)."""
    if not user_ids:
        return {}
    rows = db.execute(
        select(
            Order.user_id,
            func.count(Order.id),
            func.coalesce(func.sum(case((Order.status == OrderStatus.DELIVERED, Order.total), else_=_ZERO)), _ZERO),
        )
        .where(Order.user_id.in_(user_ids))
        .group_by(Order.user_id)
    ).all()
    return {user_id: (count, spending) for user_id, count, spending in rows}


def list_admin_customers(
    db: Session,
    *,
    search: str | None,
    status_filter: AdminCustomerStatus | None,
    registered_after: date | None,
    registered_before: date | None,
    page: int,
    limit: int,
) -> AdminCustomerListResponse:
    conditions = [User.role == UserRole.CUSTOMER]
    if search:
        pattern = f"%{search.strip()}%"
        conditions.append((User.name.ilike(pattern)) | (User.email.ilike(pattern)) | (User.phone.ilike(pattern)))
    if status_filter is not None:
        conditions.append(User.is_active.is_(_status_to_is_active(status_filter)))
    if registered_after is not None:
        conditions.append(User.created_at >= datetime.combine(registered_after, time.min))
    if registered_before is not None:
        conditions.append(User.created_at <= datetime.combine(registered_before, time.max))

    total = db.scalar(select(func.count()).select_from(User).where(*conditions)) or 0

    offset = (page - 1) * limit
    customers = db.scalars(
        select(User).where(*conditions).order_by(User.created_at.desc()).offset(offset).limit(limit)
    ).all()

    stats = _order_stats_by_customer(db, [customer.id for customer in customers])
    items = [
        AdminCustomerSummary(
            id=customer.id,
            name=customer.name,
            email=customer.email,
            phone=customer.phone,
            status=_is_active_to_status(customer.is_active),
            created_at=customer.created_at,
            order_count=stats.get(customer.id, (0, _ZERO))[0],
            total_spending=stats.get(customer.id, (0, _ZERO))[1],
        )
        for customer in customers
    ]
    return AdminCustomerListResponse(items=items, total=total, page=page, limit=limit)


def _get_customer_or_404(db: Session, customer_id: UUID) -> User:
    customer = db.get(User, customer_id)
    if not customer or customer.role != UserRole.CUSTOMER:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Customer not found")
    return customer


def get_admin_customer_detail(db: Session, customer_id: UUID) -> AdminCustomerDetail:
    customer = _get_customer_or_404(db, customer_id)
    order_count, total_spending = _order_stats_by_customer(db, [customer.id]).get(customer.id, (0, _ZERO))

    recent_orders = db.scalars(
        select(Order).where(Order.user_id == customer.id).order_by(Order.created_at.desc()).limit(RECENT_ORDERS_LIMIT)
    )
    return AdminCustomerDetail(
        id=customer.id,
        name=customer.name,
        email=customer.email,
        phone=customer.phone,
        status=_is_active_to_status(customer.is_active),
        created_at=customer.created_at,
        order_count=order_count,
        total_spending=total_spending,
        recent_orders=[
            AdminRecentOrder(
                id=order.id,
                order_number=order.order_number,
                restaurant_name=order.restaurant_name,
                customer_name=order.customer_name,
                status=order.status,
                total=order.total,
                created_at=order.created_at,
            )
            for order in recent_orders
        ],
    )


def suspend_admin_customer(
    db: Session, admin: User, customer_id: UUID, reason: str, ip_address: str | None = None
) -> AdminCustomerDetail:
    customer = _get_customer_or_404(db, customer_id)
    set_user_active_status(
        db, admin, customer, target_active=False, action="customer.suspend", target_type="customer",
        reason=reason, ip_address=ip_address,
    )
    db.commit()
    db.refresh(customer)
    return get_admin_customer_detail(db, customer_id)


def activate_admin_customer(
    db: Session, admin: User, customer_id: UUID, reason: str, ip_address: str | None = None
) -> AdminCustomerDetail:
    customer = _get_customer_or_404(db, customer_id)
    set_user_active_status(
        db, admin, customer, target_active=True, action="customer.activate", target_type="customer",
        reason=reason, ip_address=ip_address,
    )
    db.commit()
    db.refresh(customer)
    return get_admin_customer_detail(db, customer_id)
