from fastapi import APIRouter, Depends

from app.api.v1.deps import DbSession, require_rider
from app.models.user import User
from app.schemas.order import OrderRead
from app.schemas.rider import RiderLocationRead, RiderLocationUpdate
from app.services.orders import list_rider_orders
from app.services.rider_location import update_rider_location

router = APIRouter()


@router.patch("/location", response_model=RiderLocationRead)
def update_location(
    payload: RiderLocationUpdate,
    db: DbSession,
    current_rider: User = Depends(require_rider),
) -> RiderLocationRead:
    # Phase 22's "equivalent efficient location ingestion mechanism" — this
    # existing PATCH is extended in place (accuracy/heading/speed, a
    # throttled history ledger, and an online-or-active-delivery gate)
    # rather than standing up a parallel POST route for the same concern.
    return update_rider_location(
        db, current_rider, payload.latitude, payload.longitude, payload.accuracy, payload.heading, payload.speed
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
