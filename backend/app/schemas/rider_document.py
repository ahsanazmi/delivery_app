from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, HttpUrl

from app.models.rider_document import DocumentType, DocumentVerificationStatus


class RiderDocumentCreate(BaseModel):
    document_type: DocumentType
    document_url: HttpUrl
    document_number: str | None = Field(default=None, max_length=120)


class RiderDocumentUpdate(BaseModel):
    """Replacing a document — a new file and/or number. There is no field
    for verification_status here on purpose: a rider can never set their own
    document's review outcome, only an admin can (see the Admin module)."""

    document_url: HttpUrl | None = None
    document_number: str | None = Field(default=None, max_length=120)


class RiderDocumentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    document_type: DocumentType
    document_number: str | None
    document_url: str
    verification_status: DocumentVerificationStatus
    rejection_reason: str | None
    created_at: datetime
    updated_at: datetime
