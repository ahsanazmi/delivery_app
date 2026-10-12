from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.v1.deps import DbSession, require_customer
from app.models.address import Address
from app.models.user import User
from app.schemas.address import AddressCreate, AddressRead, AddressUpdate
from app.services.addresses import create_address, delete_address, get_address_for_user, list_addresses, set_default_address

router = APIRouter()

# API Contract Validation (Phase 18) — this is the address-book surface the
# real customer-mobile app actually calls (services/api/addressesApi.ts
# uses the bare /api/v1/addresses path, not /api/v1/customer/addresses).
# Delivery addresses are a customer-only concept in this domain, so this
# needs the same require_customer gate every /api/v1/customer/* route
# already has (see Phase 2) — this file lived outside that directory and
# was missed by that pass entirely.


@router.get("", response_model=list[AddressRead])
def list_user_addresses(db: DbSession, current_user: User = Depends(require_customer)) -> list[AddressRead]:
    return list_addresses(db, current_user.id)


@router.post("", response_model=AddressRead, status_code=status.HTTP_201_CREATED)
def add_address(payload: AddressCreate, db: DbSession, current_user: User = Depends(require_customer)) -> AddressRead:
    data = payload.model_dump()
    # E2E Validation Phase 9 — AddressCreate defaults is_default to False, so a
    # plain model_dump() always carried it and create_address()'s "a customer's
    # first address becomes their default" rule never ran. Only pass it on
    # when the client actually chose a value.
    if "is_default" not in payload.model_fields_set:
        data.pop("is_default")
    return create_address(db, current_user.id, data)


@router.get("/{address_id}", response_model=AddressRead)
def get_address(address_id: UUID, db: DbSession, current_user: User = Depends(require_customer)) -> AddressRead:
    address = get_address_for_user(db, current_user.id, address_id)
    if not address:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Address not found")
    return address


@router.patch("/{address_id}", response_model=AddressRead)
def update_address(address_id: UUID, payload: AddressUpdate, db: DbSession, current_user: User = Depends(require_customer)) -> AddressRead:
    address = get_address_for_user(db, current_user.id, address_id)
    if not address:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Address not found")
    update_data = payload.model_dump(exclude_unset=True)
    if update_data.get("is_default") is not None and update_data["is_default"]:
        set_default_address(db, current_user.id, address_id)
        update_data.pop("is_default", None)
    # E2E Validation Phase 9 — AddressCreate enforces "both coordinates or
    # neither", but a PATCH of just one of them (e.g. {"latitude": null})
    # could leave half a pin. Check the resulting pair, not just the payload.
    latitude = update_data.get("latitude", address.latitude)
    longitude = update_data.get("longitude", address.longitude)
    if (latitude is None) != (longitude is None):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Both latitude and longitude must be provided together, or neither.",
        )
    for field, value in update_data.items():
        setattr(address, field, value)
    db.commit()
    db.refresh(address)
    return address


@router.delete("/{address_id}", response_model=AddressRead)
def remove_address(address_id: UUID, db: DbSession, current_user: User = Depends(require_customer)) -> AddressRead:
    try:
        address = delete_address(db, current_user.id, address_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return address


@router.patch("/{address_id}/default", response_model=AddressRead)
def set_default(address_id: UUID, db: DbSession, current_user: User = Depends(require_customer)) -> AddressRead:
    try:
        return set_default_address(db, current_user.id, address_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
