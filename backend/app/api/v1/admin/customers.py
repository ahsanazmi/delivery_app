from datetime import date
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request

from app.api.v1.deps import DbSession, require_admin
from app.models.user import User
from app.schemas.admin import (
    AdminAccountActionRequest,
    AdminCustomerDetail,
    AdminCustomerListResponse,
    AdminCustomerStatus,
)
from app.services.admin_customers import activate_admin_customer, get_admin_customer_detail, list_admin_customers, suspend_admin_customer

router = APIRouter()


@router.get("/customers", response_model=AdminCustomerListResponse)
def list_customers(
    db: DbSession,
    search: str | None = Query(default=None),
    status_filter: AdminCustomerStatus | None = Query(default=None, alias="status"),
    registered_after: date | None = Query(default=None),
    registered_before: date | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=20, ge=1, le=100),
    current_admin: User = Depends(require_admin),
) -> AdminCustomerListResponse:
    return list_admin_customers(
        db,
        search=search,
        status_filter=status_filter,
        registered_after=registered_after,
        registered_before=registered_before,
        page=page,
        limit=limit,
    )


# Registered after the plain /customers list on purpose (established
# convention: "customers" itself is never a valid UUID so there's no real
# collision here, but ordering list-before-detail is kept consistent with
# every other admin/rider route pair in this project).
@router.get("/customers/{customer_id}", response_model=AdminCustomerDetail)
def get_customer(customer_id: UUID, db: DbSession, current_admin: User = Depends(require_admin)) -> AdminCustomerDetail:
    return get_admin_customer_detail(db, customer_id)


# Phase 23 — replaces the old PATCH /customers/{id} generic status setter
# (no validation, no reason, no audit log) with two explicit, validated,
# audited actions. See admin_account_status.set_user_active_status.
@router.post("/customers/{customer_id}/suspend", response_model=AdminCustomerDetail)
def suspend_customer(
    customer_id: UUID,
    payload: AdminAccountActionRequest,
    db: DbSession,
    request: Request,
    current_admin: User = Depends(require_admin),
) -> AdminCustomerDetail:
    ip_address = request.client.host if request.client else None
    return suspend_admin_customer(db, current_admin, customer_id, payload.reason, ip_address)


@router.post("/customers/{customer_id}/activate", response_model=AdminCustomerDetail)
def activate_customer(
    customer_id: UUID,
    payload: AdminAccountActionRequest,
    db: DbSession,
    request: Request,
    current_admin: User = Depends(require_admin),
) -> AdminCustomerDetail:
    ip_address = request.client.host if request.client else None
    return activate_admin_customer(db, current_admin, customer_id, payload.reason, ip_address)
