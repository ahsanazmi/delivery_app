import logging
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Literal

from fastapi import HTTPException, status
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.observability import log_event
from app.models.delivery_assignment import DeliveryAssignment
from app.models.order import Order
from app.models.rider_location import RiderLocationPing
from app.models.user import User
from app.schemas.rider import RiderLocationRead
from app.services import location_service
from app.services.notifications import maybe_notify_rider_approaching
from app.services.rider_dashboard import RIDER_ACTIVE_STATUSES
from app.services.rider_service import get_or_create_delivery_partner
from app.services.tracking_snapshot import LOCATION_VISIBLE_STATUSES, build_tracking_snapshot, to_tracking_response
from app.ws.manager import manager

# Live Rider Tracking Phase 5 — this module is the RiderLocationService the
# phase asks for (kept as a plain module of functions, this codebase's own
# established convention for every other "service" — see checkout.py,
# rider_deliveries.py, etc. — rather than introducing an OOP class this
# project doesn't otherwise use). Its responsibilities, each below: resolve
# the rider's active assignment/order, validate eligibility, validate
# coordinates (at the schema layer — RiderLocationUpdate), validate
# timestamps, detect implausible movement, update the latest-location
# cache and throttled history, determine stale state, and publish the
# realtime event.

logger = logging.getLogger(__name__)

RiderLocationState = Literal["live", "stale", "offline"]


def determine_rider_location_state(location_updated_at: datetime | None, *, now: datetime | None = None) -> RiderLocationState:
    """Live Rider Tracking Phase 5/19 — LIVE/STALE/OFFLINE, computed from a
    position's own age against the configured thresholds. See
    docs/live-tracking-architecture.md §5 for the reasoning behind the
    specific numbers."""
    if location_updated_at is None:
        return "offline"
    now = now or datetime.now(UTC)
    if location_updated_at.tzinfo is None:
        location_updated_at = location_updated_at.replace(tzinfo=UTC)
    age_seconds = (now - location_updated_at).total_seconds()
    if age_seconds < settings.RIDER_LOCATION_STALE_AFTER_SECONDS:
        return "live"
    if age_seconds < settings.RIDER_LOCATION_OFFLINE_AFTER_SECONDS:
        return "stale"
    return "offline"


def get_active_assignment_context(db: Session, rider: User) -> tuple[Order | None, DeliveryAssignment | None]:
    """The rider's own current active delivery, if any — at most one such
    order exists per rider by construction (a rider can't accept a new
    delivery while already holding one — enforced elsewhere, not here).
    Used both to decide eligibility and to tag a ping with which specific
    delivery it belonged to."""
    order = db.scalar(select(Order).where(Order.rider_id == rider.id, Order.status.in_(RIDER_ACTIVE_STATUSES)))
    if order is None:
        return None, None
    assignment = db.scalar(
        select(DeliveryAssignment).where(DeliveryAssignment.order_id == order.id, DeliveryAssignment.rider_id == rider.id)
    )
    return order, assignment


def _to_location_read(rider: User) -> RiderLocationRead:
    return RiderLocationRead(
        latitude=rider.current_latitude,
        longitude=rider.current_longitude,
        accuracy=rider.current_accuracy,
        heading=rider.current_heading,
        speed=rider.current_speed,
        updated_at=rider.location_updated_at,
    )


def _reject_implausible_timestamp(rider_id, captured_at: datetime | None, now: datetime) -> None:
    """Live Rider Tracking Phase 6/8 — "do not blindly trust client
    timestamps... reject invalid timestamps." Rejects the whole update
    (never silently substitutes the server's own time) when the client's
    claimed capture time is further from now than a generous bound in
    either direction — a wildly wrong device clock is itself a signal
    something is off with this report, not something to paper over."""
    if captured_at is None:
        return
    ts = captured_at if captured_at.tzinfo is not None else captured_at.replace(tzinfo=UTC)
    delta_seconds = (now - ts).total_seconds()
    too_old = delta_seconds > settings.RIDER_LOCATION_MAX_TIMESTAMP_AGE_SECONDS
    too_far_future = delta_seconds < -settings.RIDER_LOCATION_MAX_TIMESTAMP_FUTURE_SECONDS
    if too_old or too_far_future:
        log_event(logger, "location_rejected", rider_id=rider_id, reason="implausible_timestamp")
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Reported location timestamp is not plausible."
        )


