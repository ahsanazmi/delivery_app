from uuid import UUID

from fastapi import APIRouter, Depends, Query

from app.api.v1.deps import DbSession, require_roles
from app.models.user import User, UserRole
from app.schemas.restaurant_hours import RestaurantStatusResponse, RestaurantStatusUpdate
from app.services.restaurant_dashboard import resolve_owner_restaurant
from app.services.restaurant_hours import compute_is_accepting_orders, get_hours_for_restaurant, get_today_hours

router = APIRouter()


def _build_status_response(db, restaurant) -> RestaurantStatusResponse:
    hours = get_hours_for_restaurant(db, restaurant.id)
    return RestaurantStatusResponse(
        restaurant_id=restaurant.id,
        is_open=restaurant.is_open,
        is_accepting_orders=compute_is_accepting_orders(restaurant, hours),
        hours_configured=len(hours) > 0,
        today=get_today_hours(hours),
    )


@router.get("/status", response_model=RestaurantStatusResponse)
def get_status(
    db: DbSession,
    current_user: User = Depends(require_roles(UserRole.RESTAURANT_OWNER)),
    restaurant_id: UUID | None = Query(default=None),
) -> RestaurantStatusResponse:
    restaurant = resolve_owner_restaurant(db, current_user, restaurant_id)
    return _build_status_response(db, restaurant)


@router.patch("/status", response_model=RestaurantStatusResponse)
def update_status(
    payload: RestaurantStatusUpdate,
    db: DbSession,
    current_user: User = Depends(require_roles(UserRole.RESTAURANT_OWNER)),
    restaurant_id: UUID | None = Query(default=None),
) -> RestaurantStatusResponse:
    restaurant = resolve_owner_restaurant(db, current_user, restaurant_id)
    restaurant.is_open = payload.is_open
    db.commit()
    db.refresh(restaurant)
    return _build_status_response(db, restaurant)
