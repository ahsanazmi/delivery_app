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
    # Live Rider Tracking Phase 5/19 — LIVE/STALE/OFFLINE, computed
    # server-side (rider_location.py::determine_rider_location_state) from
    # updated_at against the configured thresholds, so every client
    # renders the same freshness rule instead of each reimplementing it
    # from a raw timestamp.
    state: Literal["live", "stale", "offline"]


class OrderTrackingResponse(BaseModel):
    order_id: UUID
    order_number: str
    order_status: OrderStatus
    assignment_status: Literal["unassigned", "assigned"]
    rider: RiderInfo | None
    rider_location: RiderLocation | None
    # Live Rider Tracking Phase 17 — Customer Live Map.
    restaurant_name: str | None
    restaurant_latitude: float | None
    restaurant_longitude: float | None
    # The order's own delivery address coordinates — already stored on the
    # order at creation time (Phase 9), just surfaced here too so the client
    # can show a distance/"how far away" readout next to the live rider
    # position without a second request.
    delivery_address_line: str | None
    delivery_latitude: float | None
    delivery_longitude: float | None
    estimated_delivery_at: datetime | None
    # Live Rider Tracking Phase 22/23 — whether estimated_delivery_at is a
    # real live route-based calculation or the generic static formula.
    # "unavailable" is part of the type for parity with
    # services/eta.py::EtaSource, though build_tracking_snapshot always
    # falls back to "static" rather than actually returning it today — see
    # that module's own docstring.
    eta_source: Literal["live", "static", "unavailable"]
    status_history: list[OrderStatusHistoryRead]
