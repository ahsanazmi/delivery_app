from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status

from app.api.v1.deps import DbSession, require_admin
from app.models.delivery_partner import ApprovalStatus
from app.models.user import User, UserRole
from app.schemas.admin import (
    AdminAccountActionRequest,
    AdminRiderApprovalAction,
    AdminRiderDetail,
    AdminRiderDocumentRejectRequest,
    AdminRiderDocumentReview,
    AdminRiderListResponse,
    AdminRiderRejectRequest,
    AdminRiderVerificationUpdate,
)
from app.schemas.rider import RiderVerificationRead
from app.schemas.rider_document import RiderDocumentRead
from app.services.admin_riders import (
    approve_admin_rider_document,
    deactivate_admin_rider,
    get_admin_rider_detail,
    list_admin_rider_documents,
    list_admin_riders,
    reactivate_admin_rider,
    reject_admin_rider_document,
    update_admin_rider_approval,
)
from app.services.rider_documents import get_rider_document_or_404, review_rider_document
from app.services.rider_service import update_rider_verification

router = APIRouter()


@router.get("/riders", response_model=AdminRiderListResponse)
def list_riders(
    db: DbSession,
    search: str | None = Query(default=None),
    approval_status: ApprovalStatus | None = Query(default=None),
    is_online: bool | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=20, ge=1, le=100),
    current_admin: User = Depends(require_admin),
) -> AdminRiderListResponse:
    return list_admin_riders(
        db, search=search, approval_filter=approval_status, is_online=is_online, page=page, limit=limit
    )


# Registered after the plain /riders list on purpose — same established
# convention as every other admin list-then-detail route pair.
@router.get("/riders/{rider_id}", response_model=AdminRiderDetail)
def get_rider(rider_id: UUID, db: DbSession, current_admin: User = Depends(require_admin)) -> AdminRiderDetail:
    return get_admin_rider_detail(db, rider_id)


@router.patch("/riders/{rider_id}", response_model=AdminRiderDetail)
def update_rider(
    rider_id: UUID,
    payload: AdminRiderApprovalAction,
    db: DbSession,
    request: Request,
    current_admin: User = Depends(require_admin),
) -> AdminRiderDetail:
    ip_address = request.client.host if request.client else None
    return update_admin_rider_approval(db, current_admin, rider_id, payload.action, payload.reason, ip_address)


# Phase 9 — the same validated action already implemented for
# PATCH /riders/{id} above, exposed as dedicated per-action routes
# (mirroring Phase 6's restaurant approve/reject/suspend/activate
# endpoints). Both paths call the exact same update_admin_rider_approval,
# so there is only ever one transition table to keep correct.
@router.post("/riders/{rider_id}/approve", response_model=AdminRiderDetail)
def approve_rider(
    rider_id: UUID,
    payload: AdminAccountActionRequest,
    db: DbSession,
    request: Request,
    current_admin: User = Depends(require_admin),
) -> AdminRiderDetail:
    ip_address = request.client.host if request.client else None
    return update_admin_rider_approval(db, current_admin, rider_id, "approve", payload.reason, ip_address)


@router.post("/riders/{rider_id}/reject", response_model=AdminRiderDetail)
def reject_rider(
    rider_id: UUID,
    payload: AdminRiderRejectRequest,
    db: DbSession,
    request: Request,
    current_admin: User = Depends(require_admin),
) -> AdminRiderDetail:
    ip_address = request.client.host if request.client else None
    return update_admin_rider_approval(db, current_admin, rider_id, "reject", payload.rejection_reason, ip_address)


@router.post("/riders/{rider_id}/suspend", response_model=AdminRiderDetail)
def suspend_rider(
    rider_id: UUID,
    payload: AdminAccountActionRequest,
    db: DbSession,
    request: Request,
    current_admin: User = Depends(require_admin),
) -> AdminRiderDetail:
    ip_address = request.client.host if request.client else None
    return update_admin_rider_approval(db, current_admin, rider_id, "suspend", payload.reason, ip_address)


@router.post("/riders/{rider_id}/activate", response_model=AdminRiderDetail)
def activate_rider(
    rider_id: UUID,
    payload: AdminAccountActionRequest,
    db: DbSession,
    request: Request,
    current_admin: User = Depends(require_admin),
) -> AdminRiderDetail:
    ip_address = request.client.host if request.client else None
    return update_admin_rider_approval(db, current_admin, rider_id, "activate", payload.reason, ip_address)


