from uuid import UUID

from fastapi import APIRouter, Depends

from app.api.v1.deps import DbSession, require_roles
from app.models.user import User, UserRole
from app.schemas.notification import MarkAllReadResponse, NotificationRead, UnreadCountResponse
from app.services.notifications import (
    count_unread_notifications,
    list_notifications,
    mark_all_notifications_read,
    mark_notification_read,
)

router = APIRouter()


@router.get("/notifications", response_model=list[NotificationRead])
def list_restaurant_notifications(
    db: DbSession, current_user: User = Depends(require_roles(UserRole.RESTAURANT_OWNER))
) -> list[NotificationRead]:
    # Security — Phase 12 — scoped to this owner's own user_id, the same
    # pattern as every other role's notification router. An owner with
    # multiple restaurants still has exactly one notification feed (their
    # own account's); which restaurant a given row is about is carried in
    # its own title/body text and order_id, not a separate per-restaurant
    # filter — there is no cross-owner listing of any kind here.
    return list_notifications(db, current_user.id)


@router.get("/notifications/unread-count", response_model=UnreadCountResponse)
def unread_restaurant_notification_count(
    db: DbSession, current_user: User = Depends(require_roles(UserRole.RESTAURANT_OWNER))
) -> UnreadCountResponse:
    return UnreadCountResponse(unread_count=count_unread_notifications(db, current_user.id))


@router.post("/notifications/{notification_id}/read", response_model=NotificationRead)
def mark_read(
    notification_id: UUID, db: DbSession, current_user: User = Depends(require_roles(UserRole.RESTAURANT_OWNER))
) -> NotificationRead:
    return mark_notification_read(db, current_user.id, notification_id)


@router.post("/notifications/read-all", response_model=MarkAllReadResponse)
def mark_all_read(
    db: DbSession, current_user: User = Depends(require_roles(UserRole.RESTAURANT_OWNER))
) -> MarkAllReadResponse:
    updated = mark_all_notifications_read(db, current_user.id)
    return MarkAllReadResponse(updated=updated)
