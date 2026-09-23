from datetime import date
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from app.api.v1.deps import DbSession, require_admin
from app.models.user import User
from app.schemas.admin import AdminAuditLogDetail, AdminAuditLogListResponse
from app.services.admin_audit_logs import get_admin_audit_log_detail, list_admin_audit_logs

router = APIRouter()


@router.get("/audit-logs", response_model=AdminAuditLogListResponse)
def list_audit_logs(
    db: DbSession,
    admin_id: UUID | None = Query(default=None),
    action: str | None = Query(default=None),
    entity_type: str | None = Query(default=None),
    entity_id: str | None = Query(default=None),
    date_from: date | None = Query(default=None),
    date_to: date | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=50, ge=1, le=200),
    current_admin: User = Depends(require_admin),
) -> AdminAuditLogListResponse:
    return list_admin_audit_logs(
        db, admin_id=admin_id, action=action, entity_type=entity_type, entity_id=entity_id,
        date_from=date_from, date_to=date_to, page=page, limit=limit,
    )


@router.get("/audit-logs/{audit_log_id}", response_model=AdminAuditLogDetail)
def get_audit_log(
    audit_log_id: UUID, db: DbSession, current_admin: User = Depends(require_admin)
) -> AdminAuditLogDetail:
    return get_admin_audit_log_detail(db, audit_log_id)