def _is_implausible_movement(rider: User, latitude: Decimal, longitude: Decimal, accuracy: Decimal | None, now: datetime) -> bool:
    """Live Rider Tracking Phase 8 — GPS Accuracy Filtering. Deliberately
    conservative: rejects only when poor accuracy AND an implausible
    implied speed both hold at once, never on either alone, so a single
    poor-accuracy point from a stationary rider is never rejected just for
    that, and a large but achievable jump (a real highway) is never
    rejected just for that either. Nothing to compare against yet (a
    rider's very first point) is never implausible."""
    if rider.current_latitude is None or rider.current_longitude is None or rider.location_updated_at is None:
        return False
    if accuracy is None or accuracy <= Decimal(str(settings.RIDER_LOCATION_MAX_ACCEPTED_ACCURACY_METERS)):
        return False
    prev_at = rider.location_updated_at
    if prev_at.tzinfo is None:
        prev_at = prev_at.replace(tzinfo=UTC)
    elapsed_seconds = (now - prev_at).total_seconds()
    if elapsed_seconds <= 0:
        return False
    distance_km = location_service.distance_km(rider.current_latitude, rider.current_longitude, latitude, longitude)
    implied_speed_mps = (distance_km * 1000) / elapsed_seconds
    return implied_speed_mps > settings.RIDER_LOCATION_MAX_PLAUSIBLE_SPEED_MPS


def _should_store_history_row(db: Session, rider: User, latitude: Decimal, longitude: Decimal, now: datetime) -> bool:
    """Live Rider Tracking Phase 7 — Location Update Throttling. A new
    history row is written once EITHER enough time OR enough movement has
    happened since the last stored point, whichever comes first (the same
    "time OR distance" pattern rider-mobile's own background-location task
    already uses) — never purely time-gated, so a rider covering real
    ground quickly during a short interval still gets a meaningful trail,
    while a stationary rider doesn't fill the table with near-duplicates."""
    last_ping = db.scalar(
        select(RiderLocationPing).where(RiderLocationPing.rider_id == rider.id).order_by(RiderLocationPing.recorded_at.desc()).limit(1)
    )
    if last_ping is None:
        return True

    last_recorded_at = last_ping.recorded_at if last_ping.recorded_at.tzinfo else last_ping.recorded_at.replace(tzinfo=UTC)
    elapsed_seconds = (now - last_recorded_at).total_seconds()
    if elapsed_seconds >= settings.RIDER_LOCATION_MIN_INTERVAL_SECONDS:
        return True

    moved_km = location_service.distance_km(last_ping.latitude, last_ping.longitude, latitude, longitude)
    return (moved_km * 1000) >= settings.RIDER_LOCATION_MIN_MOVEMENT_METERS


