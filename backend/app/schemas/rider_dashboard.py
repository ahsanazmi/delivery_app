from decimal import Decimal

from pydantic import BaseModel

from app.schemas.order import OrderRead


class RiderDashboardResponse(BaseModel):
    is_online: bool
    today_deliveries_count: int
    completed_deliveries_count: int
    pending_deliveries_count: int
    # Derived directly from Order.delivery_fee for orders delivered today —
    # a simple, real-data-backed figure, not a full ledger. Incentives,
    # bonuses, and adjustments belong to the dedicated Earnings phase's
    # RiderEarning model, which doesn't exist yet; this will be superseded
    # by querying that table once it does.
    today_earnings: Decimal
    current_assignment: OrderRead | None
