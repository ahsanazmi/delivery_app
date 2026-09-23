from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.models.rider_earning import EarningType


class RiderEarningRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    order_id: UUID | None
    earning_type: EarningType
    amount: Decimal
    description: str | None
    created_at: datetime


class EarningsBreakdown(BaseModel):
    """Every field is a Decimal sum over rider_earnings rows for the period
    — never a float, per the phase's own requirement."""

    delivery_fee: Decimal
    incentive: Decimal
    bonus: Decimal
    adjustment: Decimal
    total: Decimal


class RiderEarningsSummaryRead(BaseModel):
    today: EarningsBreakdown
    # Rolling 7-day window ending today (not the calendar week) — avoids
    # Monday-vs-Sunday ambiguity and stays correct regardless of what day of
    # the week "today" happens to be.
    week: EarningsBreakdown
    # Rolling 30-day window ending today, for the same reason — avoids
    # calendar-month edge cases (28 vs 31 days, mid-month signup, etc.).
    month: EarningsBreakdown
    # Lifetime, not scoped to any of the above windows.
    total_deliveries: int
    average_earning: Decimal
