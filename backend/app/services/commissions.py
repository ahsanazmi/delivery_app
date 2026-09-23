from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.commission_rule import CommissionRule, CommissionType

_ZERO = Decimal("0.00")
_CENT = Decimal("0.01")


@dataclass(frozen=True)
class EffectiveCommission:
    commission_type: CommissionType
    rate: Decimal
    amount: Decimal


def get_default_commission_rule(db: Session) -> CommissionRule | None:
    return db.scalar(select(CommissionRule).where(CommissionRule.restaurant_id.is_(None)))


def get_restaurant_commission_rule(db: Session, restaurant_id: UUID) -> CommissionRule | None:
    return db.scalar(select(CommissionRule).where(CommissionRule.restaurant_id == restaurant_id))


def compute_effective_commission(db: Session, restaurant_id: UUID, subtotal: Decimal) -> EffectiveCommission | None:
    """The rule actually charged for one order, computed fresh from
    whatever rules exist *right now* — restaurant-specific override first,
    platform default otherwise, or nothing at all if neither is configured.

    This is only ever called from create_order() at the moment an order is
    placed; the caller is responsible for snapshotting the result onto the
    order immediately. Nothing else in this codebase calls this for an
    order that already exists — that's precisely what would violate "do
    not retroactively change historical order financial calculations."
    """
    rule = get_restaurant_commission_rule(db, restaurant_id) or get_default_commission_rule(db)
    if rule is None:
        return None

    if rule.commission_type == CommissionType.PERCENTAGE:
        # Charged on the food subtotal only — delivery fee goes to the
        # rider and tax is a pass-through, neither is platform revenue.
        amount = (subtotal * rule.value / Decimal("100")).quantize(_CENT, rounding=ROUND_HALF_UP)
    else:
        amount = rule.value

    return EffectiveCommission(commission_type=rule.commission_type, rate=rule.value, amount=amount)
