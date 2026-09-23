from uuid import UUID

from fastapi import APIRouter, Depends, status

from app.api.v1.deps import DbSession, require_customer
from app.models.user import User
from app.schemas.restaurant import CustomerRestaurantRead
from app.services.favorites import add_favorite, list_favorite_restaurants, remove_favorite

router = APIRouter()


@router.get("/favorites", response_model=list[CustomerRestaurantRead])
def list_favorites(db: DbSession, current_user: User = Depends(require_customer)) -> list[CustomerRestaurantRead]:
    return list_favorite_restaurants(db, current_user.id)


@router.post("/favorites/{restaurant_id}", status_code=status.HTTP_204_NO_CONTENT)
def favorite_restaurant(restaurant_id: UUID, db: DbSession, current_user: User = Depends(require_customer)) -> None:
    add_favorite(db, current_user.id, restaurant_id)


@router.delete("/favorites/{restaurant_id}", status_code=status.HTTP_204_NO_CONTENT)
def unfavorite_restaurant(restaurant_id: UUID, db: DbSession, current_user: User = Depends(require_customer)) -> None:
    remove_favorite(db, current_user.id, restaurant_id)
