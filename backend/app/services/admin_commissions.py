from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.commission_rule import CommissionRule, CommissionType
from app.models.restaurant import Restaurant
from app.schemas.admin import (
    AdminCommissionConfigRead,
    AdminCommissionDefaultInput,
    AdminCommissionOverrideInput,
    AdminCommissionRuleRead,
    AdminCommissionUpdateRequest,
)
from app.services.commissions import get_default_commission_rule, get_restaurant_commission_rule


def _to_read(rule: CommissionRule, restaurant_name: str | None) -> AdminCommissionRuleRead:
    return AdminCommissionRuleRead(
        restaurant_id=rule.restaurant_id,
        restaurant_name=restaurant_name,
        commission_type=rule.commission_type.value,
        value=rule.value,
        updated_at=rule.updated_at,
    )


def get_admin_commission_config(db: Session) -> AdminCommissionConfigRead:
    default_rule = get_default_commission_rule(db)
    overrides = db.scalars(
        select(CommissionRule).where(CommissionRule.restaurant_id.is_not(None)).order_by(CommissionRule.updated_at.desc())
    ).all()

    restaurant_ids = [rule.restaurant_id for rule in overrides]
    restaurants = {r.id: r for r in db.scalars(select(Restaurant).where(Restaurant.id.in_(restaurant_ids)))} if restaurant_ids else {}

    return AdminCommissionConfigRead(
        default=_to_read(default_rule, None) if default_rule else None,
        restaurant_overrides=[
            _to_read(rule, restaurants[rule.restaurant_id].name if rule.restaurant_id in restaurants else None)
            for rule in overrides
        ],
    )


def _upsert_default(db: Session, payload: AdminCommissionDefaultInput) -> None:
    rule = get_default_commission_rule(db)
    if rule is None:
        rule = CommissionRule(restaurant_id=None, commission_type=CommissionType(payload.commission_type), value=payload.value)
        db.add(rule)
    else:
        rule.commission_type = CommissionType(payload.commission_type)
        rule.value = payload.value


def _upsert_override(db: Session, payload: AdminCommissionOverrideInput) -> None:
    restaurant = db.get(Restaurant, payload.restaurant_id)
    if not restaurant:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Restaurant {payload.restaurant_id} not found")

    rule = get_restaurant_commission_rule(db, payload.restaurant_id)
    if rule is None:
        rule = CommissionRule(
            restaurant_id=payload.restaurant_id, commission_type=CommissionType(payload.commission_type), value=payload.value
        )
        db.add(rule)
    else:
        rule.commission_type = CommissionType(payload.commission_type)
        rule.value = payload.value


def _remove_override(db: Session, restaurant_id: UUID) -> None:
    rule = get_restaurant_commission_rule(db, restaurant_id)
    if rule is not None:
        db.delete(rule)


def update_admin_commission_config(db: Session, payload: AdminCommissionUpdateRequest) -> AdminCommissionConfigRead:
    if payload.default is not None:
        _upsert_default(db, payload.default)
    for override in payload.upsert_restaurant_overrides or []:
        _upsert_override(db, override)
    for restaurant_id in payload.remove_restaurant_override_ids or []:
        _remove_override(db, restaurant_id)

    db.commit()
    return get_admin_commission_config(db)
