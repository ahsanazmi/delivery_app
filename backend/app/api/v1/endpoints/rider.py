from fastapi import APIRouter, Depends, Request

from app.api.v1.deps import DbSession, require_rider
from app.core.rate_limit import rate_limit
from app.models.user import User
from app.schemas.order import OrderRead
from app.schemas.rider import RiderLocationRead, RiderLocationUpdate
from app.services.orders import list_rider_orders
from app.services.rider_location import update_rider_location

router = APIRouter()


@router.patch("/location", response_model=RiderLocationRead)
def update_location(
    payload: RiderLocationUpdate,
    request: Request,
    db: DbSession,
    current_rider: User = Depends(require_rider),
) -> RiderLocationRead:
    # A prior phase's "equivalent efficient location ingestion mechanism" —
    # this existing PATCH is extended in place (accuracy/heading/speed,
    # altitude/captured_at, a throttled history ledger, GPS-jump/timestamp
    # filtering, and an online-or-active-delivery gate — Live Rider
    # Tracking Phases 3/5/6/7/8) rather than standing up a parallel POST
    # route for the same concern.
    #
    # Live Rider Tracking Phase 40 — Final Security Audit. This was the one
    # tracking-surface endpoint without a rate limit at all — the client's
    # own ~12s reporting interval is self-limiting for a well-behaved app,
    # but nothing server-side previously bounded a compromised or buggy
    # client hammering it. Keyed by rider id (a device-bound identity, not
    # IP, matching this endpoint's own auth model), generous enough to
    # never interfere with the real reporting cadence.
    rate_limit(request, max_attempts=30, window_seconds=60, key=f"rider-location:{current_rider.id}")
    return update_rider_location(
        db, current_rider, payload.latitude, payload.longitude, payload.accuracy, payload.heading, payload.speed,
        payload.altitude, payload.captured_at,
    )


@router.get("/orders", response_model=list[OrderRead])
def rider_orders(db: DbSession, current_rider: User = Depends(require_rider)) -> list[OrderRead]:
    return list_rider_orders(db, current_rider.id)


# Phase 25 security audit: the old dual-hop PATCH /orders/{id}/pickup and
# PATCH /orders/{id}/deliver endpoints that used to live here were removed.
# They were dead code (rider-mobile stopped calling them back in Phase 13/17,
# once the granular /rider/deliveries/{id}/pickup|start|complete endpoints
# took over) but still reachable directly over the API, and — unlike the
# granular endpoints — completely bypassed the business rules those later
# phases added: no COD-collection-required-first check (Phase 16), no
# earnings ledger entry (Phase 19), and no DeliveryAssignment state-machine
# update (Phase 24). A rider could still call them by hand (curl/Postman)
# to mark their own order delivered without ever recording that they
# collected the cash, and without ever being credited for it. Removing the
# dead route closes that gap outright rather than trying to maintain the
# same rules in two places.
