from datetime import datetime
from uuid import UUID

from sqlalchemy.orm import Session

from app.models.order import Order, OrderStatus
from app.models.user import User
from app.schemas.rider_history import RiderHistoryItemRead
from app.services.rider_deliveries import get_rider_delivery_detail

# A delivery only becomes "history" once the rider's part in it is over,
# either way it ended — successfully delivered or cancelled while assigned
# to this rider. An order still RIDER_ASSIGNED/PICKED_UP/OUT_FOR_DELIVERY is
# the dashboard's "Current Delivery," not history yet. REJECTED is excluded
# on purpose: that status is only ever reached before a rider is assigned
# (a restaurant rejecting the order), so Order.rider_id is never set on one.
RIDER_HISTORY_STATUSES = (OrderStatus.DELIVERED, OrderStatus.CANCELLED)


def _to_history_item(order: Order) -> RiderHistoryItemRead:
    return RiderHistoryItemRead(
        order_id=order.id,
        order_number=order.order_number,
        restaurant_name=order.restaurant_name or "Restaurant",
        date=order.updated_at,
        status=order.status,
        earning=order.delivery_fee,
        payment_method=order.payment_method,
    )


def list_rider_history(
    db: Session,
    rider: User,
    *,
    status_filter: OrderStatus | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    offset: int = 0,
    limit: int = 20,
) -> list[RiderHistoryItemRead]:
    query = db.query(Order).filter(Order.rider_id == rider.id, Order.status.in_(RIDER_HISTORY_STATUSES))
    if status_filter is not None:
        query = query.filter(Order.status == status_filter)
    if date_from is not None:
        query = query.filter(Order.updated_at >= date_from)
    if date_to is not None:
        query = query.filter(Order.updated_at <= date_to)

    orders = query.order_by(Order.updated_at.desc()).offset(offset).limit(limit).all()
    return [_to_history_item(order) for order in orders]


def get_rider_history_detail(db: Session, rider: User, order_id: UUID):
    """The single-record view reuses get_rider_delivery_detail wholesale —
    same ownership scoping (404 for anyone else's/nonexistent order) and,
    crucially, the same Phase 15 privacy masking, which already hides a
    delivered/cancelled order's exact customer contact details. There's no
    reason for the history detail view to be any less private than the live
    one — it's the same order, just looked up after the fact."""
    return get_rider_delivery_detail(db, rider, order_id)
