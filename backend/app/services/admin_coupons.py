from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.coupon import Coupon, CouponRedemption, DiscountType
from app.models.restaurant import Restaurant
from app.schemas.admin import AdminCouponCreate, AdminCouponListResponse, AdminCouponRead, AdminCouponUpdate


def _redemption_counts(db: Session, coupon_ids: list[UUID]) -> dict[UUID, int]:
    if not coupon_ids:
        return {}
    rows = db.execute(
        select(CouponRedemption.coupon_id, func.count(CouponRedemption.id))
        .where(CouponRedemption.coupon_id.in_(coupon_ids))
        .group_by(CouponRedemption.coupon_id)
    ).all()
    return dict(rows)


def _to_read(coupon: Coupon, restaurant_name: str | None, redemption_count: int) -> AdminCouponRead:
    return AdminCouponRead(
        id=coupon.id,
        code=coupon.code,
        discount_type=coupon.discount_type,
        discount_value=coupon.discount_value,
        min_order=coupon.min_order,
        max_discount=coupon.max_discount,
        start_date=coupon.start_date,
        end_date=coupon.end_date,
        usage_limit=coupon.usage_limit,
        per_customer_limit=coupon.per_customer_limit,
        restaurant_id=coupon.restaurant_id,
        restaurant_name=restaurant_name,
        is_active=coupon.is_active,
        redemption_count=redemption_count,
        created_at=coupon.created_at,
        updated_at=coupon.updated_at,
    )


def _assert_percent_within_range(coupon: Coupon) -> None:
    if coupon.discount_type == DiscountType.PERCENT and coupon.discount_value > 100:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="A percentage discount cannot exceed 100")


def _assert_end_after_start(coupon: Coupon) -> None:
    if coupon.start_date and coupon.end_date and coupon.end_date <= coupon.start_date:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="end_date must be after start_date")


def list_admin_coupons(
    db: Session, *, search: str | None, discount_type: DiscountType | None, is_active: bool | None, page: int, limit: int
) -> AdminCouponListResponse:
    conditions = []
    if search:
        conditions.append(Coupon.code.ilike(f"%{search.strip()}%"))
    if discount_type is not None:
        conditions.append(Coupon.discount_type == discount_type)
    if is_active is not None:
        conditions.append(Coupon.is_active.is_(is_active))

    total = db.scalar(select(func.count()).select_from(Coupon).where(*conditions)) or 0

    offset = (page - 1) * limit
    coupons = db.scalars(
        select(Coupon).where(*conditions).order_by(Coupon.created_at.desc()).offset(offset).limit(limit)
    ).all()

    restaurant_ids = [c.restaurant_id for c in coupons if c.restaurant_id]
    restaurants = {r.id: r for r in db.scalars(select(Restaurant).where(Restaurant.id.in_(restaurant_ids)))} if restaurant_ids else {}
    counts = _redemption_counts(db, [c.id for c in coupons])

    items = [
        _to_read(c, restaurants[c.restaurant_id].name if c.restaurant_id in restaurants else None, counts.get(c.id, 0))
        for c in coupons
    ]
    return AdminCouponListResponse(items=items, total=total, page=page, limit=limit)


def _get_coupon_or_404(db: Session, coupon_id: UUID) -> Coupon:
    coupon = db.get(Coupon, coupon_id)
    if not coupon:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Coupon not found")
    return coupon


def _get_restaurant_name(db: Session, restaurant_id: UUID | None) -> str | None:
    if restaurant_id is None:
        return None
    restaurant = db.get(Restaurant, restaurant_id)
    return restaurant.name if restaurant else None


def get_admin_coupon_detail(db: Session, coupon_id: UUID) -> AdminCouponRead:
    coupon = _get_coupon_or_404(db, coupon_id)
    redemption_count = _redemption_counts(db, [coupon.id]).get(coupon.id, 0)
    return _to_read(coupon, _get_restaurant_name(db, coupon.restaurant_id), redemption_count)


def create_admin_coupon(db: Session, payload: AdminCouponCreate) -> AdminCouponRead:
    if payload.restaurant_id is not None and not db.get(Restaurant, payload.restaurant_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Restaurant {payload.restaurant_id} not found")

    coupon = Coupon(
        code=payload.code.strip().upper(),
        discount_type=payload.discount_type,
        discount_value=payload.discount_value,
        min_order=payload.min_order,
        max_discount=payload.max_discount,
        start_date=payload.start_date,
        end_date=payload.end_date,
        usage_limit=payload.usage_limit,
        per_customer_limit=payload.per_customer_limit,
        restaurant_id=payload.restaurant_id,
        is_active=payload.is_active,
    )
    db.add(coupon)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=f"A coupon with code '{coupon.code}' already exists") from exc
    db.refresh(coupon)
    return _to_read(coupon, _get_restaurant_name(db, coupon.restaurant_id), 0)


def update_admin_coupon(db: Session, coupon_id: UUID, payload: AdminCouponUpdate) -> AdminCouponRead:
    coupon = _get_coupon_or_404(db, coupon_id)

    if payload.restaurant_id is not None and not db.get(Restaurant, payload.restaurant_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Restaurant {payload.restaurant_id} not found")

    if payload.code is not None:
        coupon.code = payload.code.strip().upper()
    if payload.discount_type is not None:
        coupon.discount_type = payload.discount_type
    if payload.discount_value is not None:
        coupon.discount_value = payload.discount_value
    if payload.min_order is not None:
        coupon.min_order = payload.min_order
    if payload.max_discount is not None:
        coupon.max_discount = payload.max_discount
    if payload.start_date is not None:
        coupon.start_date = payload.start_date
    if payload.end_date is not None:
        coupon.end_date = payload.end_date
    if payload.usage_limit is not None:
        coupon.usage_limit = payload.usage_limit
    if payload.per_customer_limit is not None:
        coupon.per_customer_limit = payload.per_customer_limit
    if payload.restaurant_id is not None:
        coupon.restaurant_id = payload.restaurant_id
    if payload.is_active is not None:
        coupon.is_active = payload.is_active

    # Checked against the merged, final state — a PATCH that only sends
    # discount_value on an already-PERCENT coupon must still be caught,
    # not just the case where both fields arrive in the same request
    # (which AdminCouponUpdate's own schema validator already covers).
    _assert_percent_within_range(coupon)
    _assert_end_after_start(coupon)

    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=f"A coupon with code '{coupon.code}' already exists") from exc
    db.refresh(coupon)
    redemption_count = _redemption_counts(db, [coupon.id]).get(coupon.id, 0)
    return _to_read(coupon, _get_restaurant_name(db, coupon.restaurant_id), redemption_count)


def delete_admin_coupon(db: Session, coupon_id: UUID) -> None:
    """A real delete, blocked while any redemption history exists — unlike
    a category's restaurant_id (a SET NULL FK, just an orphaned reference),
    CouponRedemption cascades on coupon delete, which would destroy the
    actual record of who used this coupon and when. Deactivate
    (is_active=False) instead to retire a coupon that's already been used."""
    coupon = _get_coupon_or_404(db, coupon_id)
    redemption_count = _redemption_counts(db, [coupon.id]).get(coupon.id, 0)
    if redemption_count > 0:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Cannot delete — this coupon has been redeemed {redemption_count} time(s). Deactivate it instead.",
        )
    db.delete(coupon)
    db.commit()
