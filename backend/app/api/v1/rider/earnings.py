from fastapi import APIRouter, Depends, Query

from app.api.v1.deps import DbSession, require_rider
from app.models.user import User
from app.schemas.rider_earning import RiderEarningRead, RiderEarningsSummaryRead
from app.services.rider_earnings import get_rider_earnings_summary, list_rider_earnings

router = APIRouter()


@router.get("/earnings", response_model=list[RiderEarningRead])
def get_rider_earnings(
    db: DbSession,
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=50, ge=1, le=100),
    current_rider: User = Depends(require_rider),
) -> list[RiderEarningRead]:
    offset = (page - 1) * limit
    return list_rider_earnings(db, current_rider, offset=offset, limit=limit)


@router.get("/earnings/summary", response_model=RiderEarningsSummaryRead)
def get_rider_earnings_summary_request(
    db: DbSession, current_rider: User = Depends(require_rider)
) -> RiderEarningsSummaryRead:
    return get_rider_earnings_summary(db, current_rider)
