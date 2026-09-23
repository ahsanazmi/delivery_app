from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.notification import NotificationType
from app.models.rider_document import DocumentVerificationStatus, RiderDocument
from app.models.user import User
from app.schemas.rider_document import RiderDocumentCreate, RiderDocumentUpdate
from app.services.notifications import notify_admins


def list_rider_documents(db: Session, rider_id: UUID) -> list[RiderDocument]:
    statement = select(RiderDocument).where(RiderDocument.rider_id == rider_id).order_by(RiderDocument.created_at.asc())
    return list(db.scalars(statement))


def get_rider_document_or_404(db: Session, rider_id: UUID, document_id: UUID) -> RiderDocument:
    """Scoped to rider_id — a document belonging to a different rider is
    treated as not found, the same "never leak that it exists" pattern used
    throughout the Restaurant Owner Portal."""
    document = db.scalar(
        select(RiderDocument).where(RiderDocument.id == document_id, RiderDocument.rider_id == rider_id)
    )
    if not document:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")
    return document


def create_rider_document(db: Session, rider_id: UUID, payload: RiderDocumentCreate) -> RiderDocument:
    document = RiderDocument(
        rider_id=rider_id,
        document_type=payload.document_type,
        document_number=payload.document_number.strip() if payload.document_number else None,
        document_url=str(payload.document_url),
    )
    db.add(document)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"A {payload.document_type.value} document already exists — update it instead of creating a new one.",
        ) from exc

    rider = db.get(User, rider_id)
    notify_admins(
        db, NotificationType.DOCUMENT_SUBMITTED, "Document submitted",
        f"{rider.name if rider else 'A rider'} submitted a {payload.document_type.value.replace('_', ' ').title()} for review.",
    )

    db.commit()
    db.refresh(document)
    return document


def update_rider_document(db: Session, document: RiderDocument, payload: RiderDocumentUpdate) -> RiderDocument:
    """Replacing a document (new file and/or number) puts it back in the
    review queue — the previous approval/rejection was for the old file,
    not this one. Mirrors Phase 3's resubmit-clears-rejection-reason rule."""
    changed = False
    if payload.document_url is not None:
        document.document_url = str(payload.document_url)
        changed = True
    if payload.document_number is not None:
        document.document_number = payload.document_number.strip() or None
        changed = True

    if changed:
        document.verification_status = DocumentVerificationStatus.PENDING
        document.rejection_reason = None

    db.commit()
    db.refresh(document)
    return document


def delete_rider_document(db: Session, document: RiderDocument) -> None:
    db.delete(document)
    db.commit()


def review_rider_document(
    db: Session, document: RiderDocument, new_status: DocumentVerificationStatus, rejection_reason: str | None
) -> RiderDocument:
    """Admin-only mutation (called from the Admin module) — the counterpart
    to update_rider_document: this is the only place a document's
    verification_status actually changes based on review, as opposed to
    being reset to PENDING by the rider replacing the file."""
    document.verification_status = new_status
    document.rejection_reason = rejection_reason if new_status == DocumentVerificationStatus.REJECTED else None
    db.commit()
    db.refresh(document)
    return document
