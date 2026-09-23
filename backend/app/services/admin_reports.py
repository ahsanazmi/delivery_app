from datetime import date, datetime, time
from decimal import Decimal
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.delivery_partner import ApprovalStatus, DeliveryPartner
from app.models.order import Order, OrderStatus
from app.models.payment import Payment, PaymentProvider
from app.models.restaurant import Restaurant
from app.models.rider_earning import RiderEarning
from app.models.rider_settlement import RiderSettlement, SettlementType
from app.models.user import User, UserRole
from app.schemas.admin_reports import (
    AdminCustomersReport,
    AdminDailyAmount,
    AdminDailyCount,
    AdminOrdersReport,
    AdminOrderStatusCount,
    AdminReportsOverview,
    AdminRestaurantsReport,
    AdminRevenueReport,
    AdminRidersReport,
    AdminTopCustomer,
    AdminTopRestaurant,
    AdminTopRider,
)

_ZERO = Decimal("0.00")
TOP_N_LIMIT = 10

# An order still in a non-terminal stage — not yet delivered, cancelled, or
# rejected. Mirrors the exact grouping already used for admin_dashboard.py's
# pending_orders count.
_IN_PROGRESS_STATUSES = (
    OrderStatus.PLACED,
    OrderStatus.CONFIRMED,
    OrderStatus.PREPARING,
    OrderStatus.READY_FOR_PICKUP,
    OrderStatus.RIDER_ASSIGNED,
    OrderStatus.PICKED_UP,
    OrderStatus.OUT_FOR_DELIVERY,
)


def _range_bounds(date_from: date | None, date_to: date | None) -> tuple[datetime | None, datetime | None]:
    start = datetime.combine(date_from, time.min) if date_from else None
    end = datetime.combine(date_to, time.max) if date_to else None
    return start, end


def _apply_range(conditions: list, column, start: datetime | None, end: datetime | None) -> None:
    if start is not None:
        conditions.append(column >= start)
    if end is not None:
        conditions.append(column <= end)


def _cod_outstanding(db: Session) -> Decimal:
    """Platform-wide, current — never date-ranged (see AdminReportsOverview's
    own note on this field). Computed exactly the way the Phase 2 dashboard
    and Phase 14 COD reconciliation both already do: total COD collected
    minus total remitted, never netted against rider earnings."""
    collected = db.scalar(
        select(func.coalesce(func.sum(Payment.amount), _ZERO)).where(
            Payment.provider == PaymentProvider.COD, Payment.collected_by_rider_id.is_not(None)
        )
    ) or _ZERO
    remitted = db.scalar(
        select(func.coalesce(func.sum(RiderSettlement.amount), _ZERO)).where(
            RiderSettlement.settlement_type == SettlementType.REMITTANCE
        )
    ) or _ZERO
    return collected - remitted


def _order_financials(db: Session, start: datetime | None, end: datetime | None) -> tuple[Decimal, Decimal, Decimal]:
    """(revenue, platform_commission, restaurant_earnings) — all computed
    over DELIVERED orders only, since commission is only ever actually
    earned on a completed sale (see the schema's own note).

    Admin Portal Phase 28 — restaurant_earnings must derive from subtotal,
    never from total. Order.total includes delivery_fee, which is never
    the restaurant's money — it's credited in full to the rider as its
    own RiderEarning row (see rider_earnings.record_delivery_fee_earning).
    Deriving restaurant_earnings from total would double-count that same
    delivery_fee as belonging to both the restaurant and the rider at
    once. Commission itself is also computed on subtotal at order-creation
    time (see services.commissions.compute_effective_commission), so
    subtotal - commission is the only formula consistent with how that
    commission_amount was actually derived in the first place."""
    conditions = [Order.status == OrderStatus.DELIVERED]
    _apply_range(conditions, Order.created_at, start, end)

    row = db.execute(
        select(
            func.coalesce(func.sum(Order.total), _ZERO),
            func.coalesce(func.sum(Order.subtotal), _ZERO),
            func.coalesce(func.sum(Order.commission_amount), _ZERO),
        ).where(*conditions)
    ).one()
    revenue, subtotal, commission = row
    restaurant_earnings = subtotal - commission
    return revenue, commission, restaurant_earnings


def _rider_earnings_in_range(db: Session, start: datetime | None, end: datetime | None) -> Decimal:
    conditions = []
    _apply_range(conditions, RiderEarning.created_at, start, end)
    return db.scalar(select(func.coalesce(func.sum(RiderEarning.amount), _ZERO)).where(*conditions)) or _ZERO


def _growth_count(db: Session, model, conditions: list) -> int:
    return db.scalar(select(func.count()).select_from(model).where(*conditions)) or 0


def _growth_by_day(db: Session, created_at_column, conditions: list) -> list[AdminDailyCount]:
    rows = db.execute(
        select(func.date(created_at_column), func.count())
        .where(*conditions)
        .group_by(func.date(created_at_column))
        .order_by(func.date(created_at_column))
    ).all()
    return [AdminDailyCount(date=day, count=count) for day, count in rows]


