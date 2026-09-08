from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.address import Address


def list_addresses(db: Session, user_id: UUID) -> list[Address]:
    statement = (
        select(Address)
        .where(Address.user_id == user_id, Address.is_active.is_(True))
        .order_by(Address.is_default.desc(), Address.created_at.desc())
    )
    return list(db.scalars(statement).all())


def create_address(db: Session, user_id: UUID, payload: dict) -> Address:
    payload = dict(payload)
    has_existing = db.query(Address).filter(Address.user_id == user_id, Address.is_active.is_(True)).count() > 0
    if "is_default" not in payload:
        payload["is_default"] = not has_existing
    if payload.get("is_default"):
        db.query(Address).filter(Address.user_id == user_id, Address.is_active.is_(True)).update({"is_default": False})
    address = Address(user_id=user_id, **payload)
    db.add(address)
    db.commit()
    db.refresh(address)
    return address


def get_address_for_user(db: Session, user_id: UUID, address_id: UUID) -> Address | None:
    return db.query(Address).filter(Address.id == address_id, Address.user_id == user_id, Address.is_active.is_(True)).first()


def set_default_address(db: Session, user_id: UUID, address_id: UUID) -> Address:
    target = get_address_for_user(db, user_id, address_id)
    if not target:
        raise ValueError("Address not found")
    db.query(Address).filter(Address.user_id == user_id, Address.is_active.is_(True)).update({"is_default": False})
    target.is_default = True
    db.commit()
    db.refresh(target)
    return target


def delete_address(db: Session, user_id: UUID, address_id: UUID) -> Address:
    target = get_address_for_user(db, user_id, address_id)
    if not target:
        raise ValueError("Address not found")
    target.is_active = False
    if target.is_default:
        next_default = list_addresses(db, user_id)
        if next_default:
            next_default[0].is_default = True
    db.commit()
    db.refresh(target)
    return target
