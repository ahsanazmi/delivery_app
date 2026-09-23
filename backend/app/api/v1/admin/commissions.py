from fastapi import APIRouter, Depends

from app.api.v1.deps import DbSession, require_admin
from app.models.user import User
from app.schemas.admin import AdminCommissionConfigRead, AdminCommissionUpdateRequest
from app.services.admin_commissions import get_admin_commission_config, update_admin_commission_config

router = APIRouter()


@router.get("/commissions", response_model=AdminCommissionConfigRead)
def get_commissions(db: DbSession, current_admin: User = Depends(require_admin)) -> AdminCommissionConfigRead:
    return get_admin_commission_config(db)


@router.patch("/commissions", response_model=AdminCommissionConfigRead)
def update_commissions(
    payload: AdminCommissionUpdateRequest, db: DbSession, current_admin: User = Depends(require_admin)
) -> AdminCommissionConfigRead:
    return update_admin_commission_config(db, payload)