# Admin Portal Phase 23 — a genuinely new, account-level capability
# (User.is_active) distinct from the approval_status suspend/activate
# above, which only ever governed delivery eligibility. Named deactivate/
# reactivate since suspend/activate are already taken by Phase 9's actions.
@router.post("/riders/{rider_id}/deactivate", response_model=AdminRiderDetail)
def deactivate_rider(
    rider_id: UUID,
    payload: AdminAccountActionRequest,
    db: DbSession,
    request: Request,
    current_admin: User = Depends(require_admin),
) -> AdminRiderDetail:
    ip_address = request.client.host if request.client else None
    return deactivate_admin_rider(db, current_admin, rider_id, payload.reason, ip_address)


@router.post("/riders/{rider_id}/reactivate", response_model=AdminRiderDetail)
def reactivate_rider(
    rider_id: UUID,
    payload: AdminAccountActionRequest,
    db: DbSession,
    request: Request,
    current_admin: User = Depends(require_admin),
) -> AdminRiderDetail:
    ip_address = request.client.host if request.client else None
    return reactivate_admin_rider(db, current_admin, rider_id, payload.reason, ip_address)


# Moved from app/api/v1/endpoints/admin.py (Phase 7) — same path, same
# behavior, unchanged. Left deliberately unvalidated (any approval_status ->
# any approval_status) exactly as before: this is pre-existing, heavily
# tested infrastructure from the Rider Portal phases, not something this
# phase asked to change. The new validated PATCH /riders/{id} above is the
# Admin Portal UI's own path; this one keeps serving whatever already calls it.
@router.patch("/riders/{rider_id}/verification", response_model=RiderVerificationRead)
def update_rider_verification_status(
    rider_id: UUID,
    payload: AdminRiderVerificationUpdate,
    db: DbSession,
    current_admin: User = Depends(require_admin),
) -> RiderVerificationRead:
    rider = db.get(User, rider_id)
    if not rider or rider.role != UserRole.RIDER:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Rider not found")
    return update_rider_verification(db, rider_id, payload.approval_status, payload.rejection_reason)


# Moved from app/api/v1/endpoints/admin.py (Phase 7) — same path, same behavior.
@router.patch("/riders/{rider_id}/documents/{document_id}", response_model=RiderDocumentRead)
def review_rider_document_status(
    rider_id: UUID,
    document_id: UUID,
    payload: AdminRiderDocumentReview,
    db: DbSession,
    current_admin: User = Depends(require_admin),
) -> RiderDocumentRead:
    rider = db.get(User, rider_id)
    if not rider or rider.role != UserRole.RIDER:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Rider not found")
    document = get_rider_document_or_404(db, rider_id, document_id)
    return review_rider_document(db, document, payload.verification_status, payload.rejection_reason)


# Phase 8 — dedicated, validated document-verification endpoints. The
# legacy PATCH .../documents/{id} above stays exactly as-is; these are
# additive, matching the same "new validated path alongside old unvalidated
# one" precedent as PATCH /riders/{id} vs /riders/{id}/verification.
@router.get("/riders/{rider_id}/documents", response_model=list[RiderDocumentRead])
def list_rider_documents_route(
    rider_id: UUID, db: DbSession, current_admin: User = Depends(require_admin)
) -> list[RiderDocumentRead]:
    return list_admin_rider_documents(db, rider_id)


@router.post("/riders/{rider_id}/documents/{document_id}/approve", response_model=RiderDocumentRead)
def approve_rider_document(
    rider_id: UUID, document_id: UUID, db: DbSession, current_admin: User = Depends(require_admin)
) -> RiderDocumentRead:
    return approve_admin_rider_document(db, rider_id, document_id)


@router.post("/riders/{rider_id}/documents/{document_id}/reject", response_model=RiderDocumentRead)
def reject_rider_document(
    rider_id: UUID,
    document_id: UUID,
    payload: AdminRiderDocumentRejectRequest,
    db: DbSession,
    current_admin: User = Depends(require_admin),
) -> RiderDocumentRead:
    return reject_admin_rider_document(db, rider_id, document_id, payload.rejection_reason)
