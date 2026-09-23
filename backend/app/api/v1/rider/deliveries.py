from uuid import UUID

from fastapi import APIRouter, Depends

from app.api.v1.deps import DbSession, require_rider
from app.models.user import User
from app.schemas.order import OrderRead
from app.schemas.rider_delivery import (
    AvailableDeliveryRead,
    CodCollectionRead,
    DeliveryAssignmentRead,
    DeliveryRejectRequest,
    RiderDeliveryDetailRead,
)
from app.services.rider_deliveries import (
    accept_delivery,
    collect_cod_payment,
    complete_delivery,
    get_rider_delivery_detail,
    list_available_deliveries,
    mark_arrived_at_restaurant,
    pickup_delivery,
    reject_delivery,
    start_delivery,
)

router = APIRouter()


@router.get("/deliveries/available", response_model=list[AvailableDeliveryRead])
def get_available_deliveries(
    db: DbSession, current_rider: User = Depends(require_rider)
) -> list[AvailableDeliveryRead]:
    return list_available_deliveries(db, current_rider)


# Registered before the /{order_id} routes below on purpose: FastAPI/Starlette
# matches path *templates* before validating the {order_id} type, so if a
# GET /{order_id} route were registered first, a request to
# /deliveries/available would match its template and fail UUID parsing
# (422) instead of ever reaching this handler.
@router.get("/deliveries/{order_id}", response_model=RiderDeliveryDetailRead)
def get_delivery_detail(
    order_id: UUID, db: DbSession, current_rider: User = Depends(require_rider)
) -> RiderDeliveryDetailRead:
    return get_rider_delivery_detail(db, current_rider, order_id)


@router.post("/deliveries/{order_id}/accept", response_model=OrderRead)
def accept_delivery_request(
    order_id: UUID, db: DbSession, current_rider: User = Depends(require_rider)
) -> OrderRead:
    return accept_delivery(db, current_rider, order_id)


@router.post("/deliveries/{order_id}/reject", response_model=DeliveryAssignmentRead)
def reject_delivery_request(
    order_id: UUID,
    db: DbSession,
    payload: DeliveryRejectRequest | None = None,
    current_rider: User = Depends(require_rider),
) -> DeliveryAssignmentRead:
    reason = payload.reason if payload else None
    return reject_delivery(db, current_rider, order_id, reason)


@router.post("/deliveries/{order_id}/arrived", response_model=DeliveryAssignmentRead)
def mark_arrived_request(
    order_id: UUID, db: DbSession, current_rider: User = Depends(require_rider)
) -> DeliveryAssignmentRead:
    return mark_arrived_at_restaurant(db, current_rider, order_id)


@router.post("/deliveries/{order_id}/pickup", response_model=OrderRead)
def pickup_delivery_request(
    order_id: UUID, db: DbSession, current_rider: User = Depends(require_rider)
) -> OrderRead:
    return pickup_delivery(db, current_rider, order_id)


@router.post("/deliveries/{order_id}/start", response_model=OrderRead)
def start_delivery_request(
    order_id: UUID, db: DbSession, current_rider: User = Depends(require_rider)
) -> OrderRead:
    return start_delivery(db, current_rider, order_id)


@router.post("/deliveries/{order_id}/cod-collect", response_model=CodCollectionRead)
def collect_cod_payment_request(
    order_id: UUID, db: DbSession, current_rider: User = Depends(require_rider)
) -> CodCollectionRead:
    return collect_cod_payment(db, current_rider, order_id)


@router.post("/deliveries/{order_id}/complete", response_model=OrderRead)
def complete_delivery_request(
    order_id: UUID, db: DbSession, current_rider: User = Depends(require_rider)
) -> OrderRead:
    return complete_delivery(db, current_rider, order_id)
