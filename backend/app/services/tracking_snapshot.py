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

# Live Rider Tracking Phase 28 — Tracking Lifecycle. Nothing further will
# ever be broadcast for an order once it reaches one of these — used to
# proactively close any lingering WebSocket connections for it (see
# services/orders.py::_broadcast_tracking_update) rather than leaving that
# entirely to a well-behaved client eventually closing its own socket.
TERMINAL_ORDER_STATUSES = {OrderStatus.DELIVERED, OrderStatus.CANCELLED, OrderStatus.REJECTED}

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
    eta_source = "static"

    rider_location = None
    if (
        order.status in LOCATION_VISIBLE_STATUSES
        and rider is not None
        and rider.current_latitude is not None
        and rider.current_longitude is not None
        and rider.location_updated_at is not None
    ):
        # Live Rider Tracking Phase 5/19/22 — imported inline to avoid a
        # circular import (rider_location.py itself imports
        # build_tracking_snapshot from this module).
        from app.services.eta import get_live_eta
        from app.services.rider_location import determine_rider_location_state

        rider_location = {
            "latitude": float(rider.current_latitude),
            "longitude": float(rider.current_longitude),
            "updated_at": rider.location_updated_at,
            "state": determine_rider_location_state(rider.location_updated_at),
        }

        # Phase 22 — a real route-based ETA replaces the static formula
        # while the rider's live position is actually available. Falls
        # back to the static estimate (untouched above) if the routing
        # provider has never successfully answered for this order yet.
        live_eta, live_source = get_live_eta(order, rider.current_latitude, rider.current_longitude)
        if live_eta is not None:
            estimated_delivery_at = live_eta
            eta_source = live_source
    else:
        # Phase 24 — an order that's left the trackable window (delivered/
        # cancelled/rejected, or not yet assigned) has no further use for
        # a cached live ETA; evict it rather than let the cache grow
        # unbounded with orders nothing will ever refresh again.
        from app.services.eta import clear_eta_cache

        clear_eta_cache(order.id)

    return {
        "order_id": order.id,
        "order_number": order.order_number,
        "order_status": order.status,
        "assignment_status": "assigned" if rider else "unassigned",
        "rider": rider,
        "rider_location": rider_location,
        # Live Rider Tracking Phase 17 — Customer Live Map. Restaurant
        # location wasn't previously surfaced to the customer tracking
        # view at all (only the rider and the delivery destination were).
        # Phase 26 — the name/address text themselves (not just pins),
        # read from the order's own snapshot fields (order.restaurant_name,
        # order.address_line/city — captured at order-creation time, same
        # as everywhere else on Order) so the customer can read "Chai
        # House" / "15 Market Road, Bengaluru" instead of only seeing an
        # unlabeled colored dot on the map.
        "restaurant_name": order.restaurant_name,
        "restaurant_latitude": float(restaurant.latitude) if restaurant else None,
        "restaurant_longitude": float(restaurant.longitude) if restaurant else None,
        "delivery_address_line": f"{order.address_line}, {order.city}",
        "delivery_latitude": float(order.latitude) if order.latitude is not None else None,
        "delivery_longitude": float(order.longitude) if order.longitude is not None else None,
        "estimated_delivery_at": estimated_delivery_at,
        # Live Rider Tracking Phase 22/23 — whether estimated_delivery_at
        # came from a real live route calculation ("live"), the static
        # creation-time+fixed-minutes formula ("static"), or neither could
        # be produced at all ("unavailable"). The client derives its own
        # Calculating/Updated/Updating/Unavailable copy from this plus
        # rider_location.state, rather than the backend trying to guess
        # what the client is currently displaying.
        "eta_source": eta_source,
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
        restaurant_name=result["restaurant_name"],
        restaurant_latitude=result["restaurant_latitude"],
        restaurant_longitude=result["restaurant_longitude"],
        delivery_address_line=result["delivery_address_line"],
        delivery_latitude=result["delivery_latitude"],
        delivery_longitude=result["delivery_longitude"],
        estimated_delivery_at=result["estimated_delivery_at"],
        eta_source=result["eta_source"],
        status_history=[OrderStatusHistoryRead.model_validate(entry) for entry in result["status_history"]],
    )
