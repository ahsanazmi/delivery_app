from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.models.rider_settlement import SettlementType


class RiderSettlementRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    settlement_type: SettlementType
    amount: Decimal
    note: str | None
    created_at: datetime


class RiderWalletRead(BaseModel):
    """The rider's full financial position. Every figure is a Decimal sum
    over the underlying ledgers — never a float.

    total_cod_collected is tracked entirely separately from total_earnings
    and is SUBTRACTED, never added, when computing wallet_balance: it is
    cash the rider is physically holding on the platform's behalf (from
    Phase 16's cod-collect), not money they've earned. Treating it as
    income would double-count — the rider was already credited a
    DELIVERY_FEE earning for that same delivery.
    """

    total_earnings: Decimal
    total_cod_collected: Decimal
    total_settled: Decimal
    # The current net unsettled position: positive means the platform still
    # owes the rider this much; negative means the rider is holding more
    # COD cash than they've earned and owes the platform the difference.
    # wallet_balance and settlement_due are the same computed figure, shown
    # under both labels because the frontend spec asks for both — there is
    # no separate "eligible for settlement" concept in this phase.
    wallet_balance: Decimal
    settlement_due: Decimal
