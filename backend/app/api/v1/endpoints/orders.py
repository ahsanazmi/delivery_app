from uuid import UUID

from fastapi import APIRouter, HTTPException, status

from app.api.v1.deps import CurrentUser, DbSession
from app.schemas.order import OrderCreate, OrderRead
from app.services.orders import cancel_order, create_order_from_cart, get_user_order, list_user_orders

router = APIRouter()


@router.get("", response_model=list[OrderRead])
def list_orders(db: DbSession, current_user: CurrentUser) -> list[OrderRead]:
    return list_user_orders(db, current_user.id)


@router.post("", response_model=OrderRead, status_code=status.HTTP_201_CREATED)
def create_order(payload: OrderCreate, db: DbSession, current_user: CurrentUser) -> OrderRead:
    try:
        return create_order_from_cart(db, current_user.id, payload.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.get("/{order_id}", response_model=OrderRead)
def get_order(order_id: UUID, db: DbSession, current_user: CurrentUser) -> OrderRead:
    order = get_user_order(db, current_user.id, order_id)
    if not order:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Order not found")
    return order


@router.patch("/{order_id}/cancel", response_model=OrderRead)
def cancel_order_endpoint(order_id: UUID, db: DbSession, current_user: CurrentUser, reason: str | None = None) -> OrderRead:
    try:
        return cancel_order(db, current_user.id, order_id, reason)
    except HTTPException:
        raise
