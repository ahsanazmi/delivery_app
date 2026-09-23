from uuid import UUID

from fastapi import APIRouter, Depends, Query

from app.api.v1.deps import DbSession, require_roles
from app.models.user import User, UserRole
from app.schemas.restaurant_hours import OperatingHourRead, OperatingHoursUpdate, RestaurantHoursResponse
from app.services.restaurant_dashboard import resolve_owner_restaurant
from app.services.restaurant_hours import get_hours_for_restaurant, replace_hours

router = APIRouter()


@router.get("/hours", response_model=RestaurantHoursResponse)
def get_hours(
    db: DbSession,
    current_user: User = Depends(require_roles(UserRole.RESTAURANT_OWNER)),
    restaurant_id: UUID | None = Query(default=None),
) -> RestaurantHoursResponse:
    restaurant = resolve_owner_restaurant(db, current_user, restaurant_id)
    hours = get_hours_for_restaurant(db, restaurant.id)
    return RestaurantHoursResponse(
        restaurant_id=restaurant.id,
        hours=[OperatingHourRead.model_validate(h) for h in hours],
    )


@router.put("/hours", response_model=RestaurantHoursResponse)
def put_hours(
    payload: OperatingHoursUpdate,
    db: DbSession,
    current_user: User = Depends(require_roles(UserRole.RESTAURANT_OWNER)),
    restaurant_id: UUID | None = Query(default=None),
) -> RestaurantHoursResponse:
    restaurant = resolve_owner_restaurant(db, current_user, restaurant_id)
    hours = replace_hours(db, restaurant.id, payload.hours)
    return RestaurantHoursResponse(
        restaurant_id=restaurant.id,
        hours=[OperatingHourRead.model_validate(h) for h in hours],
    )
