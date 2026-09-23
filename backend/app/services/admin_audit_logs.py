from datetime import date, datetime, time
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.admin_audit_log import AdminAuditLog
from app.models.user import User
from app.schemas.admin import AdminAuditLogDetail, AdminAuditLogListResponse, AdminAuditLogSummary


def _admin_name(db: Session, admin_id: UUID) -> str | None:
    admin = db.get(User, admin_id)
    return admin.name if admin else None


def _to_summary(entry: AdminAuditLog, admin_name: str | None) -> AdminAuditLogSummary:
    return AdminAuditLogSummary(
        id=entry.id,
        admin_id=entry.admin_id,
        admin_name=admin_name,
        action=entry.action,
        entity_type=entry.target_type,
        entity_id=entry.target_id,
        reason=entry.reason,
        ip_address=entry.ip_address,
        created_at=entry.created_at,
    )


def _to_detail(entry: AdminAuditLog, admin_name: str | None) -> AdminAuditLogDetail:
    return AdminAuditLogDetail(
        **_to_summary(entry, admin_name).model_dump(),
        old_value=entry.previous_state,
        new_value=entry.new_state,
    )


def list_admin_audit_logs(
    db: Session,
    *,
    admin_id: UUID | None = None,
    action: str | None = None,
    entity_type: str | None = None,
    entity_id: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    page: int = 1,
    limit: int = 50,
) -> AdminAuditLogListResponse:
    statement = select(AdminAuditLog)
    if admin_id is not None:
        statement = statement.where(AdminAuditLog.admin_id == admin_id)
    if action:
        statement = statement.where(AdminAuditLog.action == action)
    if entity_type:
        statement = statement.where(AdminAuditLog.target_type == entity_type)
    if entity_id:
        statement = statement.where(AdminAuditLog.target_id == entity_id)
    if date_from is not None:
        statement = statement.where(AdminAuditLog.created_at >= datetime.combine(date_from, time.min))
    if date_to is not None:
        statement = statement.where(AdminAuditLog.created_at <= datetime.combine(date_to, time.max))

    total = db.scalar(select(func.count()).select_from(statement.subquery())) or 0
    entries = list(
        db.scalars(
            statement.order_by(AdminAuditLog.created_at.desc()).offset((page - 1) * limit).limit(limit)
        )
    )

    admin_names = {admin.id: admin.name for admin in db.scalars(select(User).where(User.id.in_({e.admin_id for e in entries})))}
    return AdminAuditLogListResponse(
        items=[_to_summary(entry, admin_names.get(entry.admin_id)) for entry in entries],
        total=total,
        page=page,
        limit=limit,
    )


def get_admin_audit_log_detail(db: Session, audit_log_id: UUID) -> AdminAuditLogDetail:
    entry = db.get(AdminAuditLog, audit_log_id)
    if not entry:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Audit log entry not found")
    return _to_detail(entry, _admin_name(db, entry.admin_id))
