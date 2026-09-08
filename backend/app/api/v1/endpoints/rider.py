from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException

from app.api.v1.deps import DbSession, require_roles
from app.models.order import OrderStatus
from app.models.user import User, UserRole
from app.schemas.order import OrderRead
from app.services.orders import list_rider_orders, update_rider_order_status

router = APIRouter()


@router.get("/orders", response_model=list[OrderRead])
def rider_orders(db: DbSession, current_rider: User = Depends(require_roles(UserRole.RIDER))) -> list[OrderRead]:
    return list_rider_orders(db, current_rider.id)


@router.patch("/orders/{order_id}/pickup", response_model=OrderRead)
def mark_pickup(
    order_id: UUID,
    db: DbSession,
    current_rider: User = Depends(require_roles(UserRole.RIDER)),
) -> OrderRead:
    try:
        return update_rider_order_status(db, current_rider.id, order_id, OrderStatus.OUT_FOR_DELIVERY, "Picked up by rider")
    except HTTPException:
        raise


@router.patch("/orders/{order_id}/deliver", response_model=OrderRead)
def mark_delivered(
    order_id: UUID,
    db: DbSession,
    current_rider: User = Depends(require_roles(UserRole.RIDER)),
) -> OrderRead:
    try:
        return update_rider_order_status(db, current_rider.id, order_id, OrderStatus.DELIVERED, "Delivered by rider")
    except HTTPException:
        raise
