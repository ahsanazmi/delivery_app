from fastapi import APIRouter, Depends

from app.api.v1.deps import DbSession, require_rider
from app.models.user import User
from app.schemas.rider import RiderProfileUpdate
from app.schemas.user import UserRead
from app.services.rider_service import update_rider_profile

router = APIRouter()


@router.get("/profile", response_model=UserRead)
def get_profile(current_rider: User = Depends(require_rider)) -> UserRead:
    return current_rider


@router.patch("/profile", response_model=UserRead)
def patch_profile(
    payload: RiderProfileUpdate,
    db: DbSession,
    current_rider: User = Depends(require_rider),
) -> UserRead:
    return update_rider_profile(db, current_rider, payload)
