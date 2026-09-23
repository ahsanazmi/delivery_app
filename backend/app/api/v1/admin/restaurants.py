from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request

from app.api.v1.deps import DbSession, require_admin
from app.models.delivery_partner import ApprovalStatus
from app.models.user import User
from app.schemas.admin import (
    AdminAccountActionRequest,
    AdminRestaurantDetail,
    AdminRestaurantListResponse,
    AdminRestaurantRejectRequest,
    AdminRestaurantStatus,
)
from app.services.admin_restaurants import (
    approve_admin_restaurant,
    deactivate_admin_restaurant,
    get_admin_restaurant_detail,
    list_admin_restaurants,
    reactivate_admin_restaurant,
    reinstate_admin_restaurant,
    reject_admin_restaurant,
    suspend_admin_restaurant,
)

router = APIRouter()


@router.get("/restaurants", response_model=AdminRestaurantListResponse)
def list_restaurants(
    db: DbSession,
    search: str | None = Query(default=None),
    status_filter: AdminRestaurantStatus | None = Query(default=None, alias="status"),
    is_open: bool | None = Query(default=None),
    approval_status: ApprovalStatus | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=20, ge=1, le=100),
    current_admin: User = Depends(require_admin),
) -> AdminRestaurantListResponse:
    return list_admin_restaurants(
        db,
        search=search,
        status_filter=status_filter,
        is_open=is_open,
        approval_filter=approval_status,
        page=page,
        limit=limit,
    )


# Registered after the plain /restaurants list on purpose — same established
# convention as every other admin/rider list-then-detail route pair.
@router.get("/restaurants/{restaurant_id}", response_model=AdminRestaurantDetail)
def get_restaurant(restaurant_id: UUID, db: DbSession, current_admin: User = Depends(require_admin)) -> AdminRestaurantDetail:
    return get_admin_restaurant_detail(db, restaurant_id)


# Phase 23 — replaces the old PATCH /restaurants/{id} generic status
# setter with two explicit, validated, audited actions on Restaurant.is_active.
# Named deactivate/reactivate (not suspend/activate) since those two words
# already belong to the approval-status actions below (Phase 6).
@router.post("/restaurants/{restaurant_id}/deactivate", response_model=AdminRestaurantDetail)
def deactivate_restaurant(
    restaurant_id: UUID,
    payload: AdminAccountActionRequest,
    db: DbSession,
    request: Request,
    current_admin: User = Depends(require_admin),
) -> AdminRestaurantDetail:
    ip_address = request.client.host if request.client else None
    return deactivate_admin_restaurant(db, current_admin, restaurant_id, payload.reason, ip_address)


@router.post("/restaurants/{restaurant_id}/reactivate", response_model=AdminRestaurantDetail)
def reactivate_restaurant(
    restaurant_id: UUID,
    payload: AdminAccountActionRequest,
    db: DbSession,
    request: Request,
    current_admin: User = Depends(require_admin),
) -> AdminRestaurantDetail:
    ip_address = request.client.host if request.client else None
    return reactivate_admin_restaurant(db, current_admin, restaurant_id, payload.reason, ip_address)


# Phase 6 — the only validated way to move a restaurant through the
# approval state machine (PENDING/APPROVED/REJECTED/SUSPENDED). Each
# action 409s if the restaurant isn't currently in a state it's valid from.
@router.post("/restaurants/{restaurant_id}/approve", response_model=AdminRestaurantDetail)
def approve_restaurant(
    restaurant_id: UUID,
    payload: AdminAccountActionRequest,
    db: DbSession,
    request: Request,
    current_admin: User = Depends(require_admin),
) -> AdminRestaurantDetail:
    ip_address = request.client.host if request.client else None
    return approve_admin_restaurant(db, current_admin, restaurant_id, payload.reason, ip_address)


@router.post("/restaurants/{restaurant_id}/reject", response_model=AdminRestaurantDetail)
def reject_restaurant(
    restaurant_id: UUID,
    payload: AdminRestaurantRejectRequest,
    db: DbSession,
    request: Request,
    current_admin: User = Depends(require_admin),
) -> AdminRestaurantDetail:
    ip_address = request.client.host if request.client else None
    return reject_admin_restaurant(db, current_admin, restaurant_id, payload.rejection_reason, ip_address)


@router.post("/restaurants/{restaurant_id}/suspend", response_model=AdminRestaurantDetail)
def suspend_restaurant(
    restaurant_id: UUID,
    payload: AdminAccountActionRequest,
    db: DbSession,
    request: Request,
    current_admin: User = Depends(require_admin),
) -> AdminRestaurantDetail:
    ip_address = request.client.host if request.client else None
    return suspend_admin_restaurant(db, current_admin, restaurant_id, payload.reason, ip_address)


@router.post("/restaurants/{restaurant_id}/activate", response_model=AdminRestaurantDetail)
def activate_restaurant(
    restaurant_id: UUID,
    payload: AdminAccountActionRequest,
    db: DbSession,
    request: Request,
    current_admin: User = Depends(require_admin),
) -> AdminRestaurantDetail:
    ip_address = request.client.host if request.client else None
    return reinstate_admin_restaurant(db, current_admin, restaurant_id, payload.reason, ip_address)
