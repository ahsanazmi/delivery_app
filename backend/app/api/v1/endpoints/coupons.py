from decimal import Decimal

from fastapi import APIRouter, HTTPException, Query, status

from app.api.v1.deps import DbSession
from app.models.coupon import Coupon
from app.schemas.coupon import CouponCreate, CouponRead
from app.services.coupons import calculate_coupon_discount, get_coupon_by_code, validate_coupon

router = APIRouter()


@router.get("", response_model=list[CouponRead])
def list_coupons(db: DbSession) -> list[CouponRead]:
    return list(db.query(Coupon).order_by(Coupon.created_at.desc()).all())


@router.post("", response_model=CouponRead, status_code=status.HTTP_201_CREATED)
def create_coupon(payload: CouponCreate, db: DbSession) -> CouponRead:
    coupon = Coupon(**payload.model_dump())
    coupon.code = coupon.code.upper()
    db.add(coupon)
    db.commit()
    db.refresh(coupon)
    return coupon


@router.get("/{code}", response_model=CouponRead)
def get_coupon(code: str, db: DbSession) -> CouponRead:
    coupon = get_coupon_by_code(db, code)
    if not coupon:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Coupon not found")
    return coupon


@router.post("/validate")
def validate_coupon_endpoint(code: str = Query(...), order_total: Decimal = Query(...), db: DbSession = DbSession) -> dict[str, Decimal | str]:
    coupon = validate_coupon(db, code, order_total)
    return {
        "code": coupon.code,
        "discount": calculate_coupon_discount(coupon, order_total),
        "discount_type": coupon.discount_type.value,
    }
