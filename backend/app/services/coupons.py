from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.models.cart import Cart
from app.models.coupon import Coupon, CouponRedemption

_CENT = Decimal("0.01")


def _as_aware(value: datetime) -> datetime:
    """SQLite (used in tests) drops tzinfo on DateTime(timezone=True) columns
    on round-trip, unlike Postgres which always returns it. Treat a naive
    value as UTC so expiry comparisons work the same on both backends."""
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def calculate_coupon_discount(coupon: Coupon, order_total: Decimal) -> Decimal:
    if not coupon.is_active:
        return Decimal("0.00")
    now = datetime.now(UTC)
    if coupon.start_date and now < _as_aware(coupon.start_date):
        return Decimal("0.00")
    if coupon.end_date and now > _as_aware(coupon.end_date):
        return Decimal("0.00")
    if order_total < coupon.min_order:
        return Decimal("0.00")

    discount_type = getattr(coupon.discount_type, "value", str(coupon.discount_type))
    if discount_type == "percent":
        # Financial Consistency Test (Phase 23) — quantized to the cent,
        # same rounding mode compute_effective_commission already uses for
        # commission, so a percent discount is never displayed or stored
        # with more precision than real money has (was returning values
        # like 20.0000 instead of 20.00).
        discount = (order_total * coupon.discount_value / Decimal("100")).quantize(_CENT, rounding=ROUND_HALF_UP)
    else:
        discount = coupon.discount_value

    if coupon.max_discount is not None:
        discount = min(discount, coupon.max_discount)
    return min(discount, order_total)


def get_coupon_by_code(db: Session, code: str) -> Coupon | None:
    return db.scalar(select(Coupon).where(Coupon.code == code.strip().upper(), Coupon.is_active.is_(True)))


def list_available_coupons(db: Session) -> list[Coupon]:
    now = datetime.now(UTC)
    statement = (
        select(Coupon)
        .where(
            Coupon.is_active.is_(True),
            or_(Coupon.start_date.is_(None), Coupon.start_date <= now),
            or_(Coupon.end_date.is_(None), Coupon.end_date >= now),
        )
        .order_by(Coupon.created_at.desc())
    )
    return list(db.scalars(statement))


def validate_coupon(db: Session, code: str, order_total: Decimal) -> Coupon:
    coupon = get_coupon_by_code(db, code)
    if not coupon:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Coupon not found or inactive")
    now = datetime.now(UTC)
    if coupon.start_date and now < _as_aware(coupon.start_date):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="This coupon isn't active yet")
    if coupon.end_date and now > _as_aware(coupon.end_date):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="This coupon has expired")
    if order_total < coupon.min_order:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Order total is below the coupon minimum")
    return coupon


def _coupon_usage_count(db: Session, coupon_id: UUID, user_id: UUID | None = None) -> int:
    query = db.query(CouponRedemption).filter(CouponRedemption.coupon_id == coupon_id)
    if user_id is not None:
        query = query.filter(CouponRedemption.user_id == user_id)
    return query.count()


def validate_coupon_for_cart(db: Session, coupon: Coupon, user_id: UUID, cart: Cart, subtotal: Decimal) -> None:
    """Every server-side rule from the phase spec, in one place: expiry,
    minimum order, restaurant eligibility, usage limits, customer eligibility.
    Raises HTTPException with a customer-readable reason on the first rule
    that fails."""
    now = datetime.now(UTC)
    if not coupon.is_active:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="This coupon is no longer active.")
    if coupon.start_date and now < _as_aware(coupon.start_date):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="This coupon isn't active yet.")
    if coupon.end_date and now > _as_aware(coupon.end_date):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="This coupon has expired.")
    if subtotal < coupon.min_order:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Add {coupon.min_order - subtotal} more to use this coupon (minimum order {coupon.min_order}).",
        )
    if coupon.restaurant_id and cart.restaurant_id and coupon.restaurant_id != cart.restaurant_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="This coupon isn't valid for this restaurant.")
    if coupon.usage_limit is not None and _coupon_usage_count(db, coupon.id) >= coupon.usage_limit:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="This coupon has reached its usage limit.")
    if coupon.per_customer_limit is not None and _coupon_usage_count(db, coupon.id, user_id) >= coupon.per_customer_limit:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="You've already used this coupon the maximum number of times.",
        )


def apply_coupon_to_cart(db: Session, user_id: UUID, cart: Cart, code: str) -> Cart:
    if not cart.items:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Add items to your cart before applying a coupon.")

    coupon = get_coupon_by_code(db, code)
    if not coupon:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Coupon not found.")

    subtotal = sum((item.unit_price * item.quantity for item in cart.items), Decimal("0.00"))
    validate_coupon_for_cart(db, coupon, user_id, cart, subtotal)

    cart.coupon_id = coupon.id
    db.commit()
    db.refresh(cart)
    return cart


def remove_coupon_from_cart(db: Session, cart: Cart) -> Cart:
    cart.coupon_id = None
    db.commit()
    db.refresh(cart)
    return cart


def record_coupon_redemption(db: Session, coupon_id: UUID, user_id: UUID, order_id: UUID) -> None:
    db.add(CouponRedemption(coupon_id=coupon_id, user_id=user_id, order_id=order_id))
