from decimal import Decimal
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.models.delivery_partner import ApprovalStatus, DeliveryPartner
from app.models.order import Order, OrderStatus
from app.models.review import Review
from app.models.rider_document import DocumentVerificationStatus
from app.models.rider_earning import RiderEarning
from app.models.user import User, UserRole
from app.schemas.admin import AdminRiderDetail, AdminRiderListResponse, AdminRiderSummary
from app.schemas.rider_document import RiderDocumentRead
from app.services.admin_account_status import set_user_active_status
from app.services.admin_audit_log import record_admin_audit_log
from app.services.rider_documents import get_rider_document_or_404, list_rider_documents, review_rider_document
from app.services.rider_history import list_rider_history
from app.services.rider_service import get_or_create_delivery_partner, update_rider_verification

_ZERO = Decimal("0.00")
RECENT_DELIVERIES_LIMIT = 20


def _delivery_partners_by_rider(db: Session, rider_ids: list[UUID]) -> dict[UUID, DeliveryPartner]:
    if not rider_ids:
        return {}
    partners = db.scalars(select(DeliveryPartner).where(DeliveryPartner.user_id.in_(rider_ids))).all()
    return {partner.user_id: partner for partner in partners}


def _ratings_by_rider(db: Session, rider_ids: list[UUID]) -> dict[UUID, float]:
    """Average of Review.delivery_rating per rider — the real per-order
    delivery rating a customer leaves (see create_order_review in
    reviews.py), not the generic single-target Review.rating column, which
    is never populated with target_type=RIDER by the current review flow."""
    if not rider_ids:
        return {}
    rows = db.execute(
        select(Review.rider_id, func.avg(Review.delivery_rating))
        .where(Review.rider_id.in_(rider_ids), Review.delivery_rating.is_not(None))
        .group_by(Review.rider_id)
    ).all()
    return {rider_id: round(float(avg), 2) for rider_id, avg in rows}


def _delivery_counts_by_rider(db: Session, rider_ids: list[UUID]) -> dict[UUID, int]:
    if not rider_ids:
        return {}
    rows = db.execute(
        select(Order.rider_id, func.count(Order.id))
        .where(Order.rider_id.in_(rider_ids), Order.status == OrderStatus.DELIVERED)
        .group_by(Order.rider_id)
    ).all()
    return dict(rows)


def _earnings_by_rider(db: Session, rider_ids: list[UUID]) -> dict[UUID, Decimal]:
    if not rider_ids:
        return {}
    rows = db.execute(
        select(RiderEarning.rider_id, func.coalesce(func.sum(RiderEarning.amount), _ZERO))
        .where(RiderEarning.rider_id.in_(rider_ids))
        .group_by(RiderEarning.rider_id)
    ).all()
    return dict(rows)


def _to_summary(
    rider: User, partner: DeliveryPartner | None, rating: float, deliveries_count: int, total_earnings: Decimal
) -> AdminRiderSummary:
    # A rider with no DeliveryPartner row yet (never touched the rider app)
    # is treated exactly like a freshly-created one would read as —
    # PENDING, offline, no vehicle — never a crash or a null approval_status.
    return AdminRiderSummary(
        id=rider.id,
        name=rider.name,
        phone=rider.phone,
        email=rider.email,
        approval_status=partner.approval_status if partner else ApprovalStatus.PENDING,
        rejection_reason=partner.rejection_reason if partner else None,
        is_online=partner.is_online if partner else False,
        vehicle_type=partner.vehicle_type if partner else None,
        vehicle_number=partner.vehicle_number if partner else None,
        rating=rating,
        deliveries_count=deliveries_count,
        total_earnings=total_earnings,
        created_at=rider.created_at,
        is_active=rider.is_active,
    )


