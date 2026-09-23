from uuid import UUID

from fastapi import APIRouter, Depends, Query

from app.api.v1.deps import DbSession, require_roles
from app.models.user import User, UserRole
from app.schemas.restaurant import RestaurantProfileUpdate, RestaurantRead
from app.services.restaurant_dashboard import resolve_owner_restaurant
from app.services.restaurants import update_restaurant_profile

router = APIRouter()


@router.get("/profile", response_model=RestaurantRead)
def get_profile(
    db: DbSession,
    current_user: User = Depends(require_roles(UserRole.RESTAURANT_OWNER)),
    restaurant_id: UUID | None = Query(default=None),
) -> RestaurantRead:
    return resolve_owner_restaurant(db, current_user, restaurant_id)


@router.patch("/profile", response_model=RestaurantRead)
def update_profile(
    payload: RestaurantProfileUpdate,
    db: DbSession,
    current_user: User = Depends(require_roles(UserRole.RESTAURANT_OWNER)),
    restaurant_id: UUID | None = Query(default=None),
) -> RestaurantRead:
    restaurant = resolve_owner_restaurant(db, current_user, restaurant_id)
    return update_restaurant_profile(db, restaurant, payload)
