import logging
from uuid import UUID

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.push_token import PushToken

logger = logging.getLogger(__name__)

EXPO_PUSH_URL = "https://exp.host/--/api/v2/push/send"
PUSH_REQUEST_TIMEOUT_SECONDS = 5.0


def _send_expo_push(db: Session, tokens: list[PushToken], title: str, body: str, data: dict | None) -> None:
    """Best-effort delivery to Expo's push service.

    Runs synchronously on the request thread (this backend has no background
    task queue) with a short timeout — a slow or unreachable Expo endpoint
    must never block or fail the order-status change / admin action that
    triggered the notification. Any stale token Expo reports as no longer
    registered is queued for deletion on the caller's next commit.
    """
    messages = [
        {"to": token.token, "title": title, "body": body, "data": data or {}, "sound": "default"}
        for token in tokens
    ]
    try:
        response = httpx.post(
            EXPO_PUSH_URL,
            json=messages,
            timeout=PUSH_REQUEST_TIMEOUT_SECONDS,
            headers={"Content-Type": "application/json", "Accept": "application/json"},
        )
        response.raise_for_status()
        results = response.json().get("data", [])
    except Exception:
        return

    stale_token_ids = [
        token.id
        for token, result in zip(tokens, results)
        if isinstance(result, dict)
        and result.get("status") == "error"
        and result.get("details", {}).get("error") == "DeviceNotRegistered"
    ]
    if stale_token_ids:
        db.query(PushToken).filter(PushToken.id.in_(stale_token_ids)).delete(synchronize_session=False)


def send_push_to_user(db: Session, user_id: UUID, title: str, body: str, data: dict | None = None) -> None:
    tokens = list(db.scalars(select(PushToken).where(PushToken.user_id == user_id)))
    if not tokens:
        return
    _send_expo_push(db, tokens, title, body, data)


def send_push_to_users(db: Session, user_ids: list[UUID], title: str, body: str, data: dict | None = None) -> int:
    """Returns the number of distinct users who had at least one device to notify."""
    if not user_ids:
        return 0
    tokens = list(db.scalars(select(PushToken).where(PushToken.user_id.in_(user_ids))))
    if not tokens:
        return 0
    _send_expo_push(db, tokens, title, body, data)
    return len({token.user_id for token in tokens})


def send_push_to_users_in_background(user_ids: list[UUID], title: str, body: str, data: dict | None = None) -> None:
    """Performance & Reliability (Phase 39) — the version scheduled via
    FastAPI's BackgroundTasks from a hot request/webhook path, instead of
    calling send_push_to_users() directly on the request's own db Session.
    A request-scoped Session is not safe to reuse from a background task
    (its lifetime is tied to the request's dependency teardown), so this
    opens and owns a completely independent Session for the whole call —
    including committing the stale-token cleanup send_push_to_users()
    itself never commits, since there's no longer a caller's own
    transaction here to piggyback on."""
    from app.db.session import SessionLocal

    db = SessionLocal()
    try:
        send_push_to_users(db, user_ids, title, body, data)
        db.commit()
    except Exception:
        logger.exception("Background push notification delivery failed for %d user(s)", len(user_ids))
        db.rollback()
    finally:
        db.close()
