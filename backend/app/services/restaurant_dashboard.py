from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.order import Order, OrderStatus
from app.models.restaurant import Restaurant
from app.models.user import User
from app.services.restaurants import assert_restaurant_manager, list_restaurants_for_owner

# "Preparing" merges CONFIRMED + PREPARING — both mean "the kitchen is on it"
# from the owner's point of view. "Ready" covers everything from the moment
# food is ready until it's actually in the customer's hands — once a rider
# has it, it's out of the restaurant's control, but it isn't "completed" yet.
PREPARING_STATUSES = (OrderStatus.CONFIRMED, OrderStatus.PREPARING)
READY_STATUSES = (
    OrderStatus.READY_FOR_PICKUP,
    OrderStatus.RIDER_ASSIGNED,
    OrderStatus.PICKED_UP,
    OrderStatus.OUT_FOR_DELIVERY,
)
# Anything not yet delivered and not dead (cancelled/rejected) still
# represents revenue the restaurant hasn't been paid out for yet.
IN_FLIGHT_STATUSES = (OrderStatus.PLACED, *PREPARING_STATUSES, *READY_STATUSES)

RECENT_ORDERS_LIMIT = 10
PENDING_ORDERS_LIMIT = 20


def resolve_owner_restaurant(db: Session, owner: User, restaurant_id: UUID | None) -> Restaurant:
    """Which restaurant this dashboard call is about.

    Most owners have exactly one restaurant, so restaurant_id is optional in
    that case. An owner with several must say which one; either way, the
    restaurant is proven to actually belong to this owner before any data is
    computed for it (never trust a restaurant_id from the client at face
    value, even when it's provided).
    """
    if restaurant_id is not None:
        restaurant = db.get(Restaurant, restaurant_id)
        if not restaurant:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Restaurant not found")
        assert_restaurant_manager(restaurant, owner)
        return restaurant

    owned = list_restaurants_for_owner(db, owner.id)
    if not owned:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No restaurant found for this account")
    if len(owned) > 1:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="You manage multiple restaurants — specify restaurant_id.",
        )
    return owned[0]


def _today_start() -> datetime:
    return datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)


def _order_summaries(orders: list[Order]) -> list[dict]:
    return [
        {
            "id": order.id,
            "order_number": order.order_number,
            "status": order.status,
            "customer_name": order.customer_name,
            "total": order.total,
            "item_count": order.item_count,
            "created_at": order.created_at,
        }
        for order in orders
    ]


def get_restaurant_dashboard(db: Session, restaurant: Restaurant) -> dict:
    restaurant_id = str(restaurant.id)
    today_start = _today_start()

    today_orders_count = db.scalar(
        select(func.count())
        .select_from(Order)
        .where(Order.restaurant_id == restaurant_id, Order.created_at >= today_start)
    ) or 0

    # Payment Status Synchronization (Phase 16) — the documented rule: an
    # online (razorpay) order the customer hasn't actually paid for yet
    # isn't something the restaurant has "received" — it stays out of the
    # pending queue/count until is_paid is true. See
    # services.orders.list_restaurant_orders and accept_order() for the
    # same rule applied to the owner's full order list and the actual
    # accept action.
    payment_confirmed = ~((Order.payment_method == "razorpay") & (Order.is_paid.is_(False)))

    pending_orders_query = (
        select(Order)
        .where(Order.restaurant_id == restaurant_id, Order.status == OrderStatus.PLACED, payment_confirmed)
        .order_by(Order.created_at.asc())
        .limit(PENDING_ORDERS_LIMIT)
    )
    pending_orders = list(db.scalars(pending_orders_query))
    pending_orders_count = db.scalar(
        select(func.count())
        .select_from(Order)
        .where(Order.restaurant_id == restaurant_id, Order.status == OrderStatus.PLACED, payment_confirmed)
    ) or 0

    preparing_orders_count = db.scalar(
        select(func.count())
        .select_from(Order)
        .where(Order.restaurant_id == restaurant_id, Order.status.in_(PREPARING_STATUSES))
    ) or 0

    ready_orders_count = db.scalar(
        select(func.count())
        .select_from(Order)
        .where(Order.restaurant_id == restaurant_id, Order.status.in_(READY_STATUSES))
    ) or 0

    completed_orders_count = db.scalar(
        select(func.count())
        .select_from(Order)
        .where(
            Order.restaurant_id == restaurant_id,
            Order.status == OrderStatus.DELIVERED,
            Order.created_at >= today_start,
        )
    ) or 0

    # "Sales" is revenue actually realized today — subtotal, not total, since
    # delivery fee and tax were never the restaurant's money. "Pending
    # earnings" is the same measure for every order still in flight, any
    # day — money owed but not yet finalized by a delivery.
    today_sales = db.scalar(
        select(func.coalesce(func.sum(Order.subtotal), Decimal("0.00")))
        .where(
            Order.restaurant_id == restaurant_id,
            Order.status == OrderStatus.DELIVERED,
            Order.created_at >= today_start,
        )
    ) or Decimal("0.00")

    pending_earnings = db.scalar(
        select(func.coalesce(func.sum(Order.subtotal), Decimal("0.00")))
        .where(Order.restaurant_id == restaurant_id, Order.status.in_(IN_FLIGHT_STATUSES))
    ) or Decimal("0.00")

    recent_orders_query = (
        select(Order)
        .where(Order.restaurant_id == restaurant_id)
        .order_by(Order.created_at.desc())
        .limit(RECENT_ORDERS_LIMIT)
    )
    recent_orders = list(db.scalars(recent_orders_query))

    return {
        "restaurant_id": restaurant.id,
        "restaurant_name": restaurant.name,
        "is_open": restaurant.is_open,
        "today_orders_count": today_orders_count,
        "pending_orders_count": pending_orders_count,
        "preparing_orders_count": preparing_orders_count,
        "ready_orders_count": ready_orders_count,
        "completed_orders_count": completed_orders_count,
        "today_sales": today_sales,
        "pending_earnings": pending_earnings,
        "pending_orders": _order_summaries(pending_orders),
        "recent_orders": _order_summaries(recent_orders),
    }
