from fastapi import APIRouter, Query, status

from app.api.v1.deps import CurrentUser, DbSession
from app.schemas.notification import NotificationPreferenceRead, NotificationPreferenceUpdate
from app.schemas.push_token import PushTokenCreate, PushTokenRead
from app.services.notifications import (
    delete_push_token,
    get_or_create_notification_preference,
    update_notification_preference,
    upsert_push_token,
)

router = APIRouter()


@router.post("/register", response_model=PushTokenRead)
def register_push_token(payload: PushTokenCreate, db: DbSession, current_user: CurrentUser) -> PushTokenRead:
    return upsert_push_token(db, current_user.id, payload.token, payload.platform, payload.device_identifier)


@router.delete("/register", status_code=status.HTTP_204_NO_CONTENT)
def unregister_push_token(db: DbSession, current_user: CurrentUser, token: str = Query(...)) -> None:
    delete_push_token(db, current_user.id, token)


@router.get("/preferences", response_model=NotificationPreferenceRead)
def get_notification_preferences(db: DbSession, current_user: CurrentUser) -> NotificationPreferenceRead:
    # Notification Preferences (Phase 24) — shared across every role,
    # the same "this isn't role-specific, it's just this authenticated
    # user's own setting" reasoning /register above already follows.
    preference = get_or_create_notification_preference(db, current_user.id)
    db.commit()
    return preference


@router.patch("/preferences", response_model=NotificationPreferenceRead)
def update_notification_preferences(
    payload: NotificationPreferenceUpdate, db: DbSession, current_user: CurrentUser
) -> NotificationPreferenceRead:
    # Notification Preference API (Phase 25) — PATCH (not PUT), matching
    # this codebase's own established convention for a partial update of
    # a settings-shaped resource (e.g. /admin/settings, /rider/status) —
    # never a full-replacement semantics that would reset every category
    # not explicitly sent.
    return update_notification_preference(db, current_user.id, payload.model_dump(exclude_unset=True))
