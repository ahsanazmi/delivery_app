from fastapi import APIRouter, Depends, Request

from app.api.v1.deps import DbSession, require_admin
from app.models.user import User
from app.schemas.admin import AdminPlatformSettingsRead, AdminPlatformSettingsUpdate
from app.services.admin_settings import get_admin_platform_settings, update_admin_platform_settings

router = APIRouter()


@router.get("/settings", response_model=AdminPlatformSettingsRead)
def get_settings(db: DbSession, current_admin: User = Depends(require_admin)) -> AdminPlatformSettingsRead:
    return get_admin_platform_settings(db)


@router.patch("/settings", response_model=AdminPlatformSettingsRead)
def update_settings(
    payload: AdminPlatformSettingsUpdate,
    db: DbSession,
    request: Request,
    current_admin: User = Depends(require_admin),
) -> AdminPlatformSettingsRead:
    ip_address = request.client.host if request.client else None
    return update_admin_platform_settings(db, current_admin, payload, ip_address)
