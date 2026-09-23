from fastapi import APIRouter, Depends

from app.api.v1.deps import DbSession, require_admin
from app.models.user import User
from app.schemas.notification import PromotionalBroadcastCreate, PromotionalBroadcastResult
from app.services.notifications import broadcast_promotion

router = APIRouter()

# GET /dashboard moved to app/api/v1/admin/dashboard.py (Phase 2) — the
# start of migrating this legacy monolithic file into the same per-concern
# package structure the Rider Portal already uses (app/api/v1/rider/*).
# Everything below is still here pending its own phase to migrate.


# GET/{id}/PATCH /customers moved to app/api/v1/admin/customers.py (Phase 3).


# GET/{id}/PATCH /restaurants moved to app/api/v1/admin/restaurants.py (Phase 4).


# GET /riders, PATCH /riders/{id}/verification, PATCH
# /riders/{id}/documents/{id} moved to app/api/v1/admin/riders.py (Phase 7).


# GET/{id} /orders, PATCH /orders/{id}/assign-rider, PATCH /orders/{id}/status
# moved to app/api/v1/admin/orders.py (Phase 10).


@router.post("/notifications/broadcast", response_model=PromotionalBroadcastResult)
def broadcast_notification(
    payload: PromotionalBroadcastCreate, db: DbSession, current_admin: User = Depends(require_admin)
) -> PromotionalBroadcastResult:
    notified = broadcast_promotion(db, payload.title, payload.body)
    return PromotionalBroadcastResult(notified_customers=notified)
