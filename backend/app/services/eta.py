"""Live Rider Tracking Phases 22–24 — Live ETA / ETA Staleness / Route
Refresh Strategy.

Computes a real ETA from the rider's current position to the order's
delivery location, via the already-built OSRM-backed routing service
(location_service.route(), Maps & Location System Phase 17) — never a new
routing integration. Deliberately reuses the "current rider position ->
customer destination" framing this phase's own text gives, rather than
modeling the restaurant-then-customer two-leg trip explicitly; a
documented simplification, not an oversight (see
docs/live-tracking-architecture.md §10).

The refresh strategy (Phase 24) is the entire point of this module: a
route is only recalculated once the rider has moved far enough, or enough
time has passed, or the order's status has moved on to a different leg of
the trip — never on every GPS ping, to protect the shared, rate-limited
OSRM instance the same way the geocoding/routing caches (Maps & Location
System Phase 27) already protect Photon/OSRM elsewhere in this codebase.
This is a separate, purpose-built cache from that TTLCache (an ETA needs
"stale until something changes" semantics, not a fixed expiry), but the
same underlying discipline.
"""

import logging
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Literal
from uuid import UUID

from app.core.config import settings
from app.core.observability import log_event
from app.models.order import Order, OrderStatus
from app.services import location_service
from app.services.routing import RouteUnavailableError

logger = logging.getLogger(__name__)

EtaSource = Literal["live", "static", "unavailable"]


class _CachedEta:
    __slots__ = ("estimated_delivery_at", "computed_at", "rider_latitude", "rider_longitude", "order_status")

    def __init__(
        self,
        estimated_delivery_at: datetime,
        computed_at: datetime,
        rider_latitude: Decimal,
        rider_longitude: Decimal,
        order_status: OrderStatus,
    ) -> None:
        self.estimated_delivery_at = estimated_delivery_at
        self.computed_at = computed_at
        self.rider_latitude = rider_latitude
        self.rider_longitude = rider_longitude
        self.order_status = order_status


# Module-level, in-process — mirrors the same "latest value, not a durable
# ledger" discipline already applied to rider location itself (Phase 5).
# An ETA is inherently a live, recomputed value; losing this cache on a
# server restart just means the next request recomputes it fresh, which is
# harmless. Entries are evicted explicitly (clear_eta_cache) once an order
# leaves the trackable window, so this never grows unbounded.
_eta_cache: dict[UUID, _CachedEta] = {}


def clear_eta_cache(order_id: UUID) -> None:
    _eta_cache.pop(order_id, None)


def _needs_refresh(cached: _CachedEta | None, rider_latitude: Decimal, rider_longitude: Decimal, order_status: OrderStatus, now: datetime) -> bool:
    if cached is None:
        return True
    # A different leg of the trip (e.g. RIDER_ASSIGNED -> PICKED_UP) means
    # the trip's own dynamics changed even if the rider hasn't moved yet.
    if cached.order_status != order_status:
        return True
    elapsed_seconds = (now - cached.computed_at).total_seconds()
    if elapsed_seconds >= settings.LIVE_ETA_MIN_REFRESH_SECONDS:
        return True
    moved_km = location_service.distance_km(cached.rider_latitude, cached.rider_longitude, rider_latitude, rider_longitude)
    return (moved_km * 1000) >= settings.LIVE_ETA_MIN_MOVEMENT_METERS


def get_live_eta(order: Order, rider_latitude: Decimal, rider_longitude: Decimal) -> tuple[datetime | None, EtaSource]:
    """Returns (estimated_delivery_at, source). source is "live" whenever
    a real (fresh or cached-still-valid) route-based estimate is
    available, "unavailable" only when no estimate — live or previously
    cached — exists at all (the routing provider has never successfully
    answered for this order). Never raises — a routing failure degrades
    to the last good cached value, or to "unavailable," never an error
    that would break the rest of the tracking snapshot."""
    now = datetime.now(UTC)
    cached = _eta_cache.get(order.id)

    if not _needs_refresh(cached, rider_latitude, rider_longitude, order.status, now):
        return cached.estimated_delivery_at, "live"  # type: ignore[union-attr]

    if order.latitude is None or order.longitude is None:
        return (cached.estimated_delivery_at, "live") if cached else (None, "unavailable")

    try:
        route = location_service.route(rider_latitude, rider_longitude, order.latitude, order.longitude)
    except RouteUnavailableError:
        return (cached.estimated_delivery_at, "live") if cached else (None, "unavailable")

    if route is None:
        return (cached.estimated_delivery_at, "live") if cached else (None, "unavailable")

    estimated_delivery_at = now + timedelta(minutes=route.duration_minutes)
    _eta_cache[order.id] = _CachedEta(estimated_delivery_at, now, rider_latitude, rider_longitude, order.status)
    # Live Rider Tracking Phase 39 — Observability. Logged only on an
    # actual fresh computation (this line), never on a cache-hit reuse
    # above — otherwise this would fire on every GPS ping, not just the
    # ones that actually triggered a route recalculation.
    log_event(logger, "eta_refresh", order_id=order.id, duration_minutes=route.duration_minutes)
    return estimated_delivery_at, "live"
