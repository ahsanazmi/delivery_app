from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel

# Phase 19 — Reports & Analytics. Kept in its own file rather than
# app/schemas/admin.py (which every other admin phase's schemas share)
# purely because of size: six endpoints' worth of report shapes is a
# large, self-contained unit that nothing else in the admin schemas
# references. Mirrors the rider portal's own precedent of splitting
# schemas by concern (rider_wallet.py, rider_earning.py, etc. are all
# separate from a general rider.py) rather than one ever-growing file.


class AdminDailyCount(BaseModel):
    date: date
    count: int


class AdminDailyAmount(BaseModel):
    date: date
    amount: Decimal


class AdminReportsOverview(BaseModel):
    date_from: datetime | None
    date_to: datetime | None
    total_orders: int
    completed_orders: int
    cancelled_orders: int
    # Realized revenue — DELIVERED orders only, not gross order value
    # placed (that's a different, already-established metric on the
    # Phase 2 dashboard, deliberately not reused here: a report's
    # "Revenue" means money that actually changed hands).
    revenue: Decimal
    # Sum of Order.commission_amount for DELIVERED orders only — commission
    # is only ever actually earned on a completed order, never on one that
    # was later cancelled, even though a commission snapshot exists on it
    # (see Phase 17's create_order()).
    platform_commission: Decimal
    # revenue - platform_commission for the same DELIVERED order set — what
    # restaurants actually kept. An order with no commission rule applied
    # at the time (commission_amount NULL) counts as 100% restaurant
    # earnings for that order, not a hole in the total.
    restaurant_earnings: Decimal
    # Sum of RiderEarning.amount created within the range — the same
    # ledger the rider wallet and Phase 14's COD reconciliation both read.
    rider_earnings: Decimal
    # Platform-wide, current outstanding COD cash — a running balance, not
    # a period metric, so it is deliberately NOT scoped to date_from/date_to
    # (matching the Phase 2 dashboard's own pending_cod_settlement and
    # Phase 14's per-rider figures, computed the same way).
    cod_outstanding: Decimal
    customer_growth: int
    restaurant_growth: int
    rider_growth: int


class AdminOrderStatusCount(BaseModel):
    status: str
    count: int


class AdminOrdersReport(BaseModel):
    date_from: datetime | None
    date_to: datetime | None
    total_orders: int
    completed_orders: int
    cancelled_orders: int
    rejected_orders: int
    in_progress_orders: int
    status_breakdown: list[AdminOrderStatusCount]
    orders_by_day: list[AdminDailyCount]


class AdminRevenueReport(BaseModel):
    date_from: datetime | None
    date_to: datetime | None
    revenue: Decimal
    platform_commission: Decimal
    restaurant_earnings: Decimal
    rider_earnings: Decimal
    revenue_by_day: list[AdminDailyAmount]


class AdminTopRestaurant(BaseModel):
    restaurant_id: UUID
    restaurant_name: str
    order_count: int
    revenue: Decimal


class AdminRestaurantsReport(BaseModel):
    date_from: datetime | None
    date_to: datetime | None
    total_restaurants: int
    active_restaurants: int
    new_restaurants: int
    growth_by_day: list[AdminDailyCount]
    top_restaurants: list[AdminTopRestaurant]


class AdminTopRider(BaseModel):
    rider_id: UUID
    rider_name: str
    deliveries_count: int
    earnings: Decimal


class AdminRidersReport(BaseModel):
    date_from: datetime | None
    date_to: datetime | None
    total_riders: int
    active_riders: int
    new_riders: int
    rider_earnings: Decimal
    # Same platform-wide, non-date-ranged figure as the overview report.
    cod_outstanding: Decimal
    growth_by_day: list[AdminDailyCount]
    top_riders: list[AdminTopRider]


class AdminTopCustomer(BaseModel):
    customer_id: UUID
    customer_name: str
    order_count: int
    total_spent: Decimal


class AdminCustomersReport(BaseModel):
    date_from: datetime | None
    date_to: datetime | None
    total_customers: int
    new_customers: int
    growth_by_day: list[AdminDailyCount]
    top_customers: list[AdminTopCustomer]
