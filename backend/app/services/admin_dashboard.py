from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.delivery_partner import ApprovalStatus, DeliveryPartner
from app.models.order import Order, OrderStatus
from app.models.payment import Payment, PaymentStatus
from app.models.restaurant import Restaurant
from app.models.rider_settlement import RiderSettlement, SettlementType
from app.models.user import User, UserRole
from app.services.admin_settings import get_platform_settings
from app.schemas.admin import (
    AdminDashboardResponse,
    AdminDashboardSummary,
    AdminOperationalAlert,
    AdminPendingApproval,
    AdminRecentOrder,
    AdminRecentRegistration,
)

_ZERO = Decimal("0.00")

# An order still in one of these stages hasn't reached a terminal outcome —
# mirrors the exact same "not done yet" grouping already used for the
# pre-existing pending_orders count, kept here for the alert below too.
_NON_TERMINAL_STATUSES = (
    OrderStatus.PLACED,
    OrderStatus.CONFIRMED,
    OrderStatus.PREPARING,
    OrderStatus.READY_FOR_PICKUP,
    OrderStatus.RIDER_ASSIGNED,
    OrderStatus.PICKED_UP,
    OrderStatus.OUT_FOR_DELIVERY,
)

# A placed order the restaurant hasn't even accepted or rejected yet, after
# this long, is a genuine operational problem worth surfacing — not just a
# normal part of the pipeline the way "preparing" or "out for delivery" is.
_STALE_UNACCEPTED_ORDER_MINUTES = 30

RECENT_ORDERS_LIMIT = 10
RECENT_REGISTRATIONS_LIMIT = 10
PENDING_APPROVALS_LIMIT = 20


def _today_start() -> datetime:
    return datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)


def _get_summary(db: Session) -> AdminDashboardSummary:
    today_start = _today_start()

    total_customers = db.scalar(select(func.count()).select_from(User).where(User.role == UserRole.CUSTOMER)) or 0
    total_restaurants = db.scalar(select(func.count()).select_from(Restaurant)) or 0
    active_restaurants = db.scalar(
        select(func.count()).select_from(Restaurant).where(Restaurant.is_active.is_(True))
    ) or 0
    total_riders = db.scalar(select(func.count()).select_from(User).where(User.role == UserRole.RIDER)) or 0
    # "Active" mirrors active_restaurants' own meaning (part of the
    # currently-usable workforce, a persistent status) rather than
    # is_online (a live, moment-to-moment toggle better suited to an
    # operational alert than a summary card) — an approved rider, whether
    # or not they happen to be online right this second.
    active_riders = db.scalar(
        select(func.count())
        .select_from(DeliveryPartner)
        .where(DeliveryPartner.approval_status == ApprovalStatus.APPROVED)
    ) or 0

    todays_orders = db.scalar(
        select(func.count()).select_from(Order).where(Order.created_at >= today_start)
    ) or 0
    # Gross order value placed today, regardless of status — a live ops
    # dashboard wants "how much order volume came in today," not a
    # payment-recognized revenue figure (that's the Reports/Payments
    # phases' job, where COD-vs-online and refunds can be broken out).
    todays_revenue = db.scalar(
        select(func.coalesce(func.sum(Order.total), _ZERO)).where(Order.created_at >= today_start)
    ) or _ZERO

    pending_orders = db.scalar(
        select(func.count()).select_from(Order).where(Order.status.in_(_NON_TERMINAL_STATUSES))
    ) or 0

    pending_rider_approvals = db.scalar(
        select(func.count())
        .select_from(DeliveryPartner)
        .where(DeliveryPartner.approval_status == ApprovalStatus.PENDING)
    ) or 0

    # Real as of Phase 4 (Restaurant.approval_status). Restaurants still
    # default to APPROVED at creation time — nothing in the normal owner
    # signup flow ever produces a PENDING one today — so this is realistically
    # 0 unless an admin has explicitly moved a restaurant back to PENDING.
    pending_restaurant_approvals = db.scalar(
        select(func.count()).select_from(Restaurant).where(Restaurant.approval_status == ApprovalStatus.PENDING)
    ) or 0

    # The cash riders are currently holding on the platform's behalf but
    # haven't yet handed back — total collected minus whatever's already
    # been remitted, across every rider, independent of any individual
    # rider's own earnings (COD collection is never netted against
    # earnings — see Phase 20's wallet design). This is the platform-wide
    # counterpart to GET /rider/wallet's own per-rider total_cod_collected
    # / total_settled figures.
    total_cod_collected = db.scalar(
        select(func.coalesce(func.sum(Payment.amount), _ZERO)).where(Payment.collected_by_rider_id.is_not(None))
    ) or _ZERO
    total_remitted = db.scalar(
        select(func.coalesce(func.sum(RiderSettlement.amount), _ZERO)).where(
            RiderSettlement.settlement_type == SettlementType.REMITTANCE
        )
    ) or _ZERO
    pending_cod_settlement = total_cod_collected - total_remitted

    return AdminDashboardSummary(
        total_customers=total_customers,
        total_restaurants=total_restaurants,
        active_restaurants=active_restaurants,
        total_riders=total_riders,
        active_riders=active_riders,
        todays_orders=todays_orders,
        todays_revenue=todays_revenue,
        pending_orders=pending_orders,
        pending_rider_approvals=pending_rider_approvals,
        pending_restaurant_approvals=pending_restaurant_approvals,
        pending_cod_settlement=pending_cod_settlement,
    )


