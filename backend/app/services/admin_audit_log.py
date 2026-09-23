import logging
from uuid import UUID

from sqlalchemy.orm import Session

from app.models.admin_audit_log import AdminAuditLog

logger = logging.getLogger(__name__)


def record_admin_audit_log(
    db: Session,
    *,
    admin_id: UUID,
    action: str,
    target_type: str,
    target_id: str,
    reason: str,
    previous_state: str | None = None,
    new_state: str | None = None,
    ip_address: str | None = None,
) -> AdminAuditLog:
    """Flushes (does not commit) so the caller's own commit — the one that
    also persists the actual intervention — covers both writes atomically.
    Never call this and then leave the session uncommitted on its own;
    every caller here is expected to go on to commit the real mutation in
    the same transaction, so a rollback undoes the log entry along with it."""
    entry = AdminAuditLog(
        admin_id=admin_id,
        action=action,
        target_type=target_type,
        target_id=target_id,
        reason=reason,
        previous_state=previous_state,
        new_state=new_state,
        ip_address=ip_address,
    )
    db.add(entry)
    db.flush()
    # Logging & Error Handling (Phase 26) — the AdminAuditLog row above
    # remains the authoritative, queryable record of every admin action;
    # this INFO-level line (only visible when LOG_LEVEL=INFO) is a
    # complementary text-log trail for ops tooling that tails logs rather
    # than queries the database — same fields, never anything beyond what's
    # already stored in the audit table, so no new exposure either way.
    logger.info(
        "Admin action: admin %s performed %s on %s %s (reason=%r)",
        admin_id, action, target_type, target_id, reason,
    )
    return entry
