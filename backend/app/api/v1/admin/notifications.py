from uuid import UUID

from fastapi import APIRouter, Depends

from app.api.v1.deps import DbSession, require_admin
from app.models.user import User
from app.schemas.notification import MarkAllReadResponse, NotificationRead
from app.services.notifications import list_notifications, mark_all_notifications_read, mark_notification_read

router = APIRouter()


@router.get("/notifications", response_model=list[NotificationRead])
def list_admin_notifications(db: DbSession, current_admin: User = Depends(require_admin)) -> list[NotificationRead]:
    return list_notifications(db, current_admin.id)


@router.post("/notifications/{notification_id}/read", response_model=NotificationRead)
def mark_read(
    notification_id: UUID, db: DbSession, current_admin: User = Depends(require_admin)
) -> NotificationRead:
    return mark_notification_read(db, current_admin.id, notification_id)


@router.post("/notifications/read-all", response_model=MarkAllReadResponse)
def mark_all_read(db: DbSession, current_admin: User = Depends(require_admin)) -> MarkAllReadResponse:
    updated = mark_all_notifications_read(db, current_admin.id)
    return MarkAllReadResponse(updated=updated)
