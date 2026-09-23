import logging
from decimal import Decimal
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.cod_collection import CodCollection
from app.models.cod_settlement_allocation import CodSettlementAllocation
from app.models.order import Order
from app.models.payment import Payment, PaymentProvider
from app.models.rider_settlement import RiderSettlement, SettlementType
from app.models.user import User, UserRole
from app.schemas.admin import (
    AdminCODReconciliationDetail,
    AdminCODReconciliationListResponse,
    AdminCODReconciliationSummary,
    AdminCODSettlementAllocationRecord,
    AdminCODSettlementRecord,
    AdminCODSettlementStatus,
)
from app.services.admin_audit_log import record_admin_audit_log

logger = logging.getLogger(__name__)

_ZERO = Decimal("0.00")


def _cod_collected_by_rider(db: Session, rider_ids: list[UUID] | None = None) -> dict[UUID, Decimal]:
    """Lifetime COD cash physically collected per rider — summed straight
    from Payment (provider=COD, collected_by_rider_id set), the same single
    source of truth rider_wallet.py's own _total_cod_collected already uses,
    never a second, potentially-drifting ledger of the same fact."""
    conditions = [Payment.provider == PaymentProvider.COD, Payment.collected_by_rider_id.is_not(None)]
    if rider_ids is not None:
        conditions.append(Payment.collected_by_rider_id.in_(rider_ids))
    rows = db.execute(
        select(Payment.collected_by_rider_id, func.coalesce(func.sum(Payment.amount), _ZERO))
        .where(*conditions)
        .group_by(Payment.collected_by_rider_id)
    ).all()
    return {rider_id: amount for rider_id, amount in rows}


def _remittances_by_rider(db: Session, rider_ids: list[UUID] | None = None) -> dict[UUID, Decimal]:
    conditions = [RiderSettlement.settlement_type == SettlementType.REMITTANCE]
    if rider_ids is not None:
        conditions.append(RiderSettlement.rider_id.in_(rider_ids))
    rows = db.execute(
        select(RiderSettlement.rider_id, func.coalesce(func.sum(RiderSettlement.amount), _ZERO))
        .where(*conditions)
        .group_by(RiderSettlement.rider_id)
    ).all()
    return {rider_id: amount for rider_id, amount in rows}


def _status_for(collected: Decimal, settled: Decimal) -> AdminCODSettlementStatus:
    if settled <= _ZERO:
        return "PENDING" if collected > _ZERO else "SETTLED"
    if settled < collected:
        return "PARTIAL"
    return "SETTLED"


def _to_summary(rider: User, collected: Decimal, settled: Decimal) -> AdminCODReconciliationSummary:
    outstanding = collected - settled
    return AdminCODReconciliationSummary(
        rider_id=rider.id,
        rider_name=rider.name,
        cod_collected=collected,
        expected_settlement=collected,
        settled_amount=settled,
        outstanding_amount=outstanding,
        status=_status_for(collected, settled),
    )


def list_admin_cod_reconciliation(
    db: Session, *, search: str | None, status_filter: AdminCODSettlementStatus | None, page: int, limit: int
) -> AdminCODReconciliationListResponse:
    collected_by_rider = _cod_collected_by_rider(db)
    if not collected_by_rider:
        return AdminCODReconciliationListResponse(items=[], total=0, page=page, limit=limit)

    rider_ids = list(collected_by_rider.keys())
    settled_by_rider = _remittances_by_rider(db, rider_ids)
    riders = {rider.id: rider for rider in db.scalars(select(User).where(User.id.in_(rider_ids)))}

    summaries = [
        _to_summary(riders[rider_id], collected_by_rider[rider_id], settled_by_rider.get(rider_id, _ZERO))
        for rider_id in rider_ids
        if rider_id in riders
    ]
    if search:
        pattern = search.strip().lower()
        summaries = [s for s in summaries if pattern in s.rider_name.lower()]
    if status_filter is not None:
        summaries = [s for s in summaries if s.status == status_filter]

    summaries.sort(key=lambda s: s.outstanding_amount, reverse=True)
    total = len(summaries)
    offset = (page - 1) * limit
    return AdminCODReconciliationListResponse(items=summaries[offset : offset + limit], total=total, page=page, limit=limit)


