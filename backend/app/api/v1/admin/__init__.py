# Admin Portal subpackage for v1 APIs — one file per concern, mirroring
# app/api/v1/rider/*. Starts with dashboard.py (Phase 2); the rest of
# app/api/v1/endpoints/admin.py's routes migrate here in their own later
# phases as each gets its own dedicated frontend page.
from . import (
    audit_logs,
    categories,
    cod,
    commissions,
    coupons,
    customers,
    dashboard,
    delivery_assignments,
    notifications,
    orders,
    payments,
    reports,
    restaurant_owners,
    restaurants,
    riders,
    service_areas,
    settings,
)

__all__ = [
    "audit_logs",
    "categories",
    "cod",
    "commissions",
    "coupons",
    "customers",
    "dashboard",
    "delivery_assignments",
    "notifications",
    "orders",
    "payments",
    "reports",
    "restaurant_owners",
    "restaurants",
    "riders",
    "service_areas",
    "settings",
]
