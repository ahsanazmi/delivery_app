from datetime import date

from fastapi import APIRouter, Depends, Query

from app.api.v1.deps import DbSession, require_admin
from app.models.user import User
from app.schemas.admin_reports import (
    AdminCustomersReport,
    AdminOrdersReport,
    AdminReportsOverview,
    AdminRestaurantsReport,
    AdminRevenueReport,
    AdminRidersReport,
)
from app.services.admin_reports import (
    get_admin_customers_report,
    get_admin_orders_report,
    get_admin_reports_overview,
    get_admin_restaurants_report,
    get_admin_revenue_report,
    get_admin_riders_report,
)

router = APIRouter()

# Every report below takes the same optional date_from/date_to (a date, not
# a datetime — the range is inclusive of both whole days). Omitting both
# means "all time," not an error — there is no hidden default window.


@router.get("/reports/overview", response_model=AdminReportsOverview)
def get_reports_overview(
    db: DbSession,
    date_from: date | None = Query(default=None),
    date_to: date | None = Query(default=None),
    current_admin: User = Depends(require_admin),
) -> AdminReportsOverview:
    return get_admin_reports_overview(db, date_from, date_to)


@router.get("/reports/orders", response_model=AdminOrdersReport)
def get_reports_orders(
    db: DbSession,
    date_from: date | None = Query(default=None),
    date_to: date | None = Query(default=None),
    current_admin: User = Depends(require_admin),
) -> AdminOrdersReport:
    return get_admin_orders_report(db, date_from, date_to)


@router.get("/reports/revenue", response_model=AdminRevenueReport)
def get_reports_revenue(
    db: DbSession,
    date_from: date | None = Query(default=None),
    date_to: date | None = Query(default=None),
    current_admin: User = Depends(require_admin),
) -> AdminRevenueReport:
    return get_admin_revenue_report(db, date_from, date_to)


@router.get("/reports/restaurants", response_model=AdminRestaurantsReport)
def get_reports_restaurants(
    db: DbSession,
    date_from: date | None = Query(default=None),
    date_to: date | None = Query(default=None),
    current_admin: User = Depends(require_admin),
) -> AdminRestaurantsReport:
    return get_admin_restaurants_report(db, date_from, date_to)


@router.get("/reports/riders", response_model=AdminRidersReport)
def get_reports_riders(
    db: DbSession,
    date_from: date | None = Query(default=None),
    date_to: date | None = Query(default=None),
    current_admin: User = Depends(require_admin),
) -> AdminRidersReport:
    return get_admin_riders_report(db, date_from, date_to)


@router.get("/reports/customers", response_model=AdminCustomersReport)
def get_reports_customers(
    db: DbSession,
    date_from: date | None = Query(default=None),
    date_to: date | None = Query(default=None),
    current_admin: User = Depends(require_admin),
) -> AdminCustomersReport:
    return get_admin_customers_report(db, date_from, date_to)
