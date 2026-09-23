from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.platform_settings import PlatformSettings
from app.models.user import User
from app.schemas.admin import AdminPlatformSettingsRead, AdminPlatformSettingsUpdate
from app.services.admin_audit_log import record_admin_audit_log

_UPDATABLE_FIELDS = (
    "platform_name", "support_email", "support_phone", "default_delivery_fee",
    "default_minimum_order", "notifications_enabled", "maintenance_mode",
)


def get_platform_settings(db: Session) -> PlatformSettings:
    """Lazily creates the single settings row the first time anything asks
    for it — the same get-or-create pattern get_or_create_delivery_partner
    already uses, so there's no separate seed migration or "has this ever
    been configured" branch anywhere else in the codebase."""
    settings = db.scalar(select(PlatformSettings).order_by(PlatformSettings.created_at.asc()).limit(1))
    if settings:
        return settings
    settings = PlatformSettings()
    db.add(settings)
    db.commit()
    db.refresh(settings)
    return settings


def get_admin_platform_settings(db: Session) -> AdminPlatformSettingsRead:
    return AdminPlatformSettingsRead.model_validate(get_platform_settings(db), from_attributes=True)


def update_admin_platform_settings(
    db: Session, admin: User, payload: AdminPlatformSettingsUpdate, ip_address: str | None = None
) -> AdminPlatformSettingsRead:
    settings = get_platform_settings(db)
    updates = payload.model_dump(exclude_unset=True, exclude={"reason"})

    changed: dict[str, tuple[object, object]] = {}
    for field, new_value in updates.items():
        if field not in _UPDATABLE_FIELDS:
            continue
        old_value = getattr(settings, field)
        if old_value != new_value:
            changed[field] = (old_value, new_value)
        setattr(settings, field, new_value)

    if changed:
        record_admin_audit_log(
            db,
            admin_id=admin.id,
            action="settings.update",
            target_type="platform_settings",
            target_id=str(settings.id),
            reason=payload.reason or f"Updated: {', '.join(changed)}",
            previous_state=str({field: str(old) for field, (old, _new) in changed.items()})[:64],
            new_state=str({field: str(new) for field, (_old, new) in changed.items()})[:64],
            ip_address=ip_address,
        )

    db.commit()
    db.refresh(settings)
    return AdminPlatformSettingsRead.model_validate(settings, from_attributes=True)