def update_rider_location(
    db: Session,
    rider: User,
    latitude: Decimal,
    longitude: Decimal,
    accuracy: Decimal | None = None,
    heading: Decimal | None = None,
    speed: Decimal | None = None,
    altitude: Decimal | None = None,
    captured_at: datetime | None = None,
) -> RiderLocationRead:
    now = datetime.now(UTC)
    _reject_implausible_timestamp(rider.id, captured_at, now)

    order, assignment = get_active_assignment_context(db, rider)
    partner = get_or_create_delivery_partner(db, rider)
    # Live Rider Tracking Phase 6 — an explicit rejection, not a silent
    # no-op: a rider who is neither online nor holding an active delivery
    # gets a clear 403 the app can react to (e.g. stop its own reporting
    # loop), rather than guessing from a quietly-discarded call. An ONLINE
    # rider with no delivery yet is still eligible — required so
    # list_available_deliveries can keep showing "how far is this order"
    # before any rider has claimed it.
    if not partner.is_online and order is None:
        log_event(logger, "location_rejected", rider_id=rider.id, reason="ineligible")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Go online or accept a delivery before reporting your location.",
        )

    if _is_implausible_movement(rider, latitude, longitude, accuracy, now):
        log_event(logger, "location_rejected", rider_id=rider.id, reason="implausible_movement")
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Reported location is not plausible.")

    # Live Rider Tracking Phase 39 — Observability. "tracking_started": the
    # first accepted ping for this specific order — the moment this
    # order's own live-tracking window begins, distinct from the rider's
    # broader online/offline status.
    if order is not None and db.scalar(select(RiderLocationPing.id).where(RiderLocationPing.order_id == order.id).limit(1)) is None:
        log_event(logger, "tracking_started", rider_id=rider.id, order_id=order.id)

    log_event(logger, "location_received", rider_id=rider.id, order_id=order.id if order else None)

    should_store = _should_store_history_row(db, rider, latitude, longitude, now)
    if not should_store:
        log_event(logger, "location_filtered", rider_id=rider.id, reason="throttled")

    rider.current_latitude = latitude
    rider.current_longitude = longitude
    rider.current_accuracy = accuracy
    rider.current_heading = heading
    rider.current_speed = speed
    rider.location_updated_at = now

    if should_store:
        db.add(
            RiderLocationPing(
                rider_id=rider.id,
                assignment_id=assignment.id if assignment else None,
                order_id=order.id if order else None,
                latitude=latitude,
                longitude=longitude,
                accuracy=accuracy,
                heading=heading,
                speed=speed,
                altitude=altitude,
                captured_at=captured_at,
            )
        )

    db.commit()
    db.refresh(rider)

    # Push the new position to every order this rider is actively
    # delivering (normally at most one) — but only orders whose status
    # makes rider location visible at all; anything else stays silent.
    # Live Rider Tracking Phase 32 — Offline/Failure Handling. The location
    # itself is already committed above; a broadcast failure here (a bad
    # routing response, a WS internals issue) must degrade to "this update
    # wasn't broadcast live" only, never a 500 that makes the rider's app
    # think its location report itself failed and needs retrying.
    active_orders = db.scalars(
        select(Order).where(Order.rider_id == rider.id, Order.status.in_(LOCATION_VISIBLE_STATUSES))
    )
    for active_order in active_orders:
        try:
            # Live Rider Tracking Phase 35 — Performance/Scalability.
            # build_tracking_snapshot does real work (a restaurant read,
            # and possibly a live OSRM call for ETA) — skip it entirely
            # when nobody is connected to this order's WS room rather
            # than computing a snapshot no one will receive. This runs on
            # every accepted GPS ping (much higher frequency than a
            # status transition), so it's the path where this actually
            # matters.
            if manager.has_listeners(active_order.id):
                snapshot = build_tracking_snapshot(db, active_order)
                manager.broadcast(active_order.id, to_tracking_response(snapshot).model_dump(mode="json"))
            # Live Rider Tracking Phase 34 — Notification Integration.
            # Deliberately NOT gated behind has_listeners above — a
            # customer who isn't watching the live map right now (app
            # backgrounded/closed) still needs the push notification.
            maybe_notify_rider_approaching(db, active_order, latitude, longitude)
        except Exception as exc:
            log_event(logger, "tracking_error", order_id=active_order.id, stage="location_broadcast", reason=type(exc).__name__)
            logger.warning("Tracking broadcast failed for order %s after a rider location update", active_order.id, exc_info=True)

    return _to_location_read(rider)


def purge_rider_location_history(db: Session, *, older_than_days: int = 30) -> int:
    """Live Rider Tracking Phase 29 — Location History Policy. A plain
    bulk delete of RiderLocationPing rows past the documented retention
    window (docs/location-privacy.md) — nothing currently reads this
    table for anything other than the single most recent row per rider
    (see _should_refresh above), so an old row has no remaining
    operational purpose. Not scheduled by anything yet — this project has
    no cron/scheduled-task infrastructure today; intended to be run from
    a one-off admin script or wired into a scheduler if one is added
    later. Returns the number of rows deleted."""
    cutoff = datetime.now(UTC) - timedelta(days=older_than_days)
    result = db.execute(delete(RiderLocationPing).where(RiderLocationPing.recorded_at < cutoff))
    db.commit()
    return result.rowcount
