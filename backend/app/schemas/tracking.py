from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.models.order import OrderStatus
from app.schemas.order import OrderStatusHistoryRead


class RiderInfo(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    phone: str | None


class RiderLocation(BaseModel):
    latitude: float
    longitude: float
    updated_at: datetime


class OrderTrackingResponse(BaseModel):
    order_id: UUID
    order_number: str
    order_status: OrderStatus
    assignment_status: Literal["unassigned", "assigned"]
    rider: RiderInfo | None
    rider_location: RiderLocation | None
    # The order's own delivery address coordinates — already stored on the
    # order at creation time (Phase 9), just surfaced here too so the client
    # can show a distance/"how far away" readout next to the live rider
    # position without a second request.
    delivery_latitude: float | None
    delivery_longitude: float | None
    estimated_delivery_at: datetime | None
    status_history: list[OrderStatusHistoryRead]
