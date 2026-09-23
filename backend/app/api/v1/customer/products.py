from uuid import UUID

from fastapi import APIRouter, Query

from app.api.v1.deps import DbSession
from app.schemas.product import MenuCategoryRead, ProductRead
from app.services import products as product_service
from app.services import restaurants as restaurant_service

router = APIRouter()


@router.get("/restaurants/{restaurant_id}/categories", response_model=list[MenuCategoryRead])
def list_restaurant_menu_categories(restaurant_id: UUID, db: DbSession) -> list[MenuCategoryRead]:
    restaurant_service.get_active_restaurant_or_404(db, restaurant_id)
    return product_service.list_menu_categories(db, restaurant_id)


@router.get("/restaurants/{restaurant_id}/products", response_model=list[ProductRead])
def list_restaurant_products(
    restaurant_id: UUID,
    db: DbSession,
    category_id: UUID | None = Query(default=None),
) -> list[ProductRead]:
    restaurant_service.get_active_restaurant_or_404(db, restaurant_id)
    return product_service.list_products(db, restaurant_id, category_id=category_id)


@router.get("/products/{product_id}", response_model=ProductRead)
def get_customer_product(product_id: UUID, db: DbSession) -> ProductRead:
    return product_service.get_customer_visible_product_or_404(db, product_id)
