from uuid import UUID

from fastapi import APIRouter, Depends, Query

from app.api.v1.deps import DbSession
from app.api.v1.customer.location_params import CustomerLocation, customer_location
from app.schemas.restaurant import CustomerRestaurantRead
from app.services import restaurants as restaurant_service
from app.services.delivery_radius import restaurants_delivering_to

router = APIRouter()


@router.get("/restaurants", response_model=list[CustomerRestaurantRead])
def list_customer_restaurants(
    db: DbSession,
    category_id: UUID | None = Query(default=None),
    q: str | None = Query(default=None, alias="q"),
    open_only: bool = Query(default=False),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=20, ge=1, le=100),
    location: CustomerLocation | None = Depends(customer_location),
) -> list[CustomerRestaurantRead]:
    # With the customer's location: only restaurants that deliver there,
    # nearest first. Without it: the full list (older app versions).
    nearby = restaurants_delivering_to(db, location.latitude, location.longitude) if location else None
    return restaurant_service.list_active_restaurants(
        db, open_only=open_only, offset=offset, limit=limit, search=q, category_id=category_id, nearby=nearby
    )


@router.get("/restaurants/{restaurant_id}", response_model=CustomerRestaurantRead)
def get_customer_restaurant(restaurant_id: UUID, db: DbSession) -> CustomerRestaurantRead:
    return restaurant_service.get_active_restaurant_or_404(db, restaurant_id)