def list_admin_riders(
    db: Session,
    *,
    search: str | None,
    approval_filter: ApprovalStatus | None,
    is_online: bool | None,
    page: int,
    limit: int,
) -> AdminRiderListResponse:
    conditions = [User.role == UserRole.RIDER]
    if search:
        pattern = f"%{search.strip()}%"
        conditions.append((User.name.ilike(pattern)) | (User.email.ilike(pattern)) | (User.phone.ilike(pattern)))
    if approval_filter is not None:
        if approval_filter == ApprovalStatus.PENDING:
            # A rider who's never touched the app has no DeliveryPartner row
            # at all yet, but reads as PENDING everywhere else — so PENDING
            # must match that absence too, not just an explicit PENDING row.
            conditions.append(or_(DeliveryPartner.approval_status == ApprovalStatus.PENDING, DeliveryPartner.id.is_(None)))
        else:
            conditions.append(DeliveryPartner.approval_status == approval_filter)
    if is_online is not None:
        conditions.append(
            DeliveryPartner.is_online.is_(True)
            if is_online
            else or_(DeliveryPartner.is_online.is_(False), DeliveryPartner.id.is_(None))
        )

    base = select(User).outerjoin(DeliveryPartner, DeliveryPartner.user_id == User.id).where(*conditions)
    total = db.scalar(select(func.count()).select_from(base.subquery())) or 0

    offset = (page - 1) * limit
    riders = db.scalars(base.order_by(User.created_at.desc()).offset(offset).limit(limit)).all()

    rider_ids = [rider.id for rider in riders]
    partners = _delivery_partners_by_rider(db, rider_ids)
    ratings = _ratings_by_rider(db, rider_ids)
    delivery_counts = _delivery_counts_by_rider(db, rider_ids)
    earnings = _earnings_by_rider(db, rider_ids)

    items = [
        _to_summary(rider, partners.get(rider.id), ratings.get(rider.id, 0.0), delivery_counts.get(rider.id, 0), earnings.get(rider.id, _ZERO))
        for rider in riders
    ]
    return AdminRiderListResponse(items=items, total=total, page=page, limit=limit)


def _get_rider_or_404(db: Session, rider_id: UUID) -> User:
    rider = db.get(User, rider_id)
    if not rider or rider.role != UserRole.RIDER:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Rider not found")
    return rider


def get_admin_rider_detail(db: Session, rider_id: UUID) -> AdminRiderDetail:
    rider = _get_rider_or_404(db, rider_id)
    partner = db.scalar(select(DeliveryPartner).where(DeliveryPartner.user_id == rider.id))
    rating = _ratings_by_rider(db, [rider.id]).get(rider.id, 0.0)
    deliveries_count = _delivery_counts_by_rider(db, [rider.id]).get(rider.id, 0)
    total_earnings = _earnings_by_rider(db, [rider.id]).get(rider.id, _ZERO)

    summary = _to_summary(rider, partner, rating, deliveries_count, total_earnings)
    documents = list_rider_documents(db, rider.id)
    recent_deliveries = list_rider_history(db, rider, limit=RECENT_DELIVERIES_LIMIT)
    return AdminRiderDetail(
        **summary.model_dump(),
        documents=[RiderDocumentRead.model_validate(document) for document in documents],
        recent_deliveries=recent_deliveries,
    )


# Phase 7 — rider approval state machine, the same choke-point pattern as
# Phase 6's restaurant approval actions, unified into one PATCH body here
# (the phase's own endpoint list has a single PATCH, not four POSTs).
_RIDER_APPROVAL_ACTION_TRANSITIONS: dict[str, dict[ApprovalStatus, ApprovalStatus]] = {
    "approve": {
        ApprovalStatus.PENDING: ApprovalStatus.APPROVED,
        ApprovalStatus.REJECTED: ApprovalStatus.APPROVED,
    },
    "reject": {ApprovalStatus.PENDING: ApprovalStatus.REJECTED},
    "suspend": {ApprovalStatus.APPROVED: ApprovalStatus.SUSPENDED},
    "activate": {ApprovalStatus.SUSPENDED: ApprovalStatus.APPROVED},
}


