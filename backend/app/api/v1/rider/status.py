from fastapi import APIRouter, Depends

from app.api.v1.deps import DbSession, require_rider
from app.models.user import User
from app.schemas.rider import RiderStatusRead, RiderStatusUpdate
from app.services.rider_service import build_rider_status, set_rider_online_status

router = APIRouter()


@router.get("/status", response_model=RiderStatusRead)
def get_status(db: DbSession, current_rider: User = Depends(require_rider)) -> RiderStatusRead:
    return build_rider_status(db, current_rider)


@router.patch("/status", response_model=RiderStatusRead)
def patch_status(
    payload: RiderStatusUpdate, db: DbSession, current_rider: User = Depends(require_rider)
) -> RiderStatusRead:
    return set_rider_online_status(db, current_rider, payload.is_online)
