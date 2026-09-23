from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.category import Category
from app.models.restaurant import Restaurant
from app.schemas.admin import AdminCategoryCreate, AdminCategoryListResponse, AdminCategoryRead, AdminCategoryUpdate


def _restaurant_counts(db: Session, category_ids: list[UUID]) -> dict[UUID, int]:
    if not category_ids:
        return {}
    rows = db.execute(
        select(Restaurant.category_id, func.count(Restaurant.id))
        .where(Restaurant.category_id.in_(category_ids))
        .group_by(Restaurant.category_id)
    ).all()
    return dict(rows)


def _to_read(category: Category, restaurant_count: int) -> AdminCategoryRead:
    return AdminCategoryRead(
        id=category.id,
        name=category.name,
        image_url=category.image_url,
        display_order=category.display_order,
        is_active=category.is_active,
        restaurant_count=restaurant_count,
        created_at=category.created_at,
        updated_at=category.updated_at,
    )


def list_admin_categories(
    db: Session, *, search: str | None, is_active: bool | None, page: int, limit: int
) -> AdminCategoryListResponse:
    conditions = []
    if search:
        conditions.append(Category.name.ilike(f"%{search.strip()}%"))
    if is_active is not None:
        conditions.append(Category.is_active.is_(is_active))

    total = db.scalar(select(func.count()).select_from(Category).where(*conditions)) or 0

    offset = (page - 1) * limit
    categories = db.scalars(
        select(Category).where(*conditions).order_by(Category.display_order.asc(), Category.name.asc()).offset(offset).limit(limit)
    ).all()

    counts = _restaurant_counts(db, [category.id for category in categories])
    items = [_to_read(category, counts.get(category.id, 0)) for category in categories]
    return AdminCategoryListResponse(items=items, total=total, page=page, limit=limit)


def _get_category_or_404(db: Session, category_id: UUID) -> Category:
    category = db.get(Category, category_id)
    if not category:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Category not found")
    return category


def create_admin_category(db: Session, payload: AdminCategoryCreate) -> AdminCategoryRead:
    category = Category(name=payload.name.strip(), image_url=payload.image_url, display_order=payload.display_order)
    db.add(category)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=f"A category named '{payload.name}' already exists"
        ) from exc
    db.refresh(category)
    return _to_read(category, 0)


def update_admin_category(db: Session, category_id: UUID, payload: AdminCategoryUpdate) -> AdminCategoryRead:
    category = _get_category_or_404(db, category_id)
    if payload.name is not None:
        category.name = payload.name.strip()
    if payload.image_url is not None:
        category.image_url = payload.image_url
    if payload.display_order is not None:
        category.display_order = payload.display_order
    if payload.is_active is not None:
        category.is_active = payload.is_active

    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=f"A category named '{payload.name}' already exists"
        ) from exc
    db.refresh(category)
    restaurant_count = _restaurant_counts(db, [category.id]).get(category.id, 0)
    return _to_read(category, restaurant_count)


def delete_admin_category(db: Session, category_id: UUID) -> None:
    """A real delete, not a soft one — matching this project's established
    convention (see products.py's own comment on the same distinction):
    PATCH is_active=False is how a category is actually retired without
    losing history; DELETE is for a category that should never have
    existed. Blocked while any restaurant still references it — the FK
    itself would just SET NULL and silently orphan those restaurants'
    category, which is exactly the kind of silent data change this
    project's admin actions avoid."""
    category = _get_category_or_404(db, category_id)
    restaurant_count = _restaurant_counts(db, [category.id]).get(category.id, 0)
    if restaurant_count > 0:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Cannot delete — {restaurant_count} restaurant(s) still use this category. Reassign or deactivate it instead.",
        )
    db.delete(category)
    db.commit()