def update_admin_rider_approval(
    db: Session, admin: User, rider_id: UUID, action: str, reason: str, ip_address: str | None = None
) -> AdminRiderDetail:
    """Admin Intervention Validation (Phase 21) — approve/reject/suspend/
    activate previously took no admin, required no reason for three of the
    four actions, and wrote no audit log entry at all — the same gap
    admin_restaurants.py's equivalent actions had. Now audited via the
    same record_admin_audit_log every other administrative intervention
    in this codebase goes through."""
    rider = _get_rider_or_404(db, rider_id)
    partner = get_or_create_delivery_partner(db, rider)
    previous_status = partner.approval_status
    next_status = _RIDER_APPROVAL_ACTION_TRANSITIONS[action].get(partner.approval_status)
    if next_status is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Cannot {action} a rider with approval_status={partner.approval_status.value}",
        )
    # Audit entry flushed (not committed) before the mutation below, so
    # update_rider_verification's own commit persists both atomically —
    # same ordering as admin_cancel_order and every other intervention
    # here, so a rejected/failed transition can never leave an orphaned
    # log entry for something that didn't actually happen.
    record_admin_audit_log(
        db, admin_id=admin.id, action=f"rider.{action}", target_type="rider", target_id=str(rider.id),
        reason=reason, previous_state=previous_status.value, new_state=next_status.value, ip_address=ip_address,
    )
    # update_rider_verification already handles clearing rejection_reason,
    # forcing is_online False on any non-APPROVED status, and sending the
    # approved/suspended notifications — reused as-is so this validated
    # action gets those side effects for free instead of duplicating them.
    update_rider_verification(db, rider_id, next_status, reason if next_status == ApprovalStatus.REJECTED else None)
    return get_admin_rider_detail(db, rider_id)


# Admin Portal Phase 23 — the account-level on/off switch (User.is_active),
# a genuinely new capability distinct from the approval_status suspend/
# activate above (delivery eligibility, Phase 7/9). Named deactivate/
# reactivate to avoid colliding with those two already-taken words.
def deactivate_admin_rider(
    db: Session, admin: User, rider_id: UUID, reason: str, ip_address: str | None = None
) -> AdminRiderDetail:
    rider = _get_rider_or_404(db, rider_id)
    set_user_active_status(
        db, admin, rider, target_active=False, action="rider.deactivate", target_type="rider",
        reason=reason, ip_address=ip_address,
    )
    db.commit()
    db.refresh(rider)
    return get_admin_rider_detail(db, rider_id)


def reactivate_admin_rider(
    db: Session, admin: User, rider_id: UUID, reason: str, ip_address: str | None = None
) -> AdminRiderDetail:
    rider = _get_rider_or_404(db, rider_id)
    set_user_active_status(
        db, admin, rider, target_active=True, action="rider.reactivate", target_type="rider",
        reason=reason, ip_address=ip_address,
    )
    db.commit()
    db.refresh(rider)
    return get_admin_rider_detail(db, rider_id)


# Phase 8 — rider document verification. Unlike the 4-state approval_status
# machine above, a document only ever has PENDING/APPROVED/REJECTED — no
# "suspended" state — so the only genuinely invalid move is a self-transition
# (approving an already-approved document, rejecting an already-rejected
# one); a rider re-uploading a file (update_rider_document) already resets
# it to PENDING on their own, so there's no admin-side "reset" action needed.
_DOCUMENT_ACTION_VALID_FROM: dict[str, set[DocumentVerificationStatus]] = {
    "approve": {DocumentVerificationStatus.PENDING, DocumentVerificationStatus.REJECTED},
    "reject": {DocumentVerificationStatus.PENDING, DocumentVerificationStatus.APPROVED},
}


def list_admin_rider_documents(db: Session, rider_id: UUID) -> list[RiderDocumentRead]:
    _get_rider_or_404(db, rider_id)
    documents = list_rider_documents(db, rider_id)
    return [RiderDocumentRead.model_validate(document) for document in documents]


def _transition_document(
    db: Session, rider_id: UUID, document_id: UUID, action: str, rejection_reason: str | None
) -> RiderDocumentRead:
    _get_rider_or_404(db, rider_id)
    document = get_rider_document_or_404(db, rider_id, document_id)
    if document.verification_status not in _DOCUMENT_ACTION_VALID_FROM[action]:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Cannot {action} a document with verification_status={document.verification_status.value}",
        )
    new_status = DocumentVerificationStatus.APPROVED if action == "approve" else DocumentVerificationStatus.REJECTED
    updated = review_rider_document(db, document, new_status, rejection_reason)
    return RiderDocumentRead.model_validate(updated)


def approve_admin_rider_document(db: Session, rider_id: UUID, document_id: UUID) -> RiderDocumentRead:
    return _transition_document(db, rider_id, document_id, "approve", None)


def reject_admin_rider_document(db: Session, rider_id: UUID, document_id: UUID, rejection_reason: str) -> RiderDocumentRead:
    return _transition_document(db, rider_id, document_id, "reject", rejection_reason)
