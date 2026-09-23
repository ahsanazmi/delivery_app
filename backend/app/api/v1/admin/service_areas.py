from uuid import UUID

from fastapi import APIRouter, Depends, Query, status

from app.api.v1.deps import DbSession, require_admin
from app.models.user import User
from app.schemas.admin import (
    AdminServiceAreaCreate,
    AdminServiceAreaListResponse,
    AdminServiceAreaRead,
    AdminServiceAreaUpdate,
)
from app.services.admin_service_areas import (
    create_admin_service_area,
    delete_admin_service_area,
    list_admin_service_areas,
    update_admin_service_area,
)

router = APIRouter()


@router.get("/service-areas", response_model=AdminServiceAreaListResponse)
def list_service_areas(
    db: DbSession,
    search: str | None = Query(default=None),
    is_active: bool | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=50, ge=1, le=200),
    current_admin: User = Depends(require_admin),
) -> AdminServiceAreaListResponse:
    return list_admin_service_areas(db, search=search, is_active=is_active, page=page, limit=limit)


@router.post("/service-areas", response_model=AdminServiceAreaRead, status_code=status.HTTP_201_CREATED)
def create_service_area(
    payload: AdminServiceAreaCreate, db: DbSession, current_admin: User = Depends(require_admin)
) -> AdminServiceAreaRead:
    return create_admin_service_area(db, payload)


@router.patch("/service-areas/{service_area_id}", response_model=AdminServiceAreaRead)
def update_service_area(
    service_area_id: UUID,
    payload: AdminServiceAreaUpdate,
    db: DbSession,
    current_admin: User = Depends(require_admin),
) -> AdminServiceAreaRead:
    return update_admin_service_area(db, service_area_id, payload)


@router.delete("/service-areas/{service_area_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_service_area(service_area_id: UUID, db: DbSession, current_admin: User = Depends(require_admin)) -> None:
    delete_admin_service_area(db, service_area_id)
