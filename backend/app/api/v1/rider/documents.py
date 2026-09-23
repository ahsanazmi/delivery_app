from uuid import UUID

from fastapi import APIRouter, Depends, status

from app.api.v1.deps import DbSession, require_rider
from app.models.user import User
from app.schemas.rider_document import RiderDocumentCreate, RiderDocumentRead, RiderDocumentUpdate
from app.services.rider_documents import (
    create_rider_document,
    delete_rider_document,
    get_rider_document_or_404,
    list_rider_documents,
    update_rider_document,
)

router = APIRouter()


@router.get("/documents", response_model=list[RiderDocumentRead])
def list_documents(db: DbSession, current_rider: User = Depends(require_rider)) -> list[RiderDocumentRead]:
    return list_rider_documents(db, current_rider.id)


@router.post("/documents", response_model=RiderDocumentRead, status_code=status.HTTP_201_CREATED)
def create_document(
    payload: RiderDocumentCreate, db: DbSession, current_rider: User = Depends(require_rider)
) -> RiderDocumentRead:
    return create_rider_document(db, current_rider.id, payload)


@router.patch("/documents/{document_id}", response_model=RiderDocumentRead)
def patch_document(
    document_id: UUID,
    payload: RiderDocumentUpdate,
    db: DbSession,
    current_rider: User = Depends(require_rider),
) -> RiderDocumentRead:
    document = get_rider_document_or_404(db, current_rider.id, document_id)
    return update_rider_document(db, document, payload)


@router.delete("/documents/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_document(
    document_id: UUID, db: DbSession, current_rider: User = Depends(require_rider)
) -> None:
    document = get_rider_document_or_404(db, current_rider.id, document_id)
    delete_rider_document(db, document)
