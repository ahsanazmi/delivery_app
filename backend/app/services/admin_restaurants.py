from decimal import Decimal
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from app.models.delivery_partner import ApprovalStatus
from app.models.order import Order, OrderStatus
from app.models.product import Product
from app.models.restaurant import Restaurant
from app.models.user import User
from app.schemas.admin import (
    AdminMenuItem,
    AdminRecentOrder,
    AdminRestaurantDetail,
    AdminRestaurantListResponse,
    AdminRestaurantStatus,
    AdminRestaurantSummary,
)
from app.services.admin_audit_log import record_admin_audit_log

_ZERO = Decimal("0.00")
RECENT_ORDERS_LIMIT = 20


def _status_to_is_active(value: AdminRestaurantStatus) -> bool:
    return value == "ACTIVE"


def _is_active_to_status(is_active: bool) -> AdminRestaurantStatus:
    return "ACTIVE" if is_active else "INACTIVE"


def _order_stats_by_restaurant(db: Session, restaurant_ids: list[UUID]) -> dict[UUID, tuple[int, Decimal]]:
    """Batch-fetch {restaurant_id: (order_count, total_revenue)} in one query
    — Order.restaurant_id is a denormalized str(uuid) snapshot, not an FK, so
    the join is on that string form; same N+1-avoidance discipline as
    admin_customers.py / Phase 30."""
    if not restaurant_ids:
        return {}
    id_strings = [str(rid) for rid in restaurant_ids]
    rows = db.execute(
        select(
            Order.restaurant_id,
            func.count(Order.id),
            func.coalesce(func.sum(case((Order.status == OrderStatus.DELIVERED, Order.total), else_=_ZERO)), _ZERO),
        )
        .where(Order.restaurant_id.in_(id_strings))
        .group_by(Order.restaurant_id)
    ).all()
    return {UUID(restaurant_id): (count, revenue) for restaurant_id, count, revenue in rows}


def _owners_by_id(db: Session, owner_ids: list[UUID]) -> dict[UUID, User]:
    if not owner_ids:
        return {}
    owners = db.scalars(select(User).where(User.id.in_(owner_ids))).all()
    return {owner.id: owner for owner in owners}


def _to_summary(restaurant: Restaurant, owner: User, order_count: int, total_revenue: Decimal) -> AdminRestaurantSummary:
    return AdminRestaurantSummary(
        id=restaurant.id,
        name=restaurant.name,
        phone=restaurant.phone,
        email=restaurant.email,
        owner_id=restaurant.owner_id,
        owner_name=owner.name if owner else "Unknown owner",
        status=_is_active_to_status(restaurant.is_active),
        approval_status=restaurant.approval_status,
        rejection_reason=restaurant.rejection_reason,
        is_open=restaurant.is_open,
        average_rating=restaurant.average_rating,
        created_at=restaurant.created_at,
        order_count=order_count,
        total_revenue=total_revenue,
    )


def list_admin_restaurants(
    db: Session,
    *,
    search: str | None,
    status_filter: AdminRestaurantStatus | None,
    is_open: bool | None,
    approval_filter: ApprovalStatus | None,
    page: int,
    limit: int,
) -> AdminRestaurantListResponse:
    conditions = []
    if search:
        pattern = f"%{search.strip()}%"
        conditions.append((Restaurant.name.ilike(pattern)) | (Restaurant.phone.ilike(pattern)) | (Restaurant.email.ilike(pattern)))
    if status_filter is not None:
        conditions.append(Restaurant.is_active.is_(_status_to_is_active(status_filter)))
    if is_open is not None:
        conditions.append(Restaurant.is_open.is_(is_open))
    if approval_filter is not None:
        conditions.append(Restaurant.approval_status == approval_filter)

    total = db.scalar(select(func.count()).select_from(Restaurant).where(*conditions)) or 0

    offset = (page - 1) * limit
    restaurants = db.scalars(
        select(Restaurant).where(*conditions).order_by(Restaurant.created_at.desc()).offset(offset).limit(limit)
    ).all()

    stats = _order_stats_by_restaurant(db, [r.id for r in restaurants])
    owners = _owners_by_id(db, [r.owner_id for r in restaurants])

    items = [
        _to_summary(r, owners.get(r.owner_id), *stats.get(r.id, (0, _ZERO)))
        for r in restaurants
    ]
    return AdminRestaurantListResponse(items=items, total=total, page=page, limit=limit)


