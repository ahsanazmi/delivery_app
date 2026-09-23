from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import Select, func, or_, select
from sqlalchemy.orm import Session

from app.models.delivery_partner import ApprovalStatus
from app.models.notification import NotificationType
from app.models.restaurant import Restaurant
from app.models.user import User, UserRole
from app.schemas.restaurant import RestaurantCreate, RestaurantProfileUpdate, RestaurantUpdate
from app.services.admin_settings import get_platform_settings
from app.services.notifications import notify_admins


def _not_found() -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Restaurant not found")


def get_active_restaurant_or_404(db: Session, restaurant_id: UUID) -> Restaurant:
    restaurant = db.scalar(
        select(Restaurant).where(
            Restaurant.id == restaurant_id,
            Restaurant.is_active.is_(True),
            Restaurant.approval_status == ApprovalStatus.APPROVED,
        )
    )
    if not restaurant:
        raise _not_found()
    return restaurant


def get_restaurant_or_404(db: Session, restaurant_id: UUID) -> Restaurant:
    restaurant = db.get(Restaurant, restaurant_id)
    if not restaurant:
        raise _not_found()
    return restaurant


def assert_restaurant_manager(restaurant: Restaurant, actor: User) -> None:
    if actor.role == UserRole.ADMIN or restaurant.owner_id == actor.id:
        return
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="You do not manage this restaurant")


def list_restaurants_for_owner(db: Session, owner_id: UUID) -> list[Restaurant]:
    """All of this owner's restaurants, active or not — unlike the public
    listing, an owner needs to see (and manage) a restaurant they've
    temporarily deactivated too."""
    statement = select(Restaurant).where(Restaurant.owner_id == owner_id).order_by(Restaurant.created_at.desc())
    return list(db.scalars(statement))


def _resolve_owner_id(db: Session, payload: RestaurantCreate, actor: User) -> UUID:
    if actor.role == UserRole.RESTAURANT_OWNER:
        if payload.owner_id and payload.owner_id != actor.id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Restaurant owners can only create their own restaurant")
        return actor.id
    if not payload.owner_id:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="owner_id is required when an admin creates a restaurant")
    owner = db.get(User, payload.owner_id)
    if not owner or not owner.is_active or owner.role != UserRole.RESTAURANT_OWNER:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="owner_id must belong to an active restaurant owner")
    return owner.id


def create_restaurant(db: Session, payload: RestaurantCreate, actor: User) -> Restaurant:
    data = payload.model_dump(exclude={"owner_id"})
    if data["minimum_order"] is None or data["delivery_fee"] is None:
        platform_settings = get_platform_settings(db)
        if data["minimum_order"] is None:
            data["minimum_order"] = platform_settings.default_minimum_order
        if data["delivery_fee"] is None:
            data["delivery_fee"] = platform_settings.default_delivery_fee
    restaurant = Restaurant(**data, owner_id=_resolve_owner_id(db, payload, actor))
    db.add(restaurant)
    db.flush()
    # Admin Portal Phase 20 — added before the commit below so the alert
    # persists atomically with the restaurant itself, never as a separate step.
    notify_admins(
        db, NotificationType.NEW_RESTAURANT_REGISTERED, "New restaurant registered",
        f"{restaurant.name} has registered on the platform.",
    )
    db.commit()
    db.refresh(restaurant)
    return restaurant


def update_restaurant(db: Session, restaurant: Restaurant, payload: RestaurantUpdate) -> Restaurant:
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(restaurant, field, value)
    db.commit()
    db.refresh(restaurant)
    return restaurant


def update_restaurant_profile(db: Session, restaurant: Restaurant, payload: RestaurantProfileUpdate) -> Restaurant:
    """Like update_restaurant, but also handles the two image URL fields —
    Pydantic's HttpUrl comes back from model_dump() as a Url object, not a
    plain string, so it needs an explicit str() before it can be stored in a
    String column."""
    updates = payload.model_dump(exclude_unset=True)
    for field in ("logo_url", "cover_image_url"):
        if updates.get(field) is not None:
            updates[field] = str(updates[field])
    for field, value in updates.items():
        setattr(restaurant, field, value)
    db.commit()
    db.refresh(restaurant)
    return restaurant


def deactivate_restaurant(db: Session, restaurant: Restaurant) -> Restaurant:
    restaurant.is_active = False
    restaurant.is_open = False
    db.commit()
    db.refresh(restaurant)
    return restaurant


def list_active_restaurants(
    db: Session,
    *,
    open_only: bool,
    offset: int,
    limit: int,
    search: str | None = None,
    category_id: UUID | None = None,
) -> list[Restaurant]:
    statement: Select[tuple[Restaurant]] = select(Restaurant).where(
        Restaurant.is_active.is_(True), Restaurant.approval_status == ApprovalStatus.APPROVED
    )
    if open_only:
        statement = statement.where(Restaurant.is_open.is_(True))
    if category_id is not None:
        statement = statement.where(Restaurant.category_id == category_id)
    if search:
        query = f"%{search.strip().lower()}%"
        statement = statement.where(
            or_(
                func.lower(Restaurant.name).like(query),
                func.lower(Restaurant.description).like(query),
                func.lower(Restaurant.address).like(query),
            )
        )
    statement = statement.order_by(Restaurant.average_rating.desc(), Restaurant.name.asc()).offset(offset).limit(limit)
    return list(db.scalars(statement))


def search_restaurants(db: Session, query: str, *, offset: int = 0, limit: int = 20) -> list[Restaurant]:
    return list_active_restaurants(db, open_only=True, offset=offset, limit=limit, search=query)
