from fastapi import APIRouter, Depends, Query

from app.api.v1.deps import DbSession, require_rider
from app.models.user import User
from app.schemas.rider_wallet import RiderSettlementRead, RiderWalletRead
from app.services.rider_wallet import get_rider_wallet, list_rider_settlements

router = APIRouter()


@router.get("/wallet", response_model=RiderWalletRead)
def get_wallet(db: DbSession, current_rider: User = Depends(require_rider)) -> RiderWalletRead:
    return get_rider_wallet(db, current_rider)


@router.get("/wallet/settlements", response_model=list[RiderSettlementRead])
def get_wallet_settlements(
    db: DbSession,
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=50, ge=1, le=100),
    current_rider: User = Depends(require_rider),
) -> list[RiderSettlementRead]:
    offset = (page - 1) * limit
    return list_rider_settlements(db, current_rider, offset=offset, limit=limit)