def _get_restaurant_or_404(db: Session, restaurant_id: UUID) -> Restaurant:
    restaurant = db.get(Restaurant, restaurant_id)
    if not restaurant:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Restaurant not found")
    return restaurant


def get_admin_restaurant_detail(db: Session, restaurant_id: UUID) -> AdminRestaurantDetail:
    restaurant = _get_restaurant_or_404(db, restaurant_id)
    owner = db.get(User, restaurant.owner_id)
    order_count, total_revenue = _order_stats_by_restaurant(db, [restaurant.id]).get(restaurant.id, (0, _ZERO))

    menu = db.scalars(
        select(Product).where(Product.restaurant_id == restaurant.id).order_by(Product.name.asc())
    )
    recent_orders = db.scalars(
        select(Order)
        .where(Order.restaurant_id == str(restaurant.id))
        .order_by(Order.created_at.desc())
        .limit(RECENT_ORDERS_LIMIT)
    )

    summary = _to_summary(restaurant, owner, order_count, total_revenue)
    return AdminRestaurantDetail(
        **summary.model_dump(),
        owner_email=owner.email if owner else None,
        owner_phone=owner.phone if owner else None,
        menu=[AdminMenuItem(id=p.id, name=p.name, price=p.price, is_active=p.is_active) for p in menu],
        recent_orders=[
            AdminRecentOrder(
                id=order.id,
                order_number=order.order_number,
                restaurant_name=order.restaurant_name,
                customer_name=order.customer_name,
                status=order.status,
                total=order.total,
                created_at=order.created_at,
            )
            for order in recent_orders
        ],
    )


# Phase 23 — replaces the old PATCH-with-status generic setter. Named
# deactivate/reactivate (not suspend/activate) to stay unambiguous next to
# the approval-status actions just below, which already own those two
# words for a completely different concept (Restaurant.approval_status).
def deactivate_admin_restaurant(
    db: Session, admin: User, restaurant_id: UUID, reason: str, ip_address: str | None = None
) -> AdminRestaurantDetail:
    restaurant = _get_restaurant_or_404(db, restaurant_id)
    if not restaurant.is_active:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="This restaurant is already deactivated.")
    restaurant.is_active = False
    restaurant.is_open = False
    record_admin_audit_log(
        db, admin_id=admin.id, action="restaurant.deactivate", target_type="restaurant", target_id=str(restaurant.id),
        reason=reason, previous_state="True", new_state="False", ip_address=ip_address,
    )
    db.commit()
    db.refresh(restaurant)
    return get_admin_restaurant_detail(db, restaurant_id)


def reactivate_admin_restaurant(
    db: Session, admin: User, restaurant_id: UUID, reason: str, ip_address: str | None = None
) -> AdminRestaurantDetail:
    restaurant = _get_restaurant_or_404(db, restaurant_id)
    if restaurant.is_active:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="This restaurant is already active.")
    restaurant.is_active = True
    record_admin_audit_log(
        db, admin_id=admin.id, action="restaurant.reactivate", target_type="restaurant", target_id=str(restaurant.id),
        reason=reason, previous_state="False", new_state="True", ip_address=ip_address,
    )
    db.commit()
    db.refresh(restaurant)
    return get_admin_restaurant_detail(db, restaurant_id)


# Phase 6 — restaurant approval state machine. Each admin action is only
# valid from specific current states; anything else is a 409, the same
# choke-point pattern Phase 24 established for delivery assignment status
# (ASSIGNMENT_VALID_TRANSITIONS / _transition_assignment_status).
_APPROVAL_ACTION_TRANSITIONS: dict[str, dict[ApprovalStatus, ApprovalStatus]] = {
    # A restaurant under initial review, or one previously rejected that
    # the admin has reconsidered, can be approved. An already-APPROVED or
    # currently-SUSPENDED restaurant must go through "activate" instead —
    # "approve" is deliberately not a generic "make it APPROVED" escape hatch.
    "approve": {
        ApprovalStatus.PENDING: ApprovalStatus.APPROVED,
        ApprovalStatus.REJECTED: ApprovalStatus.APPROVED,
    },
    # Only meaningful during initial onboarding review — an already-live
    # (APPROVED) or already-SUSPENDED restaurant is taken down with
    # "suspend", not retroactively "rejected".
    "reject": {ApprovalStatus.PENDING: ApprovalStatus.REJECTED},
    # Only a currently-live restaurant can be taken down.
    "suspend": {ApprovalStatus.APPROVED: ApprovalStatus.SUSPENDED},
    # Only reinstates a suspension — not a substitute for "approve" from
    # PENDING/REJECTED, which have their own distinct real-world meaning.
    "activate": {ApprovalStatus.SUSPENDED: ApprovalStatus.APPROVED},
}


