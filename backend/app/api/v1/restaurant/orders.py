from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from app.api.v1.deps import DbSession, require_roles
from app.models.user import User, UserRole
from app.schemas.order import OrderRead, OrderRejectRequest, RestaurantOrderDetailRead, RestaurantOrderListItem
from app.services.restaurant_dashboard import resolve_owner_restaurant
from app.services.orders import (
    accept_order,
    compute_restaurant_financials,
    get_restaurant_order_or_404,
    list_restaurant_orders,
    mark_order_preparing,
    mark_order_ready,
    mask_customer_name,
    reject_order,
)

router = APIRouter()

StatusFilter = Literal["pending", "confirmed", "preparing", "ready", "completed", "cancelled"]


def _to_detail(order) -> RestaurantOrderDetailRead:
    # Restaurant Payment Visibility (Phase 28) — every restaurant-facing
    # order response (the initial GET and every action below that hands
    # back the freshly-updated order) uses this same conversion, so the
    # owner's financial figures are never dropped from the response
    # after accepting/rejecting/progressing an order — only the shared,
    # payment-blind OrderRead would otherwise be returned there.
    return RestaurantOrderDetailRead(
        **OrderRead.model_validate(order).model_dump(),
        **compute_restaurant_financials(order),
    )


@router.get("/orders", response_model=list[RestaurantOrderListItem])
def list_orders(
    db: DbSession,
    current_user: User = Depends(require_roles(UserRole.RESTAURANT_OWNER)),
    restaurant_id: UUID | None = Query(default=None),
    status_filter: StatusFilter | None = Query(default=None, alias="status"),
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=20, ge=1, le=100),
) -> list[RestaurantOrderListItem]:
    restaurant = resolve_owner_restaurant(db, current_user, restaurant_id)
    offset = (page - 1) * limit
    orders = list_restaurant_orders(db, restaurant.id, status_filter=status_filter, offset=offset, limit=limit)
    return [
        RestaurantOrderListItem(
            id=order.id,
            order_number=order.order_number,
            customer_name_masked=mask_customer_name(order.customer_name),
            item_count=order.item_count,
            total=order.total,
            payment_method=order.payment_method,
            payment_status=order.payment_status,
            status=order.status,
            created_at=order.created_at,
            **compute_restaurant_financials(order),
        )
        for order in orders
    ]


@router.get("/orders/{order_id}", response_model=RestaurantOrderDetailRead)
def get_order(
    order_id: UUID,
    db: DbSession,
    current_user: User = Depends(require_roles(UserRole.RESTAURANT_OWNER)),
    restaurant_id: UUID | None = Query(default=None),
) -> RestaurantOrderDetailRead:
    restaurant = resolve_owner_restaurant(db, current_user, restaurant_id)
    order = get_restaurant_order_or_404(db, restaurant.id, order_id)
    return _to_detail(order)


@router.post("/orders/{order_id}/accept", response_model=RestaurantOrderDetailRead)
def accept_restaurant_order(
    order_id: UUID,
    db: DbSession,
    current_user: User = Depends(require_roles(UserRole.RESTAURANT_OWNER)),
    restaurant_id: UUID | None = Query(default=None),
) -> RestaurantOrderDetailRead:
    restaurant = resolve_owner_restaurant(db, current_user, restaurant_id)
    return _to_detail(accept_order(db, restaurant.id, order_id))


@router.post("/orders/{order_id}/reject", response_model=RestaurantOrderDetailRead)
def reject_restaurant_order(
    order_id: UUID,
    db: DbSession,
    payload: OrderRejectRequest | None = None,
    current_user: User = Depends(require_roles(UserRole.RESTAURANT_OWNER)),
    restaurant_id: UUID | None = Query(default=None),
) -> RestaurantOrderDetailRead:
    restaurant = resolve_owner_restaurant(db, current_user, restaurant_id)
    reason = payload.reason if payload else None
    return _to_detail(reject_order(db, restaurant.id, order_id, reason))


@router.post("/orders/{order_id}/preparing", response_model=RestaurantOrderDetailRead)
def mark_restaurant_order_preparing(
    order_id: UUID,
    db: DbSession,
    current_user: User = Depends(require_roles(UserRole.RESTAURANT_OWNER)),
    restaurant_id: UUID | None = Query(default=None),
) -> RestaurantOrderDetailRead:
    restaurant = resolve_owner_restaurant(db, current_user, restaurant_id)
    return _to_detail(mark_order_preparing(db, restaurant.id, order_id))


@router.post("/orders/{order_id}/ready", response_model=RestaurantOrderDetailRead)
def mark_restaurant_order_ready(
    order_id: UUID,
    db: DbSession,
    current_user: User = Depends(require_roles(UserRole.RESTAURANT_OWNER)),
    restaurant_id: UUID | None = Query(default=None),
) -> RestaurantOrderDetailRead:
    restaurant = resolve_owner_restaurant(db, current_user, restaurant_id)
    return _to_detail(mark_order_ready(db, restaurant.id, order_id))
