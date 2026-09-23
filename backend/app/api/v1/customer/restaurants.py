from uuid import UUID

from fastapi import APIRouter, Query

from app.api.v1.deps import DbSession
from app.schemas.restaurant import CustomerRestaurantRead
from app.services import restaurants as restaurant_service

router = APIRouter()


@router.get("/restaurants", response_model=list[CustomerRestaurantRead])
def list_customer_restaurants(
    db: DbSession,
    category_id: UUID | None = Query(default=None),
    q: str | None = Query(default=None, alias="q"),
    open_only: bool = Query(default=False),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=20, ge=1, le=100),
) -> list[CustomerRestaurantRead]:
    return restaurant_service.list_active_restaurants(
        db, open_only=open_only, offset=offset, limit=limit, search=q, category_id=category_id
    )


@router.get("/restaurants/{restaurant_id}", response_model=CustomerRestaurantRead)
def get_customer_restaurant(restaurant_id: UUID, db: DbSession) -> CustomerRestaurantRead:
    return restaurant_service.get_active_restaurant_or_404(db, restaurant_id)
