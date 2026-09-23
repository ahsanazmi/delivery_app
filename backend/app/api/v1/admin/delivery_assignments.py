from datetime import date
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from app.api.v1.deps import DbSession, require_admin
from app.models.user import User
from app.schemas.admin import (
    AdminAssignmentStatusValue,
    AdminDeliveryAssignmentDetail,
    AdminDeliveryAssignmentListResponse,
)
from app.services.admin_delivery_assignments import get_admin_delivery_assignment_detail, list_admin_delivery_assignments

router = APIRouter()


# View-only, deliberately — this phase's own brief closes with "Do not
# allow arbitrary rider assignment changes without validation." The only
# sanctioned way to change who's assigned to an order is the already-
# validated POST /admin/orders/{id}/reassign-rider from Phase 11; nothing
# here writes anything.
@router.get("/delivery-assignments", response_model=AdminDeliveryAssignmentListResponse)
def list_delivery_assignments(
    db: DbSession,
    search: str | None = Query(default=None),
    status_filter: AdminAssignmentStatusValue | None = Query(default=None, alias="status"),
    date_from: date | None = Query(default=None),
    date_to: date | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=20, ge=1, le=100),
    current_admin: User = Depends(require_admin),
) -> AdminDeliveryAssignmentListResponse:
    return list_admin_delivery_assignments(
        db, search=search, status_filter=status_filter, date_from=date_from, date_to=date_to, page=page, limit=limit
    )


# Registered after the plain list on purpose — same established convention
# as every other admin list-then-detail route pair. Only ever resolves a
# real DeliveryAssignment row — a synthesized PENDING entry from the list
# above has no id to look up here (see its own id=None) and isn't reachable
# through this endpoint at all.
@router.get("/delivery-assignments/{assignment_id}", response_model=AdminDeliveryAssignmentDetail)
def get_delivery_assignment(
    assignment_id: UUID, db: DbSession, current_admin: User = Depends(require_admin)
) -> AdminDeliveryAssignmentDetail:
    return get_admin_delivery_assignment_detail(db, assignment_id)
