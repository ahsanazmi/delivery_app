from fastapi import APIRouter, Depends

from app.api.v1.deps import DbSession, require_roles
from app.models.user import User, UserRole
from app.schemas.restaurant import RestaurantOwnerMe
from app.services.restaurants import list_restaurants_for_owner

router = APIRouter()


@router.get("/me", response_model=RestaurantOwnerMe)
def get_my_restaurant_profile(
    db: DbSession, current_user: User = Depends(require_roles(UserRole.RESTAURANT_OWNER))
) -> RestaurantOwnerMe:
    return RestaurantOwnerMe(user=current_user, restaurants=list_restaurants_for_owner(db, current_user.id))
