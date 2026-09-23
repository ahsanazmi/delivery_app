from uuid import UUID

from fastapi import APIRouter

from app.api.v1.deps import DbSession
from app.schemas.category import CategoryRead
from app.services import categories as category_service

router = APIRouter()


@router.get("/categories", response_model=list[CategoryRead])
def list_customer_categories(db: DbSession) -> list[CategoryRead]:
    return category_service.list_active_categories(db)


@router.get("/categories/{category_id}", response_model=CategoryRead)
def get_customer_category(category_id: UUID, db: DbSession) -> CategoryRead:
    return category_service.get_active_category_or_404(db, category_id)
