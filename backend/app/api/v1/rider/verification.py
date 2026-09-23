from fastapi import APIRouter, Depends

from app.api.v1.deps import DbSession, require_rider
from app.models.user import User
from app.schemas.rider import RiderVerificationRead
from app.services.rider_service import get_or_create_delivery_partner, resubmit_rider_verification

router = APIRouter()


@router.get("/verification", response_model=RiderVerificationRead)
def get_verification(db: DbSession, current_rider: User = Depends(require_rider)) -> RiderVerificationRead:
    return get_or_create_delivery_partner(db, current_rider)


@router.post("/verification/resubmit", response_model=RiderVerificationRead)
def resubmit_verification(db: DbSession, current_rider: User = Depends(require_rider)) -> RiderVerificationRead:
    return resubmit_rider_verification(db, current_rider)
