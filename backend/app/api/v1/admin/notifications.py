from uuid import UUID

from fastapi import APIRouter, Depends

from app.api.v1.deps import DbSession, require_admin
from app.models.user import User
from app.schemas.notification import MarkAllReadResponse, NotificationCleanupResult, NotificationRead, UnreadCountResponse
from app.services.notifications import (
    count_unread_notifications,
    list_notifications,
    mark_all_notifications_read,
    mark_notification_read,
    purge_old_notifications,
)

router = APIRouter()


@router.get("/notifications", response_model=list[NotificationRead])
def list_admin_notifications(db: DbSession, current_admin: User = Depends(require_admin)) -> list[NotificationRead]:
    # Security — Phase 9 — scoped to this admin's own user_id, the same
    # as every other role. An admin's notification feed is their own
    # personal inbox of operational alerts (new restaurant registered,
    # payment failure, ...) broadcast *to* them individually by
    # notify_admins — never a window into every user's private
    # notifications. No admin-only "view anyone's notifications" endpoint
    # exists anywhere in this codebase, and this phase does not add one.
    return list_notifications(db, current_admin.id)


@router.get("/notifications/unread-count", response_model=UnreadCountResponse)
def unread_notification_count(db: DbSession, current_admin: User = Depends(require_admin)) -> UnreadCountResponse:
    return UnreadCountResponse(unread_count=count_unread_notifications(db, current_admin.id))


@router.post("/notifications/{notification_id}/read", response_model=NotificationRead)
def mark_read(
    notification_id: UUID, db: DbSession, current_admin: User = Depends(require_admin)
) -> NotificationRead:
    return mark_notification_read(db, current_admin.id, notification_id)


@router.post("/notifications/read-all", response_model=MarkAllReadResponse)
def mark_all_read(db: DbSession, current_admin: User = Depends(require_admin)) -> MarkAllReadResponse:
    updated = mark_all_notifications_read(db, current_admin.id)
    return MarkAllReadResponse(updated=updated)


@router.post("/notifications/cleanup", response_model=NotificationCleanupResult)
def cleanup_old_notifications(db: DbSession, current_admin: User = Depends(require_admin)) -> NotificationCleanupResult:
    # Notification History/Retention (Phase 34) — this codebase has no
    # scheduler, so this is the on-demand trigger for
    # purge_old_notifications (also exactly what a future scheduled job
    # would call, per Phase 42's own decision on background processing).
    # Deliberately global, not scoped to current_admin's own
    # notifications — this is platform housekeeping, the same
    # "an admin action, not a personal one" category as
    # broadcast_promotion or notify_admins itself.
    deleted = purge_old_notifications(db)
    return NotificationCleanupResult(deleted=deleted)
