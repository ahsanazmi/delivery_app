from uuid import UUID

from fastapi import APIRouter, Depends, Query, status

from app.api.v1.deps import CurrentUser, DbSession, require_roles
from app.models.user import User, UserRole
from app.schemas.restaurant import (
    RestaurantCreate,
    RestaurantImagesUpdate,
    RestaurantOpenStatusUpdate,
    RestaurantRead,
    RestaurantUpdate,
)
from app.services import restaurants as restaurant_service

router = APIRouter()


@router.get("", response_model=list[RestaurantRead])
def list_restaurants(
    db: DbSession,
    open_only: bool = True,
    q: str | None = Query(default=None, alias="q"),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=20, ge=1, le=100),
) -> list[RestaurantRead]:
    return restaurant_service.list_active_restaurants(db, open_only=open_only, offset=offset, limit=limit, search=q)


@router.post("", response_model=RestaurantRead, status_code=status.HTTP_201_CREATED)
def create_restaurant(
    payload: RestaurantCreate,
    db: DbSession,
    current_user: User = Depends(require_roles(UserRole.RESTAURANT, UserRole.ADMIN)),
) -> RestaurantRead:
    return restaurant_service.create_restaurant(db, payload, current_user)


@router.get("/{restaurant_id}", response_model=RestaurantRead)
def get_restaurant(restaurant_id: UUID, db: DbSession) -> RestaurantRead:
    return restaurant_service.get_active_restaurant_or_404(db, restaurant_id)


@router.patch("/{restaurant_id}", response_model=RestaurantRead)
def update_restaurant(restaurant_id: UUID, payload: RestaurantUpdate, db: DbSession, current_user: CurrentUser) -> RestaurantRead:
    restaurant = restaurant_service.get_restaurant_or_404(db, restaurant_id)
    restaurant_service.assert_restaurant_manager(restaurant, current_user)
    return restaurant_service.update_restaurant(db, restaurant, payload)


@router.delete("/{restaurant_id}", response_model=RestaurantRead)
def deactivate_restaurant(restaurant_id: UUID, db: DbSession, current_user: CurrentUser) -> RestaurantRead:
    restaurant = restaurant_service.get_restaurant_or_404(db, restaurant_id)
    restaurant_service.assert_restaurant_manager(restaurant, current_user)
    return restaurant_service.deactivate_restaurant(db, restaurant)


@router.patch("/{restaurant_id}/images", response_model=RestaurantRead)
def update_restaurant_images(
    restaurant_id: UUID, payload: RestaurantImagesUpdate, db: DbSession, current_user: CurrentUser
) -> RestaurantRead:
    restaurant = restaurant_service.get_restaurant_or_404(db, restaurant_id)
    restaurant_service.assert_restaurant_manager(restaurant, current_user)
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(restaurant, field, str(value) if value is not None else None)
    return restaurant_service.update_restaurant(db, restaurant, RestaurantUpdate())


@router.patch("/{restaurant_id}/open-status", response_model=RestaurantRead)
def update_open_status(
    restaurant_id: UUID, payload: RestaurantOpenStatusUpdate, db: DbSession, current_user: CurrentUser
) -> RestaurantRead:
    restaurant = restaurant_service.get_restaurant_or_404(db, restaurant_id)
    restaurant_service.assert_restaurant_manager(restaurant, current_user)
    restaurant.is_open = payload.is_open
    return restaurant_service.update_restaurant(db, restaurant, RestaurantUpdate())