def _get_rider_or_404(db: Session, rider_id: UUID) -> User:
    rider = db.get(User, rider_id)
    if not rider or rider.role != UserRole.RIDER:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Rider not found")
    return rider


def _allocations_by_settlement(db: Session, settlement_ids: list[UUID]) -> dict[UUID, list[AdminCODSettlementAllocationRecord]]:
    """Financial Ledger Validation (Phase 30) — for each settlement, the
    exact collected orders (and how much of each) it discharges. Joined
    against Order only for order_number's own human-readable value; every
    other field comes straight off the allocation/collection rows
    themselves."""
    if not settlement_ids:
        return {}
    rows = db.execute(
        select(
            CodSettlementAllocation.settlement_id, CodSettlementAllocation.cod_collection_id,
            CodSettlementAllocation.amount_allocated, CodCollection.order_id, CodCollection.collected_at,
            Order.order_number,
        )
        .join(CodCollection, CodCollection.id == CodSettlementAllocation.cod_collection_id)
        .join(Order, Order.id == CodCollection.order_id)
        .where(CodSettlementAllocation.settlement_id.in_(settlement_ids))
        .order_by(CodCollection.collected_at.asc())
    ).all()
    result: dict[UUID, list[AdminCODSettlementAllocationRecord]] = {}
    for settlement_id, cod_collection_id, amount_allocated, order_id, collected_at, order_number in rows:
        result.setdefault(settlement_id, []).append(
            AdminCODSettlementAllocationRecord(
                cod_collection_id=cod_collection_id, order_id=order_id, order_number=order_number,
                amount_allocated=amount_allocated, collected_at=collected_at,
            )
        )
    return result


def get_admin_cod_reconciliation_detail(db: Session, rider_id: UUID) -> AdminCODReconciliationDetail:
    rider = _get_rider_or_404(db, rider_id)
    collected = _cod_collected_by_rider(db, [rider_id]).get(rider_id, _ZERO)
    settled = _remittances_by_rider(db, [rider_id]).get(rider_id, _ZERO)
    summary = _to_summary(rider, collected, settled)

    settlements = list(
        db.scalars(
            select(RiderSettlement)
            .where(RiderSettlement.rider_id == rider_id, RiderSettlement.settlement_type == SettlementType.REMITTANCE)
            .order_by(RiderSettlement.created_at.desc())
        )
    )
    allocations_by_settlement = _allocations_by_settlement(db, [s.id for s in settlements])
    return AdminCODReconciliationDetail(
        **summary.model_dump(),
        settlements=[
            AdminCODSettlementRecord(
                id=s.id, amount=s.amount, note=s.note, created_at=s.created_at,
                allocations=allocations_by_settlement.get(s.id, []),
            )
            for s in settlements
        ],
    )


def _unallocated_collections(db: Session, rider_id: UUID) -> list[tuple[CodCollection, Decimal]]:
    """Financial Ledger Validation (Phase 30) — this rider's own
    CodCollection rows, oldest first, each paired with how much of it
    still isn't covered by any prior settlement. This is the FIFO queue
    admin_settle_cod() allocates a new settlement against: the oldest
    still-outstanding cash is settled first, mirroring how a rider would
    actually be asked to hand over cash they've been holding longest.
    Never mutates a CodCollection row itself — "how much is covered" is
    always a fresh SUM over CodSettlementAllocation, the same
    never-store-a-derived-total principle every other ledger in this
    codebase already follows."""
    collections = list(
        db.scalars(
            select(CodCollection).where(CodCollection.rider_id == rider_id).order_by(CodCollection.collected_at.asc())
        )
    )
    if not collections:
        return []
    allocated_by_collection = dict(
        db.execute(
            select(CodSettlementAllocation.cod_collection_id, func.coalesce(func.sum(CodSettlementAllocation.amount_allocated), _ZERO))
            .where(CodSettlementAllocation.cod_collection_id.in_([c.id for c in collections]))
            .group_by(CodSettlementAllocation.cod_collection_id)
        ).all()
    )
    result = []
    for collection in collections:
        remaining = collection.amount - allocated_by_collection.get(collection.id, _ZERO)
        if remaining > _ZERO:
            result.append((collection, remaining))
    return result


