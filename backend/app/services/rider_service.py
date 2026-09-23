from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.models.delivery_partner import ApprovalStatus, DeliveryPartner
from app.models.notification import Notification, NotificationType
from app.models.rider_document import DocumentType, DocumentVerificationStatus
from app.models.user import User
from app.schemas.rider import RiderProfileUpdate, RiderStatusRead, RiderVehicleUpdate
from app.services.auth import get_user_by_email, get_user_by_phone
from app.services.push_notifications import send_push_to_user
from app.services.rider_documents import list_rider_documents

# Phase 7 — the documents a rider must have APPROVED before they're allowed
# online. Bank Document is deliberately excluded: it gates getting *paid*
# (a Wallet-phase concern), not whether it's safe/legal to dispatch them —
# a rider can start delivering before their payout details are verified.
REQUIRED_DOCUMENT_TYPES: tuple[DocumentType, ...] = (
    DocumentType.DRIVING_LICENSE,
    DocumentType.VEHICLE_REGISTRATION,
    DocumentType.IDENTITY_DOCUMENT,
    DocumentType.PROFILE_PHOTO,
)

_DOCUMENT_LABELS: dict[DocumentType, str] = {
    DocumentType.DRIVING_LICENSE: "driving license",
    DocumentType.VEHICLE_REGISTRATION: "vehicle registration",
    DocumentType.IDENTITY_DOCUMENT: "identity document",
    DocumentType.BANK_DOCUMENT: "bank document",
    DocumentType.PROFILE_PHOTO: "profile photo",
}


def update_rider_profile(db: Session, rider: User, payload: RiderProfileUpdate) -> User:
    """Every field is optional and independent (PATCH semantics) — only the
    fields actually sent are touched. Email/phone are checked against every
    other user first, the same uniqueness registration itself enforces,
    so a collision surfaces as a clean 409 instead of a raw IntegrityError."""
    if payload.name is not None:
        rider.name = payload.name.strip()

    if payload.email is not None:
        normalized_email = str(payload.email).lower().strip()
        existing = get_user_by_email(db, normalized_email)
        if existing and existing.id != rider.id:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="An account with this email already exists")
        rider.email = normalized_email

    if payload.phone is not None:
        normalized_phone = payload.phone.strip()
        existing = get_user_by_phone(db, normalized_phone)
        if existing and existing.id != rider.id:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="An account with this phone number already exists")
        rider.phone = normalized_phone

    if payload.profile_image is not None:
        rider.profile_image = payload.profile_image

    db.commit()
    db.refresh(rider)
    return rider


def get_or_create_delivery_partner(db: Session, rider: User) -> DeliveryPartner:
    """Every RIDER gets exactly one of these, created the first time it's
    needed rather than at registration — so accounts created before this
    table existed (or before a rider ever opens the verification screen)
    still get a well-defined PENDING status instead of a 404."""
    partner = db.query(DeliveryPartner).filter(DeliveryPartner.user_id == rider.id).first()
    if partner:
        return partner

    partner = DeliveryPartner(user_id=rider.id, approval_status=ApprovalStatus.PENDING)
    db.add(partner)
    db.commit()
    db.refresh(partner)
    return partner


def assert_rider_approved(db: Session, rider: User) -> DeliveryPartner:
    """The enforcement point for "a rider who is not approved must not be
    allowed to become available for deliveries" — called from the actual
    delivery-performing actions (pickup/deliver), not from read-only ones."""
    partner = get_or_create_delivery_partner(db, rider)
    if partner.approval_status != ApprovalStatus.APPROVED:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Your rider account is not approved for deliveries yet.",
        )
    return partner


def update_rider_verification(
    db: Session, rider_user_id: UUID, new_status: ApprovalStatus, rejection_reason: str | None = None
) -> DeliveryPartner:
    """Admin-only mutation (called from the Admin module, never from a rider
    endpoint) — a rider can only ever read their own status, never set it."""
    rider = db.get(User, rider_user_id)
    if not rider:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Rider not found")

    partner = get_or_create_delivery_partner(db, rider)
    partner.approval_status = new_status
    partner.rejection_reason = rejection_reason if new_status == ApprovalStatus.REJECTED else None
    if new_status != ApprovalStatus.APPROVED:
        # A rider moved to PENDING/REJECTED/SUSPENDED can't be left showing
        # as online — most importantly SUSPENDED, which can happen while a
        # rider is actively online; this is what actually makes "suspended
        # -> cannot accept deliveries" take effect immediately rather than
        # just the next time they try to toggle it themselves.
        partner.is_online = False

    if new_status == ApprovalStatus.APPROVED:
        title = "Account approved"
        body = "Your rider account has been approved. You can now go online and accept deliveries."
        db.add(Notification(user_id=rider.id, type=NotificationType.ACCOUNT_APPROVED, title=title, body=body))
        send_push_to_user(db, rider.id, title, body, data={"type": "account_approved"})
    elif new_status == ApprovalStatus.SUSPENDED:
        title = "Account suspended"
        body = "Your rider account has been suspended. Contact support for details."
        db.add(Notification(user_id=rider.id, type=NotificationType.ACCOUNT_SUSPENDED, title=title, body=body))
        send_push_to_user(db, rider.id, title, body, data={"type": "account_suspended"})

    db.commit()
    db.refresh(partner)
    return partner


