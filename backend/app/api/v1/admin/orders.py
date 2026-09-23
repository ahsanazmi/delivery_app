from datetime import date
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status

from app.api.v1.deps import DbSession, require_admin
from app.models.order import Order, OrderStatus
from app.models.user import User
from app.schemas.admin import (
    AdminOrderAssignRiderRequest,
    AdminOrderCancelRequest,
    AdminOrderDetail,
    AdminOrderListResponse,
    AdminOrderReassignRiderRequest,
)
from app.schemas.order import OrderRead
from app.services.admin_orders import get_admin_order_detail, list_admin_orders
from app.services.orders import admin_assign_rider_to_order, admin_cancel_order, admin_reassign_rider

router = APIRouter()


@router.get("/orders", response_model=AdminOrderListResponse)
def list_orders(
    db: DbSession,
    search: str | None = Query(default=None),
    status_filter: OrderStatus | None = Query(default=None, alias="status"),
    payment_method: str | None = Query(default=None),
    payment_status: str | None = Query(default=None),
    date_from: date | None = Query(default=None),
    date_to: date | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=20, ge=1, le=100),
    current_admin: User = Depends(require_admin),
) -> AdminOrderListResponse:
    return list_admin_orders(
        db,
        search=search,
        status_filter=status_filter,
        payment_method=payment_method,
        payment_status=payment_status,
        date_from=date_from,
        date_to=date_to,
        page=page,
        limit=limit,
    )


# Registered after the plain /orders list on purpose — same established
# convention as every other admin list-then-detail route pair.
@router.get("/orders/{order_id}", response_model=AdminOrderDetail)
def get_order(order_id: UUID, db: DbSession, current_admin: User = Depends(require_admin)) -> AdminOrderDetail:
    return get_admin_order_detail(db, order_id)


# Moved from app/api/v1/endpoints/admin.py (Phase 10) — a single,
# well-defined transition (assigning a rider to an order that doesn't have
# one yet, via the existing VALID_TRANSITIONS-gated READY_FOR_PICKUP ->
# RIDER_ASSIGNED move) — a genuinely distinct capability from Phase 11's
# reassign-rider below (replacing an *already*-assigned rider), not the
# "arbitrary direct status modification" this phase's other removal
# targets. Order State Rule audit — now requires a reason and writes an
# audit log, same as cancel/reassign-rider: this endpoint call is
# exclusively an administrative action, so it must be explicit and
# audited like every other one, not exempt just because it predates
# Phase 11's audit-log system. Calls admin_assign_rider_to_order, a
# distinct wrapper from the generic assign_rider_to_order the wider test
# suite uses directly as an unaudited setup helper — see that function's
# own docstring in services/orders.py for why the two must stay separate.
@router.patch("/orders/{order_id}/assign-rider", response_model=OrderRead)
def assign_rider(
    order_id: UUID,
    payload: AdminOrderAssignRiderRequest,
    db: DbSession,
    request: Request,
    current_admin: User = Depends(require_admin),
) -> OrderRead:
    order = db.get(Order, order_id)
    if not order:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Order not found")
    ip_address = request.client.host if request.client else None
    return admin_assign_rider_to_order(db, current_admin, order, payload.rider_id, payload.reason, ip_address)


# Phase 11 — PATCH /orders/{id}/status (accept-any-OrderStatus, no reason,
# no audit trail) has been removed entirely. It was exactly the "arbitrary
# direct status modification" this phase's brief opens by forbidding — the
# one transition it enabled with a genuinely clear business rule
# (cancellation) now has its own explicit, audited action below; every
# other transition it allowed had no stated business rule of its own, so
# no replacement was built for it, per "only implement actions that have
# clear business rules."
@router.post("/orders/{order_id}/cancel", response_model=OrderRead)
def cancel_order(
    order_id: UUID,
    payload: AdminOrderCancelRequest,
    db: DbSession,
    request: Request,
    current_admin: User = Depends(require_admin),
) -> OrderRead:
    ip_address = request.client.host if request.client else None
    return admin_cancel_order(db, current_admin, order_id, payload.reason, ip_address)


@router.post("/orders/{order_id}/reassign-rider", response_model=OrderRead)
def reassign_rider(
    order_id: UUID,
    payload: AdminOrderReassignRiderRequest,
    db: DbSession,
    request: Request,
    current_admin: User = Depends(require_admin),
) -> OrderRead:
    ip_address = request.client.host if request.client else None
    return admin_reassign_rider(db, current_admin, order_id, payload.new_rider_id, payload.reason, ip_address)
