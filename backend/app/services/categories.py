from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.category import Category


def list_active_categories(db: Session) -> list[Category]:
    statement = (
        select(Category)
        .where(Category.is_active.is_(True))
        .order_by(Category.display_order.asc(), Category.name.asc())
    )
    return list(db.scalars(statement))


def search_categories(db: Session, *, q: str | None = None, offset: int = 0, limit: int = 20) -> list[Category]:
    statement = select(Category).where(Category.is_active.is_(True))
    if q:
        query = f"%{q.strip().lower()}%"
        statement = statement.where(func.lower(Category.name).like(query))
    statement = statement.order_by(Category.display_order.asc(), Category.name.asc()).offset(offset).limit(limit)
    return list(db.scalars(statement))


def get_active_category_or_404(db: Session, category_id: UUID) -> Category:
    category = db.scalar(select(Category).where(Category.id == category_id, Category.is_active.is_(True)))
    if not category:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Category not found")
    return category