def _transition_approval_status(restaurant: Restaurant, action: str) -> None:
    next_status = _APPROVAL_ACTION_TRANSITIONS[action].get(restaurant.approval_status)
    if next_status is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Cannot {action} a restaurant with approval_status={restaurant.approval_status.value}",
        )
    restaurant.approval_status = next_status
    # rejection_reason only ever means something while REJECTED — any
    # transition away from it clears the old reason.
    if next_status != ApprovalStatus.REJECTED:
        restaurant.rejection_reason = None


def _audit_approval_transition(
    db: Session, admin: User, restaurant: Restaurant, action: str, previous_status: ApprovalStatus,
    reason: str, ip_address: str | None,
) -> None:
    """Admin Intervention Validation (Phase 21) — approve/reject/suspend/
    activate previously mutated Restaurant.approval_status with no admin_id,
    no required reason, and no audit log entry at all, unlike every other
    administrative intervention in this codebase (order cancel, COD
    settle, rider assignment, the account-level deactivate/reactivate
    right above). This is the same record_admin_audit_log call those
    already make, applied here too."""
    record_admin_audit_log(
        db, admin_id=admin.id, action=f"restaurant.{action}", target_type="restaurant",
        target_id=str(restaurant.id), reason=reason,
        previous_state=previous_status.value, new_state=restaurant.approval_status.value,
        ip_address=ip_address,
    )


def approve_admin_restaurant(
    db: Session, admin: User, restaurant_id: UUID, reason: str, ip_address: str | None = None
) -> AdminRestaurantDetail:
    restaurant = _get_restaurant_or_404(db, restaurant_id)
    previous_status = restaurant.approval_status
    _transition_approval_status(restaurant, "approve")
    _audit_approval_transition(db, admin, restaurant, "approve", previous_status, reason, ip_address)
    db.commit()
    db.refresh(restaurant)
    return get_admin_restaurant_detail(db, restaurant_id)


def reject_admin_restaurant(
    db: Session, admin: User, restaurant_id: UUID, rejection_reason: str, ip_address: str | None = None
) -> AdminRestaurantDetail:
    restaurant = _get_restaurant_or_404(db, restaurant_id)
    previous_status = restaurant.approval_status
    _transition_approval_status(restaurant, "reject")
    restaurant.rejection_reason = rejection_reason
    _audit_approval_transition(db, admin, restaurant, "reject", previous_status, rejection_reason, ip_address)
    db.commit()
    db.refresh(restaurant)
    return get_admin_restaurant_detail(db, restaurant_id)


def suspend_admin_restaurant(
    db: Session, admin: User, restaurant_id: UUID, reason: str, ip_address: str | None = None
) -> AdminRestaurantDetail:
    restaurant = _get_restaurant_or_404(db, restaurant_id)
    previous_status = restaurant.approval_status
    _transition_approval_status(restaurant, "suspend")
    _audit_approval_transition(db, admin, restaurant, "suspend", previous_status, reason, ip_address)
    db.commit()
    db.refresh(restaurant)
    return get_admin_restaurant_detail(db, restaurant_id)


def reinstate_admin_restaurant(
    db: Session, admin: User, restaurant_id: UUID, reason: str, ip_address: str | None = None
) -> AdminRestaurantDetail:
    """The '/activate' action from the phase brief — reinstates a
    SUSPENDED restaurant back to APPROVED. Named reinstate internally to
    keep it unambiguous next to Restaurant.is_active's own ACTIVE/INACTIVE
    vocabulary (a completely separate concept — see AdminRestaurantStatus)."""
    restaurant = _get_restaurant_or_404(db, restaurant_id)
    previous_status = restaurant.approval_status
    _transition_approval_status(restaurant, "activate")
    _audit_approval_transition(db, admin, restaurant, "activate", previous_status, reason, ip_address)
    db.commit()
    db.refresh(restaurant)
    return get_admin_restaurant_detail(db, restaurant_id)
