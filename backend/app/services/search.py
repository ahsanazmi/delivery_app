from uuid import UUID

from sqlalchemy.orm import Session

from app.services import categories as category_service
from app.services import products as product_service
from app.services import restaurants as restaurant_service


def run_customer_search(
    db: Session,
    *,
    q: str | None,
    category_id: UUID | None,
    restaurant_id: UUID | None,
    page: int,
    limit: int,
) -> dict:
    offset = (page - 1) * limit

    restaurants = restaurant_service.list_active_restaurants(
        db, open_only=False, offset=offset, limit=limit, search=q, category_id=category_id
    )
    products = product_service.search_products(
        db, q=q, restaurant_id=restaurant_id, category_id=category_id, offset=offset, limit=limit
    )
    categories = category_service.search_categories(db, q=q, offset=offset, limit=limit)

    return {
        "restaurants": restaurants,
        "products": products,
        "categories": categories,
        "page": page,
        "limit": limit,
    }
