from datetime import timedelta
from uuid import UUID

from sqlalchemy.orm import Session

from app.models.order import Order, OrderStatus
from app.models.restaurant import Restaurant
from app.models.user import User
from app.schemas.order import OrderStatusHistoryRead
from app.schemas.tracking import OrderTrackingResponse, RiderInfo, RiderLocation

# Used only when the restaurant a historical order pointed at can no longer be
# resolved (e.g. deleted) — a sane fallback rather than no estimate at all.
DEFAULT_DELIVERY_ESTIMATE_MINUTES = 45

# A rider's live GPS is only meaningful — and only shared — once they're
# actually assigned and moving toward the customer. Before that there may be
# no rider yet; after the order leaves this set (DELIVERED/CANCELLED/REJECTED)
# the rider is likely already on an unrelated trip, so continuing to expose
# their position would leak it for no reason.
LOCATION_VISIBLE_STATUSES = {OrderStatus.RIDER_ASSIGNED, OrderStatus.PICKED_UP, OrderStatus.OUT_FOR_DELIVERY}

# Split out from services/tracking.py so it can be imported by services/orders.py
# and services/rider_location.py (to broadcast over the WebSocket after a status
# or location change) without creating an import cycle — services/tracking.py
# itself depends on services/orders.py for ownership-checked order lookups.


def build_tracking_snapshot(db: Session, order: Order) -> dict:
    rider = db.get(User, order.rider_id) if order.rider_id else None

    restaurant = None
    if order.restaurant_id:
        try:
            restaurant = db.get(Restaurant, UUID(order.restaurant_id))
        except ValueError:
            restaurant = None
    estimate_minutes = restaurant.delivery_time_minutes if restaurant else DEFAULT_DELIVERY_ESTIMATE_MINUTES
    estimated_delivery_at = order.created_at + timedelta(minutes=estimate_minutes)

    rider_location = None
    if (
        order.status in LOCATION_VISIBLE_STATUSES
        and rider is not None
        and rider.current_latitude is not None
        and rider.current_longitude is not None
        and rider.location_updated_at is not None
    ):
        rider_location = {
            "latitude": float(rider.current_latitude),
            "longitude": float(rider.current_longitude),
            "updated_at": rider.location_updated_at,
        }

    return {
        "order_id": order.id,
        "order_number": order.order_number,
        "order_status": order.status,
        "assignment_status": "assigned" if rider else "unassigned",
        "rider": rider,
        "rider_location": rider_location,
        "delivery_latitude": float(order.latitude) if order.latitude is not None else None,
        "delivery_longitude": float(order.longitude) if order.longitude is not None else None,
        "estimated_delivery_at": estimated_delivery_at,
        "status_history": sorted(order.status_history, key=lambda entry: entry.created_at),
    }


def to_tracking_response(result: dict) -> OrderTrackingResponse:
    return OrderTrackingResponse(
        order_id=result["order_id"],
        order_number=result["order_number"],
        order_status=result["order_status"],
        assignment_status=result["assignment_status"],
        rider=RiderInfo.model_validate(result["rider"]) if result["rider"] else None,
        rider_location=RiderLocation(**result["rider_location"]) if result["rider_location"] else None,
        delivery_latitude=result["delivery_latitude"],
        delivery_longitude=result["delivery_longitude"],
        estimated_delivery_at=result["estimated_delivery_at"],
        status_history=[OrderStatusHistoryRead.model_validate(entry) for entry in result["status_history"]],
    )
