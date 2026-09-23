from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.api.v1.deps import DbSession, require_roles
from app.models.coupon import Coupon
from app.models.user import User, UserRole
from app.schemas.coupon import CouponCreate, CouponRead
from app.services.coupons import calculate_coupon_discount, get_coupon_by_code, validate_coupon

router = APIRouter()

# Every route here manages the master coupon catalog (create/list/inspect
# full internal fields like usage_limit and is_active) — customer-facing
# coupon browsing and application already has its own properly scoped,
# authenticated surface under /api/v1/customer/{coupons,cart/apply-coupon}
# (see api/v1/customer/coupons.py and services/coupons.py). This router is
# for admins managing that catalog, not for customers.
RequireAdmin = Depends(require_roles(UserRole.ADMIN))


@router.get("", response_model=list[CouponRead])
def list_coupons(db: DbSession, current_user: User = RequireAdmin) -> list[CouponRead]:
    return list(db.query(Coupon).order_by(Coupon.created_at.desc()).all())


@router.post("", response_model=CouponRead, status_code=status.HTTP_201_CREATED)
def create_coupon(payload: CouponCreate, db: DbSession, current_user: User = RequireAdmin) -> CouponRead:
    coupon = Coupon(**payload.model_dump())
    coupon.code = coupon.code.upper()
    db.add(coupon)
    db.commit()
    db.refresh(coupon)
    return coupon


@router.get("/{code}", response_model=CouponRead)
def get_coupon(code: str, db: DbSession, current_user: User = RequireAdmin) -> CouponRead:
    coupon = get_coupon_by_code(db, code)
    if not coupon:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Coupon not found")
    return coupon


@router.post("/validate")
def validate_coupon_endpoint(
    db: DbSession, current_user: User = RequireAdmin, code: str = Query(...), order_total: Decimal = Query(...)
) -> dict[str, Decimal | str]:
    coupon = validate_coupon(db, code, order_total)
    return {
        "code": coupon.code,
        "discount": calculate_coupon_discount(coupon, order_total),
        "discount_type": coupon.discount_type.value,
    }
