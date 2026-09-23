from datetime import UTC, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.order import Order
from app.models.rider_earning import EarningType, RiderEarning
from app.models.user import User
from app.schemas.rider_earning import EarningsBreakdown, RiderEarningRead, RiderEarningsSummaryRead

_ZERO = Decimal("0.00")


def record_delivery_fee_earning(db: Session, rider_id: UUID, order: Order) -> RiderEarning:
    """Credits the rider for a completed delivery. Called once, from
    complete_delivery() in rider_deliveries.py, as part of the same
    transaction that moves the order to DELIVERED — never independently, so
    an earning row can't exist without the delivery that produced it (or
    vice versa). Not committed here; the caller commits both together."""
    earning = RiderEarning(
        rider_id=rider_id,
        order_id=order.id,
        earning_type=EarningType.DELIVERY_FEE,
        amount=order.delivery_fee,
    )
    db.add(earning)
    return earning


def list_rider_earnings(db: Session, rider: User, *, offset: int = 0, limit: int = 50) -> list[RiderEarningRead]:
    # Phase 30: this ledger only ever grows for as long as a rider stays
    # active — a tenured rider could have thousands of rows. Bounded with
    # the same offset/limit shape as list_rider_history, defaulting to the
    # most recent 50 rather than returning every row ever on every call.
    earnings = db.scalars(
        select(RiderEarning)
        .where(RiderEarning.rider_id == rider.id)
        .order_by(RiderEarning.created_at.desc())
        .offset(offset)
        .limit(limit)
    )
    return [RiderEarningRead.model_validate(earning) for earning in earnings]


def _day_start(days_ago: int = 0) -> datetime:
    return datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=days_ago)


def _breakdown_since(db: Session, rider_id: UUID, since: datetime) -> EarningsBreakdown:
    rows = db.execute(
        select(RiderEarning.earning_type, func.coalesce(func.sum(RiderEarning.amount), _ZERO))
        .where(RiderEarning.rider_id == rider_id, RiderEarning.created_at >= since)
        .group_by(RiderEarning.earning_type)
    ).all()
    totals: dict[EarningType, Decimal] = {earning_type: _ZERO for earning_type in EarningType}
    for earning_type, amount in rows:
        totals[earning_type] = amount

    return EarningsBreakdown(
        delivery_fee=totals[EarningType.DELIVERY_FEE],
        incentive=totals[EarningType.INCENTIVE],
        bonus=totals[EarningType.BONUS],
        adjustment=totals[EarningType.ADJUSTMENT],
        total=sum(totals.values(), _ZERO),
    )


def get_rider_earnings_summary(db: Session, rider: User) -> RiderEarningsSummaryRead:
    today = _breakdown_since(db, rider.id, _day_start())
    week = _breakdown_since(db, rider.id, _day_start(6))
    month = _breakdown_since(db, rider.id, _day_start(29))

    # Lifetime, independent of the rolling windows above — one row per
    # completed delivery, so counting DELIVERY_FEE earnings is exactly
    # "how many deliveries has this rider ever completed."
    total_deliveries = db.scalar(
        select(func.count())
        .select_from(RiderEarning)
        .where(RiderEarning.rider_id == rider.id, RiderEarning.earning_type == EarningType.DELIVERY_FEE)
    ) or 0

    lifetime_total = db.scalar(
        select(func.coalesce(func.sum(RiderEarning.amount), _ZERO)).where(RiderEarning.rider_id == rider.id)
    ) or _ZERO

    average_earning = (
        (lifetime_total / total_deliveries).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        if total_deliveries
        else _ZERO
    )

    return RiderEarningsSummaryRead(
        today=today,
        week=week,
        month=month,
        total_deliveries=total_deliveries,
        average_earning=average_earning,
    )
