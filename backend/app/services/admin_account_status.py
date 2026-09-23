from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.models.user import User
from app.services.admin_audit_log import record_admin_audit_log


def set_user_active_status(
    db: Session,
    admin: User,
    user: User,
    *,
    target_active: bool,
    action: str,
    target_type: str,
    reason: str,
    ip_address: str | None = None,
) -> None:
    """Admin Portal Phase 23 — the single choke point every account-level
    activation/suspension action (customer, restaurant owner, rider) goes
    through: validates the user isn't already in the requested state,
    flips User.is_active, and writes the audit log entry before the
    caller's own commit. Never a generic "set any field" mutation — the
    only thing this ever touches is is_active, and only via one of the two
    fixed target_active values a caller passes explicitly."""
    if user.is_active == target_active:
        state_word = "active" if target_active else "suspended"
        label = target_type.replace("_", " ")
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=f"This {label} is already {state_word}.")

    previous_active = user.is_active
    user.is_active = target_active
    record_admin_audit_log(
        db,
        admin_id=admin.id,
        action=action,
        target_type=target_type,
        target_id=str(user.id),
        reason=reason,
        previous_state=str(previous_active),
        new_state=str(target_active),
        ip_address=ip_address,
    )
