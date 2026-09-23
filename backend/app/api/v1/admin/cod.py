from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request

from app.api.v1.deps import DbSession, require_admin
from app.models.user import User
from app.schemas.admin import (
    AdminCODReconciliationDetail,
    AdminCODReconciliationListResponse,
    AdminCODSettlementStatus,
    AdminCODSettleRequest,
)
from app.services.admin_cod import admin_settle_cod, get_admin_cod_reconciliation_detail, list_admin_cod_reconciliation

router = APIRouter()


@router.get("/cod", response_model=AdminCODReconciliationListResponse)
def list_cod_reconciliation(
    db: DbSession,
    search: str | None = Query(default=None),
    status_filter: AdminCODSettlementStatus | None = Query(default=None, alias="status"),
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=20, ge=1, le=100),
    current_admin: User = Depends(require_admin),
) -> AdminCODReconciliationListResponse:
    return list_admin_cod_reconciliation(db, search=search, status_filter=status_filter, page=page, limit=limit)


# Registered after the plain list on purpose — same established convention
# as every other admin list-then-detail route pair. {id} here is the
# rider's own user id — this endpoint reconciles one rider's COD standing,
# not a row in some separate "reconciliation record" table (there isn't
# one; everything is derived fresh from Payment + RiderSettlement).
@router.get("/cod/{rider_id}", response_model=AdminCODReconciliationDetail)
def get_cod_reconciliation(
    rider_id: UUID, db: DbSession, current_admin: User = Depends(require_admin)
) -> AdminCODReconciliationDetail:
    return get_admin_cod_reconciliation_detail(db, rider_id)


@router.post("/cod/{rider_id}/settle", response_model=AdminCODReconciliationDetail)
def settle_cod(
    rider_id: UUID,
    payload: AdminCODSettleRequest,
    db: DbSession,
    request: Request,
    current_admin: User = Depends(require_admin),
) -> AdminCODReconciliationDetail:
    ip_address = request.client.host if request.client else None
    return admin_settle_cod(db, current_admin, rider_id, payload.amount, payload.note, ip_address)