def resubmit_rider_verification(db: Session, rider: User) -> DeliveryPartner:
    """The rider's own half of "Rejected -> Reason -> Resubmit" — puts a
    rejected application back into the review queue. Only reachable from
    REJECTED; there's nothing to resubmit from PENDING/APPROVED/SUSPENDED."""
    partner = get_or_create_delivery_partner(db, rider)
    if partner.approval_status != ApprovalStatus.REJECTED:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Only a rejected application can be resubmitted.",
        )
    partner.approval_status = ApprovalStatus.PENDING
    partner.rejection_reason = None
    db.commit()
    db.refresh(partner)
    return partner


def update_rider_vehicle(db: Session, rider: User, payload: RiderVehicleUpdate) -> DeliveryPartner:
    """PATCH semantics, same convention as update_rider_profile — only
    fields actually sent are touched."""
    partner = get_or_create_delivery_partner(db, rider)
    if payload.vehicle_type is not None:
        partner.vehicle_type = payload.vehicle_type
    if payload.vehicle_number is not None:
        partner.vehicle_number = payload.vehicle_number.strip()
    if payload.vehicle_model is not None:
        partner.vehicle_model = payload.vehicle_model.strip()
    db.commit()
    db.refresh(partner)
    return partner


def get_online_eligibility_blocker(db: Session, rider: User, partner: DeliveryPartner) -> str | None:
    """Phase 7's full "can this rider go online" check, in priority order.
    Returns the first unmet condition's message, or None if every condition
    is satisfied. Checked both proactively (GET /rider/status, so the
    frontend can grey out the toggle before the rider even tries) and
    authoritatively (PATCH /rider/status, which never trusts what GET said
    a moment ago)."""
    if partner.approval_status == ApprovalStatus.SUSPENDED:
        return "Your rider account has been suspended."
    if partner.approval_status == ApprovalStatus.REJECTED:
        return "Your rider application was rejected."
    if partner.approval_status == ApprovalStatus.PENDING:
        return "Your rider application is still under review."

    approved_types = {
        doc.document_type
        for doc in list_rider_documents(db, rider.id)
        if doc.verification_status == DocumentVerificationStatus.APPROVED
    }
    for document_type in REQUIRED_DOCUMENT_TYPES:
        if document_type not in approved_types:
            return f"Your {_DOCUMENT_LABELS[document_type]} must be uploaded and approved before you can go online."

    if not rider.phone:
        return "Add a phone number to your profile before going online."
    if not partner.vehicle_type or not partner.vehicle_number:
        return "Add your vehicle type and vehicle number before going online."

    return None


def build_rider_status(db: Session, rider: User, partner: DeliveryPartner | None = None) -> RiderStatusRead:
    partner = partner or get_or_create_delivery_partner(db, rider)
    blocker = get_online_eligibility_blocker(db, rider, partner)
    return RiderStatusRead(
        approval_status=partner.approval_status,
        is_online=partner.is_online,
        can_go_online=blocker is None,
        online_blocked_reason=blocker,
        updated_at=partner.updated_at,
    )


def set_rider_online_status(db: Session, rider: User, is_online: bool) -> RiderStatusRead:
    """Phase 7's enforcement point: going online requires every condition in
    get_online_eligibility_blocker to pass — approved, not suspended, every
    required document approved, and profile/vehicle info completed. Going
    offline is always allowed regardless of status — there's never a reason
    to block a rider from stepping away."""
    partner = get_or_create_delivery_partner(db, rider)
    if is_online:
        blocker = get_online_eligibility_blocker(db, rider, partner)
        if blocker:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=blocker)
    partner.is_online = is_online
    db.commit()
    db.refresh(partner)
    return build_rider_status(db, rider, partner)
