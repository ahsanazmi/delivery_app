from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app.models.service_area import ServiceArea, ServiceAreaPostalCode
from app.schemas.admin import (
    AdminServiceAreaCreate,
    AdminServiceAreaListResponse,
    AdminServiceAreaRead,
    AdminServiceAreaUpdate,
)


def _normalize_postal_codes(postal_codes: list[str]) -> list[str]:
    # De-duplicated, trimmed, order-preserving — a client accidentally
    # pasting the same pincode twice shouldn't produce two child rows.
    seen: set[str] = set()
    normalized: list[str] = []
    for code in postal_codes:
        cleaned = code.strip()
        if cleaned and cleaned not in seen:
            seen.add(cleaned)
            normalized.append(cleaned)
    return normalized


def _to_read(service_area: ServiceArea) -> AdminServiceAreaRead:
    return AdminServiceAreaRead(
        id=service_area.id,
        city=service_area.city,
        district=service_area.district,
        zone_name=service_area.zone_name,
        postal_codes=[p.postal_code for p in service_area.postal_codes],
        is_active=service_area.is_active,
        created_at=service_area.created_at,
        updated_at=service_area.updated_at,
    )


def list_admin_service_areas(
    db: Session, *, search: str | None, is_active: bool | None, page: int, limit: int
) -> AdminServiceAreaListResponse:
    conditions = []
    if search:
        pattern = f"%{search.strip()}%"
        conditions.append(
            ServiceArea.city.ilike(pattern) | ServiceArea.zone_name.ilike(pattern) | ServiceArea.district.ilike(pattern)
        )
    if is_active is not None:
        conditions.append(ServiceArea.is_active.is_(is_active))

    total = db.scalar(select(func.count()).select_from(ServiceArea).where(*conditions)) or 0

    offset = (page - 1) * limit
    service_areas = db.scalars(
        select(ServiceArea)
        .options(selectinload(ServiceArea.postal_codes))
        .where(*conditions)
        .order_by(ServiceArea.city.asc(), ServiceArea.zone_name.asc())
        .offset(offset)
        .limit(limit)
    ).all()

    return AdminServiceAreaListResponse(items=[_to_read(sa) for sa in service_areas], total=total, page=page, limit=limit)


def _get_service_area_or_404(db: Session, service_area_id: UUID) -> ServiceArea:
    service_area = db.scalar(
        select(ServiceArea).options(selectinload(ServiceArea.postal_codes)).where(ServiceArea.id == service_area_id)
    )
    if not service_area:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Service area not found")
    return service_area


def _replace_postal_codes(db: Session, service_area: ServiceArea, postal_codes: list[str]) -> None:
    service_area.postal_codes.clear()
    db.flush()
    for code in _normalize_postal_codes(postal_codes):
        db.add(ServiceAreaPostalCode(service_area_id=service_area.id, postal_code=code))


def create_admin_service_area(db: Session, payload: AdminServiceAreaCreate) -> AdminServiceAreaRead:
    service_area = ServiceArea(
        city=payload.city.strip(), district=payload.district, zone_name=payload.zone_name.strip(),
        is_active=payload.is_active,
    )
    db.add(service_area)
    db.flush()
    for code in _normalize_postal_codes(payload.postal_codes):
        db.add(ServiceAreaPostalCode(service_area_id=service_area.id, postal_code=code))

    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="One or more postal codes are already assigned to another service area.",
        ) from exc
    return _to_read(_get_service_area_or_404(db, service_area.id))


def update_admin_service_area(db: Session, service_area_id: UUID, payload: AdminServiceAreaUpdate) -> AdminServiceAreaRead:
    service_area = _get_service_area_or_404(db, service_area_id)
    if payload.city is not None:
        service_area.city = payload.city.strip()
    if payload.district is not None:
        service_area.district = payload.district
    if payload.zone_name is not None:
        service_area.zone_name = payload.zone_name.strip()
    if payload.is_active is not None:
        service_area.is_active = payload.is_active
    if payload.postal_codes is not None:
        _replace_postal_codes(db, service_area, payload.postal_codes)

    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="One or more postal codes are already assigned to another service area.",
        ) from exc
    return _to_read(_get_service_area_or_404(db, service_area_id))


def delete_admin_service_area(db: Session, service_area_id: UUID) -> None:
    service_area = _get_service_area_or_404(db, service_area_id)
    db.delete(service_area)
    db.commit()
