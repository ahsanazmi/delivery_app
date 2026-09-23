from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.api.v1.customer.cart import serialize_cart
from app.api.v1.deps import DbSession, require_customer
from app.models.order import OrderStatus
from app.models.user import User
from app.schemas.cart import CartRead
from app.schemas.order import CustomerOrderCreate, OrderRead
from app.services.orders import cancel_order, create_order, get_user_order, list_user_orders, reorder_from_order

router = APIRouter()


@router.get("/orders", response_model=list[OrderRead])
def list_orders(
    db: DbSession,
    current_user: User = Depends(require_customer),
    status_filter: OrderStatus | None = Query(default=None, alias="status"),
    date_from: datetime | None = Query(default=None),
    date_to: datetime | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=20, ge=1, le=100),
) -> list[OrderRead]:
    offset = (page - 1) * limit
    return list_user_orders(
        db,
        current_user.id,
        status_filter=status_filter,
        date_from=date_from,
        date_to=date_to,
        offset=offset,
        limit=limit,
    )


@router.post("/orders", response_model=OrderRead, status_code=status.HTTP_201_CREATED)
def place_order(payload: CustomerOrderCreate, db: DbSession, current_user: User = Depends(require_customer)) -> OrderRead:
    try:
        return create_order(
            db,
            current_user,
            payload.address_id,
            payment_method=payload.payment_method,
            delivery_instructions=payload.delivery_instructions,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc


@router.get("/orders/{order_id}", response_model=OrderRead)
def get_order(order_id: UUID, db: DbSession, current_user: User = Depends(require_customer)) -> OrderRead:
    order = get_user_order(db, current_user.id, order_id)
    if not order:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Order not found")
    return order


@router.post("/orders/{order_id}/cancel", response_model=OrderRead)
def cancel_order_endpoint(order_id: UUID, db: DbSession, current_user: User = Depends(require_customer), reason: str | None = None) -> OrderRead:
    return cancel_order(db, current_user.id, order_id, reason)


@router.post("/orders/{order_id}/reorder", response_model=CartRead)
def reorder_order(order_id: UUID, db: DbSession, current_user: User = Depends(require_customer)) -> CartRead:
    result = reorder_from_order(db, current_user, order_id)
    return serialize_cart(db, result["cart"], result["unavailable_items"])