def admin_settle_cod(
    db: Session, admin: User, rider_id: UUID, amount: Decimal, note: str | None, ip_address: str | None = None
) -> AdminCODReconciliationDetail:
    """The only way a RiderSettlement row is ever created — always an
    INSERT into the append-only ledger, never an update to some cached
    balance column (there isn't one; every figure here is always derived
    fresh from Payment + RiderSettlement). Validates both the current state
    (this rider actually has outstanding COD) and the target state (the
    settlement can't exceed what's actually outstanding) before writing
    anything, and records who did it and why in the same admin audit log
    Phase 11 introduced.

    Database Transaction Testing (Phase 24) — live-proved that two admins
    (or one admin double-clicking) settling the same rider's COD balance at
    the same moment could both read the same `outstanding` value before
    either had written their RiderSettlement row, and both succeed —
    remitting up to double what was actually outstanding. `collected` and
    `settled` are always derived fresh from two other tables (Payment,
    RiderSettlement), so there is no single balance row a normal read
    already locks; a row lock is taken on the rider themselves instead,
    before computing anything, so a second concurrent settlement for the
    same rider blocks until the first transaction actually resolves (commit
    or rollback), then correctly recomputes against the now-reduced
    balance. Nothing else in this function commits early — unlike Phase
    16/24's original create_order bug, where an intermediate commit inside
    a nested call released a lock before the real work happened — so this
    lock is never released before the whole settlement either fully
    commits or fully rolls back."""
    rider = db.scalar(select(User).where(User.id == rider_id).with_for_update())
    if not rider or rider.role != UserRole.RIDER:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Rider not found")
    collected = _cod_collected_by_rider(db, [rider_id]).get(rider_id, _ZERO)
    settled = _remittances_by_rider(db, [rider_id]).get(rider_id, _ZERO)
    outstanding = collected - settled

    if outstanding <= _ZERO:
        # Logging & Error Handling (Phase 26) — includes the losing side of
        # the concurrent-double-settle race this same lock now prevents.
        logger.warning("COD issue: admin %s attempted to settle rider %s with no outstanding balance", admin.id, rider_id)
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="This rider has no outstanding COD balance to settle")
    if amount > outstanding:
        logger.warning(
            "COD issue: admin %s attempted to settle %s for rider %s, only %s outstanding",
            admin.id, amount, rider_id, outstanding,
        )
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Cannot settle {amount} — only {outstanding} is currently outstanding for this rider",
        )

    record_admin_audit_log(
        db,
        admin_id=admin.id,
        action="cod.settle",
        target_type="rider",
        target_id=str(rider.id),
        reason=note or "COD settlement recorded by admin",
        previous_state=str(outstanding),
        new_state=str(outstanding - amount),
        ip_address=ip_address,
    )
    settlement = RiderSettlement(rider_id=rider.id, settlement_type=SettlementType.REMITTANCE, amount=amount, note=note)
    db.add(settlement)
    # settlement.id is needed below for the allocation rows' own foreign
    # key — flush (not commit) assigns it without ending the transaction
    # this whole settlement still needs to commit or roll back atomically.
    db.flush()

    # Financial Ledger Validation (Phase 30) — this settlement's own
    # itemized trail: exactly which CodCollection row(s) it discharges,
    # oldest first, and how much of each. remaining_to_allocate always
    # reaches zero before this loop runs out of unallocated collections —
    # outstanding (validated above as >= amount) is, by construction,
    # always equal to the sum of every unallocated remainder this rider
    # has, since every collection is ledgered exactly once and every past
    # settlement was itself always fully allocated the same way.
    remaining_to_allocate = amount
    for collection, unallocated in _unallocated_collections(db, rider_id):
        if remaining_to_allocate <= _ZERO:
            break
        take = min(unallocated, remaining_to_allocate)
        db.add(CodSettlementAllocation(settlement_id=settlement.id, cod_collection_id=collection.id, amount_allocated=take))
        remaining_to_allocate -= take

    db.commit()
    return get_admin_cod_reconciliation_detail(db, rider_id)
