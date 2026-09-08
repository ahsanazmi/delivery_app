from uuid import UUID

from fastapi import APIRouter, HTTPException, status

from app.api.v1.deps import CurrentUser, DbSession
from app.models.address import Address
from app.schemas.address import AddressCreate, AddressRead, AddressUpdate
from app.services.addresses import create_address, delete_address, get_address_for_user, list_addresses, set_default_address

router = APIRouter()


@router.get("", response_model=list[AddressRead])
def list_user_addresses(db: DbSession, current_user: CurrentUser) -> list[AddressRead]:
    return list_addresses(db, current_user.id)


@router.post("", response_model=AddressRead, status_code=status.HTTP_201_CREATED)
def add_address(payload: AddressCreate, db: DbSession, current_user: CurrentUser) -> AddressRead:
    return create_address(db, current_user.id, payload.model_dump())


@router.get("/{address_id}", response_model=AddressRead)
def get_address(address_id: UUID, db: DbSession, current_user: CurrentUser) -> AddressRead:
    address = get_address_for_user(db, current_user.id, address_id)
    if not address:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Address not found")
    return address


@router.patch("/{address_id}", response_model=AddressRead)
def update_address(address_id: UUID, payload: AddressUpdate, db: DbSession, current_user: CurrentUser) -> AddressRead:
    address = get_address_for_user(db, current_user.id, address_id)
    if not address:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Address not found")
    update_data = payload.model_dump(exclude_unset=True)
    if update_data.get("is_default") is not None and update_data["is_default"]:
        set_default_address(db, current_user.id, address_id)
        update_data.pop("is_default", None)
    for field, value in update_data.items():
        setattr(address, field, value)
    db.commit()
    db.refresh(address)
    return address


@router.delete("/{address_id}", response_model=AddressRead)
def remove_address(address_id: UUID, db: DbSession, current_user: CurrentUser) -> AddressRead:
    try:
        address = delete_address(db, current_user.id, address_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return address


@router.patch("/{address_id}/default", response_model=AddressRead)
def set_default(address_id: UUID, db: DbSession, current_user: CurrentUser) -> AddressRead:
    try:
        return set_default_address(db, current_user.id, address_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
