from fastapi import APIRouter, Depends, HTTPException, status
from uuid import UUID
from typing import List

from app.api.v1.deps import DbSession, require_customer
from app.schemas.address import AddressRead, AddressCreate, AddressUpdate
from app.services.addresses import (
    list_addresses,
    create_address,
    get_address_for_user,
    set_default_address,
    delete_address,
)
from app.models.user import User, UserRole
from sqlalchemy.orm import Session

router = APIRouter()


@router.get("/addresses", response_model=List[AddressRead])
def list_customer_addresses(db: DbSession, current_user: User = Depends(require_customer)):
    return list_addresses(db, current_user.id)


@router.post("/addresses", response_model=AddressRead, status_code=status.HTTP_201_CREATED)
def create_customer_address(payload: AddressCreate, db: DbSession, current_user: User = Depends(require_customer)):
    return create_address(db, current_user.id, payload.model_dump())


@router.get("/addresses/{address_id}", response_model=AddressRead)
def get_customer_address(address_id: UUID, db: DbSession, current_user: User = Depends(require_customer)):
    address = get_address_for_user(db, current_user.id, address_id)
    if not address:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Address not found")
    return address


@router.patch("/addresses/{address_id}", response_model=AddressRead)
def update_customer_address(address_id: UUID, payload: AddressUpdate, db: DbSession, current_user: User = Depends(require_customer)):
    address = get_address_for_user(db, current_user.id, address_id)
    if not address:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Address not found")
    data = {k: v for k, v in payload.model_dump().items() if v is not None}
    for k, v in data.items():
        setattr(address, k, v)
    # handle is_default: if set true, clear others
    if data.get("is_default"):
        db.query(type(address)).filter(type(address).user_id == current_user.id, type(address).is_active.is_(True)).update({"is_default": False})
        address.is_default = True
    db.commit()
    db.refresh(address)
    return address


@router.delete("/addresses/{address_id}")
def delete_customer_address(address_id: UUID, db: DbSession, current_user: User = Depends(require_customer)):
    try:
        deleted = delete_address(db, current_user.id, address_id)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Address not found")
    return {"message": "deleted"}


@router.post("/addresses/{address_id}/default", response_model=AddressRead)
def post_set_default_address(address_id: UUID, db: DbSession, current_user: User = Depends(require_customer)):
    try:
        addr = set_default_address(db, current_user.id, address_id)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Address not found")
    return addr
