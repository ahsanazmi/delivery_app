from decimal import Decimal
from uuid import UUID

from sqlalchemy.orm import Session

from app.services import categories as category_service
from app.services import products as product_service
from app.services import restaurants as restaurant_service
from app.services.delivery_radius import restaurants_delivering_to


def run_customer_search(
    db: Session,
    *,
    q: str | None,
    category_id: UUID | None,
    restaurant_id: UUID | None,
    page: int,
    limit: int,
    latitude: Decimal | None = None,
    longitude: Decimal | None = None,
) -> dict:
    offset = (page - 1) * limit
    # With a location, both restaurants and dishes are limited to
    # restaurants that actually deliver there.
    nearby = restaurants_delivering_to(db, latitude, longitude) if latitude is not None and longitude is not None else None

    restaurants = restaurant_service.list_active_restaurants(
        db, open_only=False, offset=offset, limit=limit, search=q, category_id=category_id, nearby=nearby
    )
    products = product_service.search_products(
        db, q=q, restaurant_id=restaurant_id, category_id=category_id,
        restaurant_ids=set(nearby) if nearby is not None else None, offset=offset, limit=limit,
    )
    categories = category_service.search_categories(db, q=q, offset=offset, limit=limit)

    return {
        "restaurants": restaurants,
        "products": products,
        "categories": categories,
        "page": page,
        "limit": limit,
    }
