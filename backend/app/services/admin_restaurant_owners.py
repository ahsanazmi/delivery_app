from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.restaurant import Restaurant
from app.models.user import User, UserRole
from app.schemas.admin import (
    AdminOwnedRestaurant,
    AdminRestaurantOwnerListResponse,
    AdminRestaurantOwnerStatus,
    AdminRestaurantOwnerSummary,
)
from app.services.admin_account_status import set_user_active_status


def _status_to_is_active(value: AdminRestaurantOwnerStatus) -> bool:
    return value == "ACTIVE"


def _is_active_to_status(is_active: bool) -> AdminRestaurantOwnerStatus:
    return "ACTIVE" if is_active else "SUSPENDED"


def _restaurants_by_owner(db: Session, owner_ids: list[UUID]) -> dict[UUID, list[Restaurant]]:
    """Batch-fetch every restaurant belonging to any of these owners in one
    query, grouped in Python — avoids an N+1 of one query per row on the
    owner list page, same discipline as admin_customers.py/admin_restaurants.py."""
    if not owner_ids:
        return {}
    restaurants = db.scalars(
        select(Restaurant).where(Restaurant.owner_id.in_(owner_ids)).order_by(Restaurant.created_at.asc())
    ).all()
    grouped: dict[UUID, list[Restaurant]] = {}
    for restaurant in restaurants:
        grouped.setdefault(restaurant.owner_id, []).append(restaurant)
    return grouped


def _to_summary(owner: User, restaurants: list[Restaurant]) -> AdminRestaurantOwnerSummary:
    return AdminRestaurantOwnerSummary(
        id=owner.id,
        name=owner.name,
        email=owner.email,
        phone=owner.phone,
        status=_is_active_to_status(owner.is_active),
        created_at=owner.created_at,
        restaurants=[
            AdminOwnedRestaurant(id=r.id, name=r.name, is_active=r.is_active, approval_status=r.approval_status)
            for r in restaurants
        ],
    )


def list_admin_restaurant_owners(
    db: Session,
    *,
    search: str | None,
    status_filter: AdminRestaurantOwnerStatus | None,
    has_restaurant: bool | None,
    page: int,
    limit: int,
) -> AdminRestaurantOwnerListResponse:
    conditions = [User.role == UserRole.RESTAURANT_OWNER]
    if search:
        pattern = f"%{search.strip()}%"
        conditions.append((User.name.ilike(pattern)) | (User.email.ilike(pattern)) | (User.phone.ilike(pattern)))
    if status_filter is not None:
        conditions.append(User.is_active.is_(_status_to_is_active(status_filter)))
    if has_restaurant is not None:
        owned_owner_ids = select(Restaurant.owner_id).distinct()
        conditions.append(User.id.in_(owned_owner_ids) if has_restaurant else User.id.notin_(owned_owner_ids))

    total = db.scalar(select(func.count()).select_from(User).where(*conditions)) or 0

    offset = (page - 1) * limit
    owners = db.scalars(
        select(User).where(*conditions).order_by(User.created_at.desc()).offset(offset).limit(limit)
    ).all()

    restaurants_by_owner = _restaurants_by_owner(db, [owner.id for owner in owners])
    items = [_to_summary(owner, restaurants_by_owner.get(owner.id, [])) for owner in owners]
    return AdminRestaurantOwnerListResponse(items=items, total=total, page=page, limit=limit)


def _get_owner_or_404(db: Session, owner_id: UUID) -> User:
    owner = db.get(User, owner_id)
    if not owner or owner.role != UserRole.RESTAURANT_OWNER:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Restaurant owner not found")
    return owner


def get_admin_restaurant_owner_detail(db: Session, owner_id: UUID) -> AdminRestaurantOwnerSummary:
    owner = _get_owner_or_404(db, owner_id)
    restaurants = _restaurants_by_owner(db, [owner.id]).get(owner.id, [])
    return _to_summary(owner, restaurants)


def suspend_admin_restaurant_owner(
    db: Session, admin: User, owner_id: UUID, reason: str, ip_address: str | None = None
) -> AdminRestaurantOwnerSummary:
    owner = _get_owner_or_404(db, owner_id)
    set_user_active_status(
        db, admin, owner, target_active=False, action="restaurant_owner.suspend", target_type="restaurant_owner",
        reason=reason, ip_address=ip_address,
    )
    db.commit()
    db.refresh(owner)
    return get_admin_restaurant_owner_detail(db, owner_id)


def activate_admin_restaurant_owner(
    db: Session, admin: User, owner_id: UUID, reason: str, ip_address: str | None = None
) -> AdminRestaurantOwnerSummary:
    owner = _get_owner_or_404(db, owner_id)
    set_user_active_status(
        db, admin, owner, target_active=True, action="restaurant_owner.activate", target_type="restaurant_owner",
        reason=reason, ip_address=ip_address,
    )
    db.commit()
    db.refresh(owner)
    return get_admin_restaurant_owner_detail(db, owner_id)
