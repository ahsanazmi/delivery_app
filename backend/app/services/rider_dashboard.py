from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.order import Order, OrderStatus
from app.models.user import User
from app.schemas.rider_dashboard import RiderDashboardResponse
from app.services.rider_service import get_or_create_delivery_partner

# The statuses between "a rider has been assigned" and "delivered" — an
# order in any of these is this rider's current, in-progress work. Mirrors
# the restaurant dashboard's own IN_FLIGHT-style grouping, scoped to the
# rider's side of the lifecycle instead of the restaurant's.
RIDER_ACTIVE_STATUSES = (OrderStatus.RIDER_ASSIGNED, OrderStatus.PICKED_UP, OrderStatus.OUT_FOR_DELIVERY)


def _today_start() -> datetime:
    return datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)


def get_rider_dashboard(db: Session, rider: User) -> RiderDashboardResponse:
    partner = get_or_create_delivery_partner(db, rider)
    today_start = _today_start()

    # "Today's deliveries" — any order this rider's had activity on today
    # (assigned, picked up, or delivered), not just ones already completed.
    # updated_at bumps on every status transition, so this catches all of it
    # without a separate join to status history.
    today_deliveries_count = db.scalar(
        select(func.count())
        .select_from(Order)
        .where(Order.rider_id == rider.id, Order.updated_at >= today_start)
    ) or 0

    # Lifetime total — a rider's overall track record, not scoped to today.
    completed_deliveries_count = db.scalar(
        select(func.count())
        .select_from(Order)
        .where(Order.rider_id == rider.id, Order.status == OrderStatus.DELIVERED)
    ) or 0

    pending_deliveries_count = db.scalar(
        select(func.count())
        .select_from(Order)
        .where(Order.rider_id == rider.id, Order.status.in_(RIDER_ACTIVE_STATUSES))
    ) or 0

    today_earnings = db.scalar(
        select(func.coalesce(func.sum(Order.delivery_fee), Decimal("0.00")))
        .where(
            Order.rider_id == rider.id,
            Order.status == OrderStatus.DELIVERED,
            Order.updated_at >= today_start,
        )
    ) or Decimal("0.00")

    current_assignment = db.scalar(
        select(Order)
        .where(Order.rider_id == rider.id, Order.status.in_(RIDER_ACTIVE_STATUSES))
        .order_by(Order.created_at.desc())
        .limit(1)
    )

    return RiderDashboardResponse(
        is_online=partner.is_online,
        today_deliveries_count=today_deliveries_count,
        completed_deliveries_count=completed_deliveries_count,
        pending_deliveries_count=pending_deliveries_count,
        today_earnings=today_earnings,
        current_assignment=current_assignment,
    )
