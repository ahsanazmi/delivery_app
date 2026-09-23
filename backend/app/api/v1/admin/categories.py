from uuid import UUID

from fastapi import APIRouter, Depends, Query, status

from app.api.v1.deps import DbSession, require_admin
from app.models.user import User
from app.schemas.admin import AdminCategoryCreate, AdminCategoryListResponse, AdminCategoryRead, AdminCategoryUpdate
from app.services.admin_categories import (
    create_admin_category,
    delete_admin_category,
    list_admin_categories,
    update_admin_category,
)

router = APIRouter()


@router.get("/categories", response_model=AdminCategoryListResponse)
def list_categories(
    db: DbSession,
    search: str | None = Query(default=None),
    is_active: bool | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=50, ge=1, le=200),
    current_admin: User = Depends(require_admin),
) -> AdminCategoryListResponse:
    return list_admin_categories(db, search=search, is_active=is_active, page=page, limit=limit)


@router.post("/categories", response_model=AdminCategoryRead, status_code=status.HTTP_201_CREATED)
def create_category(
    payload: AdminCategoryCreate, db: DbSession, current_admin: User = Depends(require_admin)
) -> AdminCategoryRead:
    return create_admin_category(db, payload)


@router.patch("/categories/{category_id}", response_model=AdminCategoryRead)
def update_category(
    category_id: UUID, payload: AdminCategoryUpdate, db: DbSession, current_admin: User = Depends(require_admin)
) -> AdminCategoryRead:
    return update_admin_category(db, category_id, payload)


@router.delete("/categories/{category_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_category(category_id: UUID, db: DbSession, current_admin: User = Depends(require_admin)) -> None:
    delete_admin_category(db, category_id)