def get_admin_reports_overview(db: Session, date_from: date | None, date_to: date | None) -> AdminReportsOverview:
    start, end = _range_bounds(date_from, date_to)

    order_conditions = []
    _apply_range(order_conditions, Order.created_at, start, end)
    total_orders = _growth_count(db, Order, order_conditions)
    completed_orders = _growth_count(db, Order, [*order_conditions, Order.status == OrderStatus.DELIVERED])
    cancelled_orders = _growth_count(db, Order, [*order_conditions, Order.status == OrderStatus.CANCELLED])

    revenue, commission, restaurant_earnings = _order_financials(db, start, end)
    rider_earnings = _rider_earnings_in_range(db, start, end)
    cod_outstanding = _cod_outstanding(db)

    customer_conditions = [User.role == UserRole.CUSTOMER]
    _apply_range(customer_conditions, User.created_at, start, end)
    restaurant_conditions: list = []
    _apply_range(restaurant_conditions, Restaurant.created_at, start, end)
    rider_conditions = [User.role == UserRole.RIDER]
    _apply_range(rider_conditions, User.created_at, start, end)

    return AdminReportsOverview(
        date_from=start,
        date_to=end,
        total_orders=total_orders,
        completed_orders=completed_orders,
        cancelled_orders=cancelled_orders,
        revenue=revenue,
        platform_commission=commission,
        restaurant_earnings=restaurant_earnings,
        rider_earnings=rider_earnings,
        cod_outstanding=cod_outstanding,
        customer_growth=_growth_count(db, User, customer_conditions),
        restaurant_growth=_growth_count(db, Restaurant, restaurant_conditions),
        rider_growth=_growth_count(db, User, rider_conditions),
    )


def get_admin_orders_report(db: Session, date_from: date | None, date_to: date | None) -> AdminOrdersReport:
    start, end = _range_bounds(date_from, date_to)
    conditions: list = []
    _apply_range(conditions, Order.created_at, start, end)

    rows = db.execute(
        select(Order.status, func.count()).where(*conditions).group_by(Order.status)
    ).all()
    counts_by_status = {status_value: count for status_value, count in rows}

    total_orders = sum(counts_by_status.values())
    completed_orders = counts_by_status.get(OrderStatus.DELIVERED, 0)
    cancelled_orders = counts_by_status.get(OrderStatus.CANCELLED, 0)
    rejected_orders = counts_by_status.get(OrderStatus.REJECTED, 0)
    in_progress_orders = sum(counts_by_status.get(s, 0) for s in _IN_PROGRESS_STATUSES)

    return AdminOrdersReport(
        date_from=start,
        date_to=end,
        total_orders=total_orders,
        completed_orders=completed_orders,
        cancelled_orders=cancelled_orders,
        rejected_orders=rejected_orders,
        in_progress_orders=in_progress_orders,
        status_breakdown=[
            AdminOrderStatusCount(status=status_value.value, count=count) for status_value, count in rows
        ],
        orders_by_day=_growth_by_day(db, Order.created_at, conditions),
    )


def get_admin_revenue_report(db: Session, date_from: date | None, date_to: date | None) -> AdminRevenueReport:
    start, end = _range_bounds(date_from, date_to)
    revenue, commission, restaurant_earnings = _order_financials(db, start, end)
    rider_earnings = _rider_earnings_in_range(db, start, end)

    conditions = [Order.status == OrderStatus.DELIVERED]
    _apply_range(conditions, Order.created_at, start, end)
    rows = db.execute(
        select(func.date(Order.created_at), func.coalesce(func.sum(Order.total), _ZERO))
        .where(*conditions)
        .group_by(func.date(Order.created_at))
        .order_by(func.date(Order.created_at))
    ).all()

    return AdminRevenueReport(
        date_from=start,
        date_to=end,
        revenue=revenue,
        platform_commission=commission,
        restaurant_earnings=restaurant_earnings,
        rider_earnings=rider_earnings,
        revenue_by_day=[AdminDailyAmount(date=day, amount=amount) for day, amount in rows],
    )


def get_admin_restaurants_report(db: Session, date_from: date | None, date_to: date | None) -> AdminRestaurantsReport:
    start, end = _range_bounds(date_from, date_to)

    total_restaurants = _growth_count(db, Restaurant, [])
    active_restaurants = _growth_count(db, Restaurant, [Restaurant.is_active.is_(True)])

    new_conditions: list = []
    _apply_range(new_conditions, Restaurant.created_at, start, end)
    new_restaurants = _growth_count(db, Restaurant, new_conditions)

    order_conditions = [Order.status == OrderStatus.DELIVERED]
    _apply_range(order_conditions, Order.created_at, start, end)
    top_rows = db.execute(
        select(Order.restaurant_id, func.count(Order.id), func.coalesce(func.sum(Order.total), _ZERO))
        .where(*order_conditions)
        .group_by(Order.restaurant_id)
        .order_by(func.coalesce(func.sum(Order.total), _ZERO).desc())
        .limit(TOP_N_LIMIT)
    ).all()

    restaurant_ids = [UUID(rid) for rid, _, _ in top_rows if rid]
    names = {r.id: r.name for r in db.scalars(select(Restaurant).where(Restaurant.id.in_(restaurant_ids)))} if restaurant_ids else {}

    top_restaurants = [
        AdminTopRestaurant(
            restaurant_id=UUID(rid), restaurant_name=names.get(UUID(rid), "Unknown restaurant"),
            order_count=order_count, revenue=revenue,
        )
        for rid, order_count, revenue in top_rows
        if rid
    ]

    return AdminRestaurantsReport(
        date_from=start,
        date_to=end,
        total_restaurants=total_restaurants,
        active_restaurants=active_restaurants,
        new_restaurants=new_restaurants,
        growth_by_day=_growth_by_day(db, Restaurant.created_at, new_conditions),
        top_restaurants=top_restaurants,
    )


