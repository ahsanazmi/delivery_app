from datetime import date, datetime, time
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.order import Order, OrderStatus
from app.models.user import User
from app.schemas.admin import AdminOrderDetail, AdminOrderListResponse, AdminOrderSummary
from app.schemas.order import OrderItemRead, OrderStatusHistoryRead


def _riders_by_id(db: Session, rider_ids: list[UUID]) -> dict[UUID, User]:
    if not rider_ids:
        return {}
    riders = db.scalars(select(User).where(User.id.in_(rider_ids))).all()
    return {rider.id: rider for rider in riders}


def _to_summary(order: Order, rider: User | None) -> AdminOrderSummary:
    return AdminOrderSummary(
        id=order.id,
        order_number=order.order_number,
        customer_name=order.customer_name,
        restaurant_name=order.restaurant_name,
        rider_name=rider.name if rider else None,
        status=order.status,
        payment_method=order.payment_method,
        payment_status=order.payment_status,
        subtotal=order.subtotal,
        delivery_fee=order.delivery_fee,
        tax=order.tax,
        discount=order.discount,
        total=order.total,
        created_at=order.created_at,
    )


def list_admin_orders(
    db: Session,
    *,
    search: str | None,
    status_filter: OrderStatus | None,
    payment_method: str | None,
    payment_status: str | None,
    date_from: date | None,
    date_to: date | None,
    page: int,
    limit: int,
) -> AdminOrderListResponse:
    # The one join needed: rider name isn't denormalized onto Order the way
    # customer_name/restaurant_name are, so matching "Rider" in the search
    # box (and displaying it) requires joining to User via the real FK.
    base = select(Order).outerjoin(User, User.id == Order.rider_id)

    conditions = []
    if search:
        pattern = f"%{search.strip()}%"
        conditions.append(
            Order.order_number.ilike(pattern)
            | Order.customer_name.ilike(pattern)
            | Order.restaurant_name.ilike(pattern)
            | User.name.ilike(pattern)
        )
    if status_filter is not None:
        conditions.append(Order.status == status_filter)
    if payment_method:
        conditions.append(Order.payment_method == payment_method)
    if payment_status:
        conditions.append(Order.payment_status == payment_status)
    if date_from is not None:
        conditions.append(Order.created_at >= datetime.combine(date_from, time.min))
    if date_to is not None:
        conditions.append(Order.created_at <= datetime.combine(date_to, time.max))

    base = base.where(*conditions)
    total = db.scalar(select(func.count()).select_from(base.subquery())) or 0

    offset = (page - 1) * limit
    orders = db.scalars(base.order_by(Order.created_at.desc()).offset(offset).limit(limit)).all()

    riders = _riders_by_id(db, [order.rider_id for order in orders if order.rider_id])
    items = [_to_summary(order, riders.get(order.rider_id)) for order in orders]
    return AdminOrderListResponse(items=items, total=total, page=page, limit=limit)


def get_admin_order_detail(db: Session, order_id: UUID) -> AdminOrderDetail:
    order = db.get(Order, order_id)
    if not order:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Order not found")
    rider = db.get(User, order.rider_id) if order.rider_id else None

    summary = _to_summary(order, rider)
    sorted_history = sorted(order.status_history, key=lambda entry: entry.created_at)
    return AdminOrderDetail(
        **summary.model_dump(),
        customer_email=order.customer_email,
        customer_phone=order.customer_phone,
        restaurant_phone=order.restaurant_phone,
        restaurant_address=order.restaurant_address,
        items=[OrderItemRead.model_validate(item) for item in order.items],
        status_history=[OrderStatusHistoryRead.model_validate(entry) for entry in sorted_history],
    )
