from uuid import UUID

from fastapi import APIRouter, Depends

from app.api.v1.deps import DbSession, require_rider
from app.models.user import User
from app.schemas.notification import MarkAllReadResponse, NotificationRead
from app.services.notifications import list_notifications, mark_all_notifications_read, mark_notification_read

router = APIRouter()


@router.get("/notifications", response_model=list[NotificationRead])
def list_rider_notifications(db: DbSession, current_rider: User = Depends(require_rider)) -> list[NotificationRead]:
    return list_notifications(db, current_rider.id)


@router.post("/notifications/{notification_id}/read", response_model=NotificationRead)
def mark_read(
    notification_id: UUID, db: DbSession, current_rider: User = Depends(require_rider)
) -> NotificationRead:
    return mark_notification_read(db, current_rider.id, notification_id)


@router.post("/notifications/read-all", response_model=MarkAllReadResponse)
def mark_all_read(db: DbSession, current_rider: User = Depends(require_rider)) -> MarkAllReadResponse:
    updated = mark_all_notifications_read(db, current_rider.id)
    return MarkAllReadResponse(updated=updated)
