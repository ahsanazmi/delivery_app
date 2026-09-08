from decimal import Decimal

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.coupon import Coupon


def calculate_coupon_discount(coupon: Coupon, order_total: Decimal) -> Decimal:
    if not coupon.is_active:
        return Decimal("0.00")
    if order_total < coupon.min_order:
        return Decimal("0.00")

    discount_type = getattr(coupon.discount_type, "value", str(coupon.discount_type))
    if discount_type == "percent":
        discount = (order_total * coupon.discount_value) / Decimal("100")
    else:
        discount = coupon.discount_value

    if coupon.max_discount is not None:
        discount = min(discount, coupon.max_discount)
    return min(discount, order_total)


def get_coupon_by_code(db: Session, code: str) -> Coupon | None:
    return db.scalar(select(Coupon).where(Coupon.code == code.strip().upper(), Coupon.is_active.is_(True)))


def validate_coupon(db: Session, code: str, order_total: Decimal) -> Coupon:
    coupon = get_coupon_by_code(db, code)
    if not coupon:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Coupon not found or inactive")
    if order_total < coupon.min_order:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Order total is below the coupon minimum")
    return coupon
