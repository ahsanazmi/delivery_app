from uuid import UUID

from fastapi import APIRouter, Depends, Query, status

from app.api.v1.deps import DbSession, require_roles
from app.models.user import User, UserRole
from app.schemas.product import MenuCategoryCreate, MenuCategoryUpdate, OwnerMenuCategoryRead
from app.services.restaurant_dashboard import resolve_owner_restaurant
from app.services.products import (
    create_menu_category,
    delete_menu_category,
    get_menu_category_or_404,
    list_menu_categories_for_owner,
    update_menu_category,
)

router = APIRouter()


@router.get("/categories", response_model=list[OwnerMenuCategoryRead])
def list_categories(
    db: DbSession,
    current_user: User = Depends(require_roles(UserRole.RESTAURANT_OWNER)),
    restaurant_id: UUID | None = Query(default=None),
) -> list[OwnerMenuCategoryRead]:
    restaurant = resolve_owner_restaurant(db, current_user, restaurant_id)
    return list_menu_categories_for_owner(db, restaurant.id)


@router.post("/categories", response_model=OwnerMenuCategoryRead, status_code=status.HTTP_201_CREATED)
def create_category(
    payload: MenuCategoryCreate,
    db: DbSession,
    current_user: User = Depends(require_roles(UserRole.RESTAURANT_OWNER)),
    restaurant_id: UUID | None = Query(default=None),
) -> OwnerMenuCategoryRead:
    restaurant = resolve_owner_restaurant(db, current_user, restaurant_id)
    return create_menu_category(db, restaurant.id, payload)


@router.get("/categories/{category_id}", response_model=OwnerMenuCategoryRead)
def get_category(
    category_id: UUID,
    db: DbSession,
    current_user: User = Depends(require_roles(UserRole.RESTAURANT_OWNER)),
    restaurant_id: UUID | None = Query(default=None),
) -> OwnerMenuCategoryRead:
    restaurant = resolve_owner_restaurant(db, current_user, restaurant_id)
    return get_menu_category_or_404(db, restaurant.id, category_id)


@router.patch("/categories/{category_id}", response_model=OwnerMenuCategoryRead)
def patch_category(
    category_id: UUID,
    payload: MenuCategoryUpdate,
    db: DbSession,
    current_user: User = Depends(require_roles(UserRole.RESTAURANT_OWNER)),
    restaurant_id: UUID | None = Query(default=None),
) -> OwnerMenuCategoryRead:
    restaurant = resolve_owner_restaurant(db, current_user, restaurant_id)
    category = get_menu_category_or_404(db, restaurant.id, category_id)
    return update_menu_category(db, category, payload)


@router.delete("/categories/{category_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_category(
    category_id: UUID,
    db: DbSession,
    current_user: User = Depends(require_roles(UserRole.RESTAURANT_OWNER)),
    restaurant_id: UUID | None = Query(default=None),
) -> None:
    restaurant = resolve_owner_restaurant(db, current_user, restaurant_id)
    category = get_menu_category_or_404(db, restaurant.id, category_id)
    delete_menu_category(db, category)
