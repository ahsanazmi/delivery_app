from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel

from app.models.order import OrderStatus


class RiderHistoryItemRead(BaseModel):
    """One row in the rider's delivery history list — deliberately lighter
    than RiderDeliveryDetailRead (Phase 11/15): just enough to render the
    history list (order, restaurant, date, status, earning, payment method),
    not the full customer-contact detail, which is what GET
    /rider/history/{id} is for."""

    order_id: UUID
    order_number: str
    restaurant_name: str
    # The order's own updated_at — bumped on every status transition, so for
    # a terminal (DELIVERED/CANCELLED) order this is effectively "when the
    # delivery concluded," which is what "Today / Yesterday / Previous
    # Deliveries" grouping on the frontend buckets by.
    date: datetime
    status: OrderStatus
    # Same simple proxy used everywhere else in the rider portal
    # (dashboard's today_earnings, Phase 9's estimated_earning) — the order's
    # delivery_fee, not a real earnings-ledger figure.
    earning: Decimal
    payment_method: str
