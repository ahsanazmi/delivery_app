from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request

from app.api.v1.deps import DbSession, require_admin
from app.models.user import User
from app.schemas.admin import (
    AdminAccountActionRequest,
    AdminRestaurantOwnerListResponse,
    AdminRestaurantOwnerStatus,
    AdminRestaurantOwnerSummary,
)
from app.services.admin_restaurant_owners import (
    activate_admin_restaurant_owner,
    get_admin_restaurant_owner_detail,
    list_admin_restaurant_owners,
    suspend_admin_restaurant_owner,
)

router = APIRouter()


@router.get("/restaurant-owners", response_model=AdminRestaurantOwnerListResponse)
def list_restaurant_owners(
    db: DbSession,
    search: str | None = Query(default=None),
    status_filter: AdminRestaurantOwnerStatus | None = Query(default=None, alias="status"),
    has_restaurant: bool | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=20, ge=1, le=100),
    current_admin: User = Depends(require_admin),
) -> AdminRestaurantOwnerListResponse:
    return list_admin_restaurant_owners(
        db, search=search, status_filter=status_filter, has_restaurant=has_restaurant, page=page, limit=limit
    )


# Registered after the plain /restaurant-owners list on purpose — same
# established convention as every other admin/rider list-then-detail pair.
@router.get("/restaurant-owners/{owner_id}", response_model=AdminRestaurantOwnerSummary)
def get_restaurant_owner(
    owner_id: UUID, db: DbSession, current_admin: User = Depends(require_admin)
) -> AdminRestaurantOwnerSummary:
    return get_admin_restaurant_owner_detail(db, owner_id)


# Phase 23 — replaces the old PATCH /restaurant-owners/{id} generic status
# setter with two explicit, validated, audited actions.
@router.post("/restaurant-owners/{owner_id}/suspend", response_model=AdminRestaurantOwnerSummary)
def suspend_restaurant_owner(
    owner_id: UUID,
    payload: AdminAccountActionRequest,
    db: DbSession,
    request: Request,
    current_admin: User = Depends(require_admin),
) -> AdminRestaurantOwnerSummary:
    ip_address = request.client.host if request.client else None
    return suspend_admin_restaurant_owner(db, current_admin, owner_id, payload.reason, ip_address)


@router.post("/restaurant-owners/{owner_id}/activate", response_model=AdminRestaurantOwnerSummary)
def activate_restaurant_owner(
    owner_id: UUID,
    payload: AdminAccountActionRequest,
    db: DbSession,
    request: Request,
    current_admin: User = Depends(require_admin),
) -> AdminRestaurantOwnerSummary:
    ip_address = request.client.host if request.client else None
    return activate_admin_restaurant_owner(db, current_admin, owner_id, payload.reason, ip_address)
