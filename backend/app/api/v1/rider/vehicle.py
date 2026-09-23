from fastapi import APIRouter, Depends

from app.api.v1.deps import DbSession, require_rider
from app.models.user import User
from app.schemas.rider import RiderVehicleRead, RiderVehicleUpdate
from app.services.rider_service import get_or_create_delivery_partner, update_rider_vehicle

router = APIRouter()


@router.get("/vehicle", response_model=RiderVehicleRead)
def get_vehicle(db: DbSession, current_rider: User = Depends(require_rider)) -> RiderVehicleRead:
    return get_or_create_delivery_partner(db, current_rider)


@router.patch("/vehicle", response_model=RiderVehicleRead)
def patch_vehicle(
    payload: RiderVehicleUpdate, db: DbSession, current_rider: User = Depends(require_rider)
) -> RiderVehicleRead:
    return update_rider_vehicle(db, current_rider, payload)
