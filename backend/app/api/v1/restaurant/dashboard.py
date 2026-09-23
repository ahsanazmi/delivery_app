from uuid import UUID

from fastapi import APIRouter, Depends, Query

from app.api.v1.deps import DbSession, require_roles
from app.models.user import User, UserRole
from app.schemas.restaurant_dashboard import RestaurantDashboardResponse
from app.services.restaurant_dashboard import get_restaurant_dashboard, resolve_owner_restaurant

router = APIRouter()


@router.get("/dashboard", response_model=RestaurantDashboardResponse)
def get_dashboard(
    db: DbSession,
    current_user: User = Depends(require_roles(UserRole.RESTAURANT_OWNER)),
    restaurant_id: UUID | None = Query(default=None),
) -> RestaurantDashboardResponse:
    restaurant = resolve_owner_restaurant(db, current_user, restaurant_id)
    return RestaurantDashboardResponse(**get_restaurant_dashboard(db, restaurant))
