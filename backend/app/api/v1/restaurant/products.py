from uuid import UUID

from fastapi import APIRouter, Depends, Query, status

from app.api.v1.deps import DbSession, require_roles
from app.models.user import User, UserRole
from app.schemas.product import OwnerProductRead, ProductCreate, ProductUpdate
from app.services.restaurant_dashboard import resolve_owner_restaurant
from app.services.products import (
    create_product,
    delete_product,
    get_owner_product_or_404,
    list_products_for_owner,
    update_product,
)

router = APIRouter()


@router.get("/products", response_model=list[OwnerProductRead])
def list_owner_products(
    db: DbSession,
    current_user: User = Depends(require_roles(UserRole.RESTAURANT_OWNER)),
    restaurant_id: UUID | None = Query(default=None),
) -> list[OwnerProductRead]:
    restaurant = resolve_owner_restaurant(db, current_user, restaurant_id)
    return list_products_for_owner(db, restaurant.id)


@router.post("/products", response_model=OwnerProductRead, status_code=status.HTTP_201_CREATED)
def create_owner_product(
    payload: ProductCreate,
    db: DbSession,
    current_user: User = Depends(require_roles(UserRole.RESTAURANT_OWNER)),
    restaurant_id: UUID | None = Query(default=None),
) -> OwnerProductRead:
    restaurant = resolve_owner_restaurant(db, current_user, restaurant_id)
    return create_product(db, restaurant.id, payload)


@router.get("/products/{product_id}", response_model=OwnerProductRead)
def get_owner_product(
    product_id: UUID,
    db: DbSession,
    current_user: User = Depends(require_roles(UserRole.RESTAURANT_OWNER)),
    restaurant_id: UUID | None = Query(default=None),
) -> OwnerProductRead:
    restaurant = resolve_owner_restaurant(db, current_user, restaurant_id)
    return get_owner_product_or_404(db, restaurant.id, product_id)


@router.patch("/products/{product_id}", response_model=OwnerProductRead)
def patch_owner_product(
    product_id: UUID,
    payload: ProductUpdate,
    db: DbSession,
    current_user: User = Depends(require_roles(UserRole.RESTAURANT_OWNER)),
    restaurant_id: UUID | None = Query(default=None),
) -> OwnerProductRead:
    restaurant = resolve_owner_restaurant(db, current_user, restaurant_id)
    product = get_owner_product_or_404(db, restaurant.id, product_id)
    return update_product(db, restaurant.id, product, payload)


@router.delete("/products/{product_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_owner_product(
    product_id: UUID,
    db: DbSession,
    current_user: User = Depends(require_roles(UserRole.RESTAURANT_OWNER)),
    restaurant_id: UUID | None = Query(default=None),
) -> None:
    restaurant = resolve_owner_restaurant(db, current_user, restaurant_id)
    product = get_owner_product_or_404(db, restaurant.id, product_id)
    delete_product(db, product)