def _get_recent_orders(db: Session) -> list[AdminRecentOrder]:
    orders = db.scalars(select(Order).order_by(Order.created_at.desc()).limit(RECENT_ORDERS_LIMIT))
    return [
        AdminRecentOrder(
            id=order.id,
            order_number=order.order_number,
            restaurant_name=order.restaurant_name,
            customer_name=order.customer_name,
            status=order.status,
            total=order.total,
            created_at=order.created_at,
        )
        for order in orders
    ]


def _get_recent_registrations(db: Session) -> list[AdminRecentRegistration]:
    # Every role — a platform admin wants to see new signups across the
    # board (a new restaurant owner is just as relevant here as a new
    # rider application), not just one role at a time.
    users = db.scalars(select(User).order_by(User.created_at.desc()).limit(RECENT_REGISTRATIONS_LIMIT))
    return [
        AdminRecentRegistration(id=user.id, name=user.name, role=user.role, created_at=user.created_at)
        for user in users
    ]


def _get_pending_approvals(db: Session) -> list[AdminPendingApproval]:
    # Riders only, for now — see pending_restaurant_approvals above for why
    # there's no restaurant counterpart to list here yet.
    rows = db.execute(
        select(User.id, User.name, User.email, DeliveryPartner.created_at)
        .join(DeliveryPartner, DeliveryPartner.user_id == User.id)
        .where(DeliveryPartner.approval_status == ApprovalStatus.PENDING)
        .order_by(DeliveryPartner.created_at.asc())
        .limit(PENDING_APPROVALS_LIMIT)
    ).all()
    return [
        AdminPendingApproval(id=user_id, name=name, email=email, type="rider", submitted_at=submitted_at)
        for user_id, name, email, submitted_at in rows
    ]


