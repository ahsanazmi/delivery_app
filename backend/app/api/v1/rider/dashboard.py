from fastapi import APIRouter, Depends

from app.api.v1.deps import DbSession, require_rider
from app.models.user import User
from app.schemas.rider_dashboard import RiderDashboardResponse
from app.services.rider_dashboard import get_rider_dashboard

router = APIRouter()


@router.get("/dashboard", response_model=RiderDashboardResponse)
def get_dashboard(db: DbSession, current_rider: User = Depends(require_rider)) -> RiderDashboardResponse:
    return get_rider_dashboard(db, current_rider)
