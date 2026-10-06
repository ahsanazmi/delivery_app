"""Maps & Location System Phase 17 — Routes Foundation.

Proxies to OSRM (Open Source Routing Machine, https://project-osrm.org),
the free/open-source equivalent to Google's Routes API — chosen for the
same reason Photon was chosen over Google Places for geocoding:
consistent with this platform's standing "no paid map service" direction,
confirmed for routing specifically before this phase was built. Called
from the backend, not directly from any client, for the same two reasons
location_search.py proxies Photon: (1) OSRM's public demo server needs no
API key, but documents a GLOBAL 1 request/second limit — proxying here
lets every request share one correctly-throttled queue; (2) it keeps the
provider swappable (OSRM_API_BASE_URL) without ever touching a client.

Deliberately does not build live tracking (a rider's continuously moving
position) — that is a separate, already-built module and explicitly out
of scope for this phase's own instruction.
"""

import logging
import threading
import time
from decimal import Decimal

import httpx

from app.core.config import settings
from app.core.ttl_cache import TTLCache
from app.schemas.location import RouteResult

logger = logging.getLogger(__name__)

_MIN_SECONDS_BETWEEN_REQUESTS = 1.1
_MAX_THROTTLE_WAIT_SECONDS = 3.0
_REQUEST_TIMEOUT_SECONDS = 5.0

_throttle_lock = threading.Lock()
_last_request_at: float = 0.0

# Maps & Location System Phase 27 — Map Billing & Quota Safety. An
# order's delivery coordinates are an immutable snapshot (Phase 12) and a
# restaurant's own location rarely changes, so a repeat route request for
# the same origin/destination pair (e.g. a restaurant owner reopening an
# order's detail view) is answered from cache rather than calling OSRM
# again. Longer-lived than the geocoding cache in location_search.py
# since these coordinates are genuinely static, not just likely-similar.
_ROUTE_CACHE_TTL_SECONDS = 1800
_route_cache: TTLCache[tuple[str, str, str, str], "RouteResult | None"] = TTLCache(ttl_seconds=_ROUTE_CACHE_TTL_SECONDS)
_ROUTE_CACHE_COORDINATE_PRECISION = 5


class RouteUnavailableError(Exception):
    """Raised when OSRM can't be reached, or the shared throttle is
    already saturated — never silently returns a stale/wrong result."""


def _wait_for_throttle_slot() -> None:
    global _last_request_at
    with _throttle_lock:
        now = time.monotonic()
        elapsed = now - _last_request_at
        wait = _MIN_SECONDS_BETWEEN_REQUESTS - elapsed
        if wait > _MAX_THROTTLE_WAIT_SECONDS:
            raise RouteUnavailableError("Route calculation is busy right now — please try again in a moment.")
        if wait > 0:
            time.sleep(wait)
        _last_request_at = time.monotonic()


def get_route(
    origin_latitude: Decimal, origin_longitude: Decimal, destination_latitude: Decimal, destination_longitude: Decimal
) -> RouteResult | None:
    """Real road-network distance/duration between origin and
    destination — the actual route a delivery would travel, as opposed
    to LocationService.distance_km's straight-line estimate. Returns
    None when OSRM has no road route between the two points (e.g. one
    of them isn't reachable by road in the underlying map data) — a
    legitimate negative result, not a failure. Raises RouteUnavailableError
    only when the provider itself can't be reached at all."""
    cache_key = (
        format(round(origin_latitude, _ROUTE_CACHE_COORDINATE_PRECISION), "f"),
        format(round(origin_longitude, _ROUTE_CACHE_COORDINATE_PRECISION), "f"),
        format(round(destination_latitude, _ROUTE_CACHE_COORDINATE_PRECISION), "f"),
        format(round(destination_longitude, _ROUTE_CACHE_COORDINATE_PRECISION), "f"),
    )
    hit, cached = _route_cache.get(cache_key)
    if hit:
        return cached

    _wait_for_throttle_slot()

    # OSRM's coordinate order is lon,lat (GeoJSON convention), separated
    # by ";" between waypoints — confirmed against the real public demo
    # server, not guessed.
    coordinates = f"{origin_longitude},{origin_latitude};{destination_longitude},{destination_latitude}"
    try:
        response = httpx.get(
            f"{settings.OSRM_API_BASE_URL}/route/v1/driving/{coordinates}",
            params={"overview": "false"},
            timeout=_REQUEST_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        body = response.json()
    except httpx.HTTPError as exc:
        logger.warning("Routing provider unreachable: %s", exc)
        raise RouteUnavailableError("Route calculation is temporarily unavailable.") from exc
    except ValueError as exc:
        # Live Rider Tracking Phase 32 — a reachable OSRM that responds
        # with a 200 but a malformed/non-JSON body is a distinct failure
        # mode from being unreachable, but must degrade the same way: the
        # caller (get_live_eta) only ever catches RouteUnavailableError, so
        # anything else raised here would otherwise escape uncaught all
        # the way up through a status-changing endpoint that has already
        # committed its own DB write — a tracking-layer failure must never
        # surface as if the actual order action had failed.
        logger.warning("Routing provider returned an unparseable response: %s", exc)
        raise RouteUnavailableError("Route calculation is temporarily unavailable.") from exc

    if not isinstance(body, dict) or body.get("code") != "Ok" or not body.get("routes"):
        _route_cache.set(cache_key, None)
        return None

    try:
        route = body["routes"][0]
        result = RouteResult(
            distance_km=round(route["distance"] / 1000, 2),
            duration_minutes=round(route["duration"] / 60, 1),
        )
    except (KeyError, TypeError, IndexError) as exc:
        logger.warning("Routing provider returned an unexpected route shape: %s", exc)
        raise RouteUnavailableError("Route calculation is temporarily unavailable.") from exc
    _route_cache.set(cache_key, result)
    return result
