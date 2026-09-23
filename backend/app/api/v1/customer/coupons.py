from fastapi import APIRouter, Depends

from app.api.v1.deps import DbSession, require_customer
from app.models.user import User
from app.schemas.coupon import CustomerCouponRead
from app.services.coupons import list_available_coupons

router = APIRouter()


@router.get("/coupons", response_model=list[CustomerCouponRead])
def get_available_coupons(db: DbSession, current_user: User = Depends(require_customer)) -> list[CustomerCouponRead]:
    coupons = list_available_coupons(db)
    return [CustomerCouponRead.model_validate(c) for c in coupons]