# Admin Portal Phase 24 — every alert category the phase brief names, each
# with a "link" the frontend renders as a clickable navigation target
# straight to the relevant admin section. Ordered roughly by urgency
# (critical system issues first, informational counts last).
def _get_alerts(db: Session, summary: AdminDashboardSummary) -> list[AdminOperationalAlert]:
    alerts: list[AdminOperationalAlert] = []
    today_start = _today_start()

    # System issues — currently just maintenance mode (Phase 22), the one
    # platform-wide "something is deliberately turned off" switch that
    # exists today. Not a fabricated, permanently-empty counter.
    if get_platform_settings(db).maintenance_mode:
        alerts.append(
            AdminOperationalAlert(
                severity="critical",
                message="Maintenance mode is ON — new orders are currently blocked platform-wide",
                count=1,
                link="/settings",
            )
        )

    stale_cutoff = datetime.now(UTC) - timedelta(minutes=_STALE_UNACCEPTED_ORDER_MINUTES)
    stale_unaccepted = db.scalar(
        select(func.count())
        .select_from(Order)
        .where(Order.status == OrderStatus.PLACED, Order.created_at < stale_cutoff)
    ) or 0
    if stale_unaccepted:
        alerts.append(
            AdminOperationalAlert(
                severity="warning",
                message=f"{stale_unaccepted} order(s) still awaiting restaurant acceptance after "
                f"{_STALE_UNACCEPTED_ORDER_MINUTES}+ minutes",
                count=stale_unaccepted,
                link="/orders?status=placed",
            )
        )

    failed_payments_today = db.scalar(
        select(func.count())
        .select_from(Payment)
        .where(Payment.payment_status == PaymentStatus.FAILED, Payment.updated_at >= today_start)
    ) or 0
    if failed_payments_today:
        alerts.append(
            AdminOperationalAlert(
                severity="warning",
                message=f"{failed_payments_today} payment(s) failed today",
                count=failed_payments_today,
                link="/payments?status=FAILED",
            )
        )

    cancelled_orders_today = db.scalar(
        select(func.count())
        .select_from(Order)
        .where(Order.status == OrderStatus.CANCELLED, Order.created_at >= today_start)
    ) or 0
    if cancelled_orders_today:
        alerts.append(
            AdminOperationalAlert(
                severity="warning",
                message=f"{cancelled_orders_today} order(s) cancelled today",
                count=cancelled_orders_today,
                link="/orders?status=cancelled",
            )
        )

    suspended_riders = db.scalar(
        select(func.count())
        .select_from(DeliveryPartner)
        .where(DeliveryPartner.approval_status == ApprovalStatus.SUSPENDED)
    ) or 0
    if suspended_riders:
        alerts.append(
            AdminOperationalAlert(
                severity="info",
                message=f"{suspended_riders} rider(s) currently suspended",
                count=suspended_riders,
                link="/riders?approval_status=SUSPENDED",
            )
        )

    if summary.pending_rider_approvals:
        alerts.append(
            AdminOperationalAlert(
                severity="info",
                message=f"{summary.pending_rider_approvals} rider application(s) awaiting review",
                count=summary.pending_rider_approvals,
                link="/riders?approval_status=PENDING",
            )
        )

    if summary.pending_restaurant_approvals:
        alerts.append(
            AdminOperationalAlert(
                severity="info",
                message=f"{summary.pending_restaurant_approvals} restaurant(s) awaiting approval",
                count=summary.pending_restaurant_approvals,
                link="/restaurants?approval_status=PENDING",
            )
        )

    if summary.pending_cod_settlement > _ZERO:
        alerts.append(
            AdminOperationalAlert(
                severity="warning",
                message=f"₹{summary.pending_cod_settlement} in COD cash not yet remitted by riders",
                count=1,
                link="/cod",
            )
        )

    if summary.todays_orders:
        alerts.append(
            AdminOperationalAlert(
                severity="info",
                message=f"{summary.todays_orders} new order(s) placed today",
                count=summary.todays_orders,
                link="/orders",
            )
        )

    return alerts


def get_admin_dashboard(db: Session) -> AdminDashboardResponse:
    summary = _get_summary(db)
    return AdminDashboardResponse(
        summary=summary,
        recent_orders=_get_recent_orders(db),
        recent_registrations=_get_recent_registrations(db),
        pending_approvals=_get_pending_approvals(db),
        alerts=_get_alerts(db, summary),
    )