def get_admin_riders_report(db: Session, date_from: date | None, date_to: date | None) -> AdminRidersReport:
    start, end = _range_bounds(date_from, date_to)

    total_riders = _growth_count(db, User, [User.role == UserRole.RIDER])
    # Same definition as the Phase 2 dashboard's own active_riders: an
    # APPROVED delivery partner, not is_online (a live toggle) and not
    # merely User.is_active (the account-level switch).
    active_riders = _growth_count(db, DeliveryPartner, [DeliveryPartner.approval_status == ApprovalStatus.APPROVED])

    new_conditions = [User.role == UserRole.RIDER]
    _apply_range(new_conditions, User.created_at, start, end)
    new_riders = _growth_count(db, User, new_conditions)

    rider_earnings = _rider_earnings_in_range(db, start, end)
    cod_outstanding = _cod_outstanding(db)

    order_conditions = [Order.status == OrderStatus.DELIVERED, Order.rider_id.is_not(None)]
    _apply_range(order_conditions, Order.created_at, start, end)
    delivery_rows = db.execute(
        select(Order.rider_id, func.count(Order.id)).where(*order_conditions).group_by(Order.rider_id)
    ).all()
    deliveries_by_rider = dict(delivery_rows)

    earning_conditions: list = []
    _apply_range(earning_conditions, RiderEarning.created_at, start, end)
    earning_rows = db.execute(
        select(RiderEarning.rider_id, func.coalesce(func.sum(RiderEarning.amount), _ZERO))
        .where(*earning_conditions)
        .group_by(RiderEarning.rider_id)
    ).all()
    earnings_by_rider = dict(earning_rows)

    top_rider_ids = sorted(earnings_by_rider, key=lambda rid: earnings_by_rider[rid], reverse=True)[:TOP_N_LIMIT]
    riders = {r.id: r.name for r in db.scalars(select(User).where(User.id.in_(top_rider_ids)))} if top_rider_ids else {}

    top_riders = [
        AdminTopRider(
            rider_id=rider_id, rider_name=riders.get(rider_id, "Unknown rider"),
            deliveries_count=deliveries_by_rider.get(rider_id, 0), earnings=earnings_by_rider[rider_id],
        )
        for rider_id in top_rider_ids
    ]

    return AdminRidersReport(
        date_from=start,
        date_to=end,
        total_riders=total_riders,
        active_riders=active_riders,
        new_riders=new_riders,
        rider_earnings=rider_earnings,
        cod_outstanding=cod_outstanding,
        growth_by_day=_growth_by_day(db, User.created_at, new_conditions),
        top_riders=top_riders,
    )


def get_admin_customers_report(db: Session, date_from: date | None, date_to: date | None) -> AdminCustomersReport:
    start, end = _range_bounds(date_from, date_to)

    total_customers = _growth_count(db, User, [User.role == UserRole.CUSTOMER])

    new_conditions = [User.role == UserRole.CUSTOMER]
    _apply_range(new_conditions, User.created_at, start, end)
    new_customers = _growth_count(db, User, new_conditions)

    order_conditions = [Order.status == OrderStatus.DELIVERED]
    _apply_range(order_conditions, Order.created_at, start, end)
    top_rows = db.execute(
        select(Order.user_id, func.count(Order.id), func.coalesce(func.sum(Order.total), _ZERO))
        .where(*order_conditions)
        .group_by(Order.user_id)
        .order_by(func.coalesce(func.sum(Order.total), _ZERO).desc())
        .limit(TOP_N_LIMIT)
    ).all()

    customer_ids = [uid for uid, _, _ in top_rows]
    names = {u.id: u.name for u in db.scalars(select(User).where(User.id.in_(customer_ids)))} if customer_ids else {}

    top_customers = [
        AdminTopCustomer(
            customer_id=uid, customer_name=names.get(uid, "Unknown customer"), order_count=order_count, total_spent=total_spent,
        )
        for uid, order_count, total_spent in top_rows
    ]

    return AdminCustomersReport(
        date_from=start,
        date_to=end,
        total_customers=total_customers,
        new_customers=new_customers,
        growth_by_day=_growth_by_day(db, User.created_at, new_conditions),
        top_customers=top_customers,
    )
