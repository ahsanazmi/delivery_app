from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.payment import Payment, PaymentProvider
from app.models.rider_earning import RiderEarning
from app.models.rider_settlement import RiderSettlement, SettlementType
from app.models.user import User
from app.schemas.rider_wallet import RiderSettlementRead, RiderWalletRead

_ZERO = Decimal("0.00")


def _total_earnings(db: Session, rider_id) -> Decimal:
    return db.scalar(
        select(func.coalesce(func.sum(RiderEarning.amount), _ZERO)).where(RiderEarning.rider_id == rider_id)
    ) or _ZERO


def _total_cod_collected(db: Session, rider_id) -> Decimal:
    """Cash the rider has physically collected on the platform's behalf
    (Phase 16) — a liability the rider owes back, never rider income. Summed
    straight from Payment rather than a duplicate ledger, since Payment
    already records exactly this (provider=COD, collected_by_rider_id,
    collected_at) and there's no reason to maintain two sources of truth for
    the same fact."""
    return db.scalar(
        select(func.coalesce(func.sum(Payment.amount), _ZERO)).where(
            Payment.collected_by_rider_id == rider_id, Payment.provider == PaymentProvider.COD
        )
    ) or _ZERO


def _settlement_totals(db: Session, rider_id) -> tuple[Decimal, Decimal]:
    """Returns (total_payouts, total_remittances) — both non-negative."""
    rows = db.execute(
        select(RiderSettlement.settlement_type, func.coalesce(func.sum(RiderSettlement.amount), _ZERO))
        .where(RiderSettlement.rider_id == rider_id)
        .group_by(RiderSettlement.settlement_type)
    ).all()
    totals = {settlement_type: _ZERO for settlement_type in SettlementType}
    for settlement_type, amount in rows:
        totals[settlement_type] = amount
    return totals[SettlementType.PAYOUT], totals[SettlementType.REMITTANCE]


def get_rider_wallet(db: Session, rider: User) -> RiderWalletRead:
    total_earnings = _total_earnings(db, rider.id)
    total_cod_collected = _total_cod_collected(db, rider.id)
    total_payouts, total_remittances = _settlement_totals(db, rider.id)

    # A PAYOUT (platform -> rider) pays down what the platform owes, so it
    # subtracts from the balance. A REMITTANCE (rider -> platform) pays down
    # the rider's COD debt, so it adds back toward zero/positive.
    wallet_balance = total_earnings - total_cod_collected - total_payouts + total_remittances
    total_settled = total_payouts + total_remittances

    return RiderWalletRead(
        total_earnings=total_earnings,
        total_cod_collected=total_cod_collected,
        total_settled=total_settled,
        wallet_balance=wallet_balance,
        settlement_due=wallet_balance,
    )


def list_rider_settlements(db: Session, rider: User, *, offset: int = 0, limit: int = 50) -> list[RiderSettlementRead]:
    # Phase 30: bounded for the same reason as list_rider_earnings — an
    # append-only ledger with no cap on how long a rider stays active.
    settlements = db.scalars(
        select(RiderSettlement)
        .where(RiderSettlement.rider_id == rider.id)
        .order_by(RiderSettlement.created_at.desc())
        .offset(offset)
        .limit(limit)
    )
    return [RiderSettlementRead.model_validate(settlement) for settlement in settlements]
