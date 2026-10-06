import logging
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.core.observability import log_event
from app.models.push_token import PushToken
from app.services.push.expo_provider import ExpoPushProvider
from app.services.push.provider import PushMessage, PushProvider

logger = logging.getLogger(__name__)

# Push Notification Service (Phase 17) — this module is the
# "NotificationProvider" business-logic layer's own dependency on push
# delivery: it knows about PushToken rows and this codebase's user_id-
# scoped sending, but never about a provider's raw HTTP shape — that's
# entirely behind the PushProvider interface now (see app/services/push/).
# Built once at import time, exactly like payment_service.py's own
# module-level RazorpayProvider() — safe even with EXPO_ACCESS_TOKEN
# unset, since ExpoPushProvider only reads it lazily, per call.
_provider: PushProvider = ExpoPushProvider()


def _send_push(db: Session, tokens: list[PushToken], title: str, body: str, data: dict | None) -> None:
    """Best-effort delivery through the configured PushProvider.

    Runs synchronously on the request thread (this backend has no background
    task queue) with a short timeout — a slow or unreachable provider endpoint
    must never block or fail the order-status change / admin action that
    triggered the notification. Any token the provider reports as
    permanently dead (handle_failure) is soft-deactivated on the caller's
    next commit.

    Invalid Push Token Cleanup (Phase 32) — "mark token inactive," not
    delete: a prior design (Phase 14) hard-deleted here, reasoning that
    a provider-confirmed-dead token had no remaining value — this phase's
    own explicit "do not delete useful device records unnecessarily"
    overrides that. Deactivating instead of deleting preserves
    device_identifier/last_seen_at/created_at (useful for diagnosing why
    a device went dead, and for admin visibility into a user's device
    history) and means a future upsert_push_token() call from the exact
    same device (matched by device_identifier, see Push Token Domain
    Phase 14) can revive this same row via a rotated token rather than
    leaving an orphaned dead row and creating an unrelated new one.
    Already-inactive tokens are never selected in the first place
    (send_push_to_user/_users both filter is_active) — "never repeatedly
    send to a known-invalid token" holds either way, deleted or merely
    deactivated.
    """
    messages = [PushMessage(to=token.token, title=title, body=body, data=data) for token in tokens]
    # Observability (Phase 43) — one line per batch, not per token: this
    # already fires for every notify_* call across the whole platform,
    # so per-recipient logging here would dwarf every other log line in
    # the system for no diagnostic benefit over an aggregate count.
    # Never logs title/body/data (could carry order numbers/amounts —
    # not a secret, but not this log line's business either) or the raw
    # token string — only counts and provider-assigned ids.
    log_event(logger, "notification_dispatched", provider=_provider.name, recipient_count=len(messages))
    results = _provider.send_batch(messages)

    delivered = sum(1 for r in results if r.status == "ok")
    failed = len(results) - delivered
    if delivered:
        log_event(logger, "notification_delivered", provider=_provider.name, count=delivered)
    if failed:
        log_event(logger, "notification_failed", provider=_provider.name, count=failed)

    stale_token_ids = [
        token.id for token, result in zip(tokens, results) if _provider.handle_failure(result)
    ]
    if stale_token_ids:
        # Individually, not aggregated — a token going permanently
        # invalid is rare and worth its own line to investigate later
        # (e.g. "why did this user's device suddenly go dead"). Only the
        # token row's own id, never the raw push token string itself.
        for token_id in stale_token_ids:
            log_event(logger, "push_token_invalid", push_token_id=token_id)
        db.execute(update(PushToken).where(PushToken.id.in_(stale_token_ids)).values(is_active=False))


def send_push_to_user(db: Session, user_id: UUID, title: str, body: str, data: dict | None = None) -> None:
    tokens = list(
        db.scalars(select(PushToken).where(PushToken.user_id == user_id, PushToken.is_active.is_(True)))
    )
    if not tokens:
        return
    _send_push(db, tokens, title, body, data)


def send_push_to_users(db: Session, user_ids: list[UUID], title: str, body: str, data: dict | None = None) -> int:
    """Returns the number of distinct users who had at least one device to notify."""
    if not user_ids:
        return 0
    tokens = list(
        db.scalars(select(PushToken).where(PushToken.user_id.in_(user_ids), PushToken.is_active.is_(True)))
    )
    if not tokens:
        return 0
    _send_push(db, tokens, title, body, data)
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
