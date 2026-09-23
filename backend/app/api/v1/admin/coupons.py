from uuid import UUID

from fastapi import APIRouter, Depends, Query, status

from app.api.v1.deps import DbSession, require_admin
from app.models.coupon import DiscountType
from app.models.user import User
from app.schemas.admin import AdminCouponCreate, AdminCouponListResponse, AdminCouponRead, AdminCouponUpdate
from app.services.admin_coupons import (
    create_admin_coupon,
    delete_admin_coupon,
    get_admin_coupon_detail,
    list_admin_coupons,
    update_admin_coupon,
)

router = APIRouter()


@router.get("/coupons", response_model=AdminCouponListResponse)
def list_coupons(
    db: DbSession,
    search: str | None = Query(default=None),
    discount_type: DiscountType | None = Query(default=None),
    is_active: bool | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=20, ge=1, le=100),
    current_admin: User = Depends(require_admin),
) -> AdminCouponListResponse:
    return list_admin_coupons(db, search=search, discount_type=discount_type, is_active=is_active, page=page, limit=limit)


@router.post("/coupons", response_model=AdminCouponRead, status_code=status.HTTP_201_CREATED)
def create_coupon(payload: AdminCouponCreate, db: DbSession, current_admin: User = Depends(require_admin)) -> AdminCouponRead:
    return create_admin_coupon(db, payload)


# Registered after the plain list on purpose — same established convention
# as every other admin list-then-detail route pair.
@router.get("/coupons/{coupon_id}", response_model=AdminCouponRead)
def get_coupon(coupon_id: UUID, db: DbSession, current_admin: User = Depends(require_admin)) -> AdminCouponRead:
    return get_admin_coupon_detail(db, coupon_id)


@router.patch("/coupons/{coupon_id}", response_model=AdminCouponRead)
def update_coupon(
    coupon_id: UUID, payload: AdminCouponUpdate, db: DbSession, current_admin: User = Depends(require_admin)
) -> AdminCouponRead:
    return update_admin_coupon(db, coupon_id, payload)


@router.delete("/coupons/{coupon_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_coupon(coupon_id: UUID, db: DbSession, current_admin: User = Depends(require_admin)) -> None:
    delete_admin_coupon(db, coupon_id)
