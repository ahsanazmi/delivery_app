from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import Select, func, or_, select
from sqlalchemy.orm import Session

from app.models.restaurant import Restaurant
from app.models.user import User, UserRole
from app.schemas.restaurant import RestaurantCreate, RestaurantUpdate


def _not_found() -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Restaurant not found")


def get_active_restaurant_or_404(db: Session, restaurant_id: UUID) -> Restaurant:
    restaurant = db.scalar(select(Restaurant).where(Restaurant.id == restaurant_id, Restaurant.is_active.is_(True)))
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


def _resolve_owner_id(db: Session, payload: RestaurantCreate, actor: User) -> UUID:
    if actor.role == UserRole.RESTAURANT:
        if payload.owner_id and payload.owner_id != actor.id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Restaurant owners can only create their own restaurant")
        return actor.id
    if not payload.owner_id:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="owner_id is required when an admin creates a restaurant")
    owner = db.get(User, payload.owner_id)
    if not owner or not owner.is_active or owner.role != UserRole.RESTAURANT:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="owner_id must belong to an active restaurant owner")
    return owner.id


def create_restaurant(db: Session, payload: RestaurantCreate, actor: User) -> Restaurant:
    restaurant = Restaurant(
        **payload.model_dump(exclude={"owner_id"}),
        owner_id=_resolve_owner_id(db, payload, actor),
    )
    db.add(restaurant)
    db.commit()
    db.refresh(restaurant)
    return restaurant


def update_restaurant(db: Session, restaurant: Restaurant, payload: RestaurantUpdate) -> Restaurant:
    for field, value in payload.model_dump(exclude_unset=True).items():
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


def list_active_restaurants(db: Session, *, open_only: bool, offset: int, limit: int, search: str | None = None) -> list[Restaurant]:
    statement: Select[tuple[Restaurant]] = select(Restaurant).where(Restaurant.is_active.is_(True))
    if open_only:
        statement = statement.where(Restaurant.is_open.is_(True))
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
