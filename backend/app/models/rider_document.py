import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class DocumentType(str, enum.Enum):
    DRIVING_LICENSE = "DRIVING_LICENSE"
    VEHICLE_REGISTRATION = "VEHICLE_REGISTRATION"
    IDENTITY_DOCUMENT = "IDENTITY_DOCUMENT"
    BANK_DOCUMENT = "BANK_DOCUMENT"
    PROFILE_PHOTO = "PROFILE_PHOTO"


class DocumentVerificationStatus(str, enum.Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class RiderDocument(Base):
    """A rider's uploaded document. The backend never receives or stores raw
    file bytes — like every other image/logo field in this codebase
    (Restaurant.logo_url, MenuCategory.image_url, Product.image_url), the
    client uploads the actual file to external storage first and only sends
    the resulting URL here. That's "storing files securely" the same way
    the rest of the app already does it: this service is never in the
    business of handling raw uploads or serving them back, so there's no
    local storage path, access-control-on-disk, or file-serving surface to
    get wrong. document_number is free text and deliberately unvalidated
    against any real-world ID format — this app has no business hard-coding
    assumptions about what a driving license or bank account number looks
    like in a given country."""

    __tablename__ = "rider_documents"
    __table_args__ = (
        # One current record per document type per rider — "replace" means
        # PATCH the existing row, not pile up duplicates of the same type.
        UniqueConstraint("rider_id", "document_type", name="uq_rider_documents_rider_id_document_type"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    rider_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    document_type: Mapped[DocumentType] = mapped_column(
        Enum(DocumentType, name="rider_document_type", values_callable=lambda enum_cls: [e.value for e in enum_cls]),
        nullable=False,
    )
    document_number: Mapped[str | None] = mapped_column(String(120), nullable=True)
    document_url: Mapped[str] = mapped_column(String(2048), nullable=False)
    verification_status: Mapped[DocumentVerificationStatus] = mapped_column(
        Enum(
            DocumentVerificationStatus,
            name="rider_document_verification_status",
            values_callable=lambda enum_cls: [e.value for e in enum_cls],
        ),
        default=DocumentVerificationStatus.PENDING,
        nullable=False,
    )
    rejection_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
