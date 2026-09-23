from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.order import Order
from app.models.rider_location import RiderLocationPing
from app.models.user import User
from app.schemas.rider import RiderLocationRead
from app.services.rider_dashboard import RIDER_ACTIVE_STATUSES
from app.services.rider_service import get_or_create_delivery_partner
from app.services.tracking_snapshot import LOCATION_VISIBLE_STATUSES, build_tracking_snapshot, to_tracking_response
from app.ws.manager import manager

# A rider's device can report far more often than this table needs to keep.
# The mobile app's own foreground interval is ~12s (see
# rider-mobile/features/location/use-location-reporter.ts); this floor just
# makes sure nothing — a buggy client, a background task with a shorter
# interval than intended — can turn one rider's shift into thousands of
# near-duplicate history rows. The "current position" cache on User is
# refreshed on every accepted call regardless, so tracking freshness for
# available-deliveries distance and the customer's live map is unaffected.
MIN_LOCATION_PING_INTERVAL_SECONDS = 10


def _is_eligible_for_location_tracking(db: Session, rider: User) -> bool:
    """Mirrors the frontend's own rule ("only transmit when ONLINE or
    RIDER has an active delivery") server-side, as defense in depth rather
    than trusting the client to only call this while it should. Not an
    error path — see update_rider_location, an ineligible call is simply a
    no-op, since a stray report arriving just after a rider went offline
    isn't a client bug worth surfacing."""
    partner = get_or_create_delivery_partner(db, rider)
    if partner.is_online:
        return True
    has_active_delivery = db.scalar(
        select(Order.id).where(Order.rider_id == rider.id, Order.status.in_(RIDER_ACTIVE_STATUSES)).limit(1)
    )
    return has_active_delivery is not None


def _to_location_read(rider: User) -> RiderLocationRead:
    return RiderLocationRead(
        latitude=rider.current_latitude,
        longitude=rider.current_longitude,
        accuracy=rider.current_accuracy,
        heading=rider.current_heading,
        speed=rider.current_speed,
        updated_at=rider.location_updated_at,
    )


def update_rider_location(
    db: Session,
    rider: User,
    latitude: Decimal,
    longitude: Decimal,
    accuracy: Decimal | None = None,
    heading: Decimal | None = None,
    speed: Decimal | None = None,
) -> RiderLocationRead:
    if not _is_eligible_for_location_tracking(db, rider):
        return _to_location_read(rider)

    now = datetime.now(UTC)
    rider.current_latitude = latitude
    rider.current_longitude = longitude
    rider.current_accuracy = accuracy
    rider.current_heading = heading
    rider.current_speed = speed
    rider.location_updated_at = now

    last_recorded_at = db.scalar(
        select(RiderLocationPing.recorded_at)
        .where(RiderLocationPing.rider_id == rider.id)
        .order_by(RiderLocationPing.recorded_at.desc())
        .limit(1)
    )
    # SQLite (used by the fast test suite) doesn't round-trip tzinfo on a
    # DateTime(timezone=True) column the way Postgres does — normalize
    # before subtracting so this works identically on both.
    if last_recorded_at is not None and last_recorded_at.tzinfo is None:
        last_recorded_at = last_recorded_at.replace(tzinfo=UTC)
    if last_recorded_at is None or (now - last_recorded_at) >= timedelta(seconds=MIN_LOCATION_PING_INTERVAL_SECONDS):
        db.add(
            RiderLocationPing(
                rider_id=rider.id,
                latitude=latitude,
                longitude=longitude,
                accuracy=accuracy,
                heading=heading,
                speed=speed,
            )
        )

    db.commit()
    db.refresh(rider)

    # Push the new position to every order this rider is actively delivering
    # (normally at most one) — but only orders whose status makes rider
    # location visible at all; anything else stays silent.
    active_orders = db.scalars(
        select(Order).where(Order.rider_id == rider.id, Order.status.in_(LOCATION_VISIBLE_STATUSES))
    )
    for order in active_orders:
        snapshot = build_tracking_snapshot(db, order)
        manager.broadcast(order.id, to_tracking_response(snapshot).model_dump(mode="json"))

    return _to_location_read(rider)
