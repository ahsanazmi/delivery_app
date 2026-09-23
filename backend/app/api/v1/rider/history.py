from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from app.api.v1.deps import DbSession, require_rider
from app.models.order import OrderStatus
from app.models.user import User
from app.schemas.rider_delivery import RiderDeliveryDetailRead
from app.schemas.rider_history import RiderHistoryItemRead
from app.services.rider_history import get_rider_history_detail, list_rider_history

router = APIRouter()


@router.get("/history", response_model=list[RiderHistoryItemRead])
def get_rider_history(
    db: DbSession,
    status_filter: OrderStatus | None = Query(default=None, alias="status"),
    date_from: datetime | None = Query(default=None),
    date_to: datetime | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=20, ge=1, le=100),
    current_rider: User = Depends(require_rider),
) -> list[RiderHistoryItemRead]:
    offset = (page - 1) * limit
    return list_rider_history(
        db,
        current_rider,
        status_filter=status_filter,
        date_from=date_from,
        date_to=date_to,
        offset=offset,
        limit=limit,
    )


# Registered after /history above on purpose (see the identical hazard and
# fix documented in rider/deliveries.py for /deliveries/available vs
# /deliveries/{order_id}): if /history/{id} were matched first, a request to
# plain /history would fail UUID parsing instead of reaching the list above.
# There's no collision risk here since "history" itself isn't a valid UUID,
# but the registration order is kept consistent with that established
# convention regardless.
@router.get("/history/{order_id}", response_model=RiderDeliveryDetailRead)
def get_rider_history_item(
    order_id: UUID, db: DbSession, current_rider: User = Depends(require_rider)
) -> RiderDeliveryDetailRead:
    return get_rider_history_detail(db, current_rider, order_id)
