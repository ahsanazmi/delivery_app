"""Maps & Location System Phase 8/9 — Reverse Geocoding and Forward
Geocoding / Address Search.

Proxies to Photon (https://github.com/komoot/photon), an open-source
geocoder built on OpenStreetMap data — its forward-search endpoint is
purpose-built for "as-you-type" place suggestions (unlike raw Nominatim,
a general-purpose geocoder), and its reverse endpoint is the real
geocoding service behind "what address is at this coordinate" (Phase 8's
own instruction: "do not trust arbitrary client-provided formatted
addresses when coordinates are available" — this is the actual lookup
that makes that possible, run here, not fabricated on the client).
Called from the backend, not directly from customer-mobile, for two
reasons: (1) Photon needs no API key at all, so there's no credential to
keep off the client, but komoot's public instance has a documented,
GLOBAL 1 request/second fair-use limit — proxying through one backend
process lets every customer's forward AND reverse calls share a single,
correctly-throttled queue instead of each device hammering it
independently; (2) it keeps the provider swappable (PHOTON_API_BASE_URL)
without ever touching customer-mobile.
"""

import logging
import threading
import time
from decimal import Decimal

import httpx

from app.core.config import settings
from app.schemas.location import PlaceSearchResult

logger = logging.getLogger(__name__)

# A small safety margin over Photon's own documented 1 req/s limit.
_MIN_SECONDS_BETWEEN_REQUESTS = 1.1
# Never hold a customer's request open indefinitely waiting for the
# throttle to clear — an honest "try again" beats a very slow response.
_MAX_THROTTLE_WAIT_SECONDS = 3.0
_REQUEST_TIMEOUT_SECONDS = 5.0

_throttle_lock = threading.Lock()
_last_request_at: float = 0.0


class PlaceSearchUnavailableError(Exception):
    """Raised when Photon can't be reached, or the shared throttle is
    already saturated — never silently returns a stale/wrong result."""


def _wait_for_throttle_slot() -> None:
    global _last_request_at
    with _throttle_lock:
        now = time.monotonic()
        elapsed = now - _last_request_at
        wait = _MIN_SECONDS_BETWEEN_REQUESTS - elapsed
        if wait > _MAX_THROTTLE_WAIT_SECONDS:
            raise PlaceSearchUnavailableError("Address search is busy right now — please try again in a moment.")
        if wait > 0:
            time.sleep(wait)
        _last_request_at = time.monotonic()


def _osm_place_id(feature: dict) -> str | None:
    properties = feature.get("properties", {})
    osm_type = properties.get("osm_type")
    osm_id = properties.get("osm_id")
    if osm_type and osm_id:
        return f"{osm_type}:{osm_id}"
    return None


def _to_result(feature: dict) -> PlaceSearchResult | None:
    geometry = feature.get("geometry") or {}
    coordinates = geometry.get("coordinates")
    if not coordinates or len(coordinates) != 2:
        return None
    longitude, latitude = coordinates

    properties = feature.get("properties", {})
    name = properties.get("name")
    if not name:
        return None

    street = properties.get("street")
    housenumber = properties.get("housenumber")
    address_line = f"{housenumber} {street}".strip() if street else None

    explicit_city = properties.get("city")
    county = properties.get("county")
    city = explicit_city or county
    # Only a genuinely finer-grained city distinct from its county counts
    # as a district — e.g. "Some Village" within Azamgarh district. When
    # there's no explicit city at all, `city` above already fell back to
    # the county itself, so there's no separate, more specific place left
    # to call the district.
    district = county if (explicit_city and county and explicit_city != county) else None
    state = properties.get("state")
    postal_code = properties.get("postcode")
    country = properties.get("country")

    # Dedupe (e.g. name == city for a city-level result, so "Azamgarh,
    # Azamgarh, Uttar Pradesh" would otherwise repeat itself).
    seen: set[str] = set()
    deduped = []
    for part in [name, city, state]:
        if part and part not in seen:
            deduped.append(part)
            seen.add(part)
    label = ", ".join(deduped)

    return PlaceSearchResult(
        label=label,
        address_line=address_line,
        city=city,
        district=district,
        state=state,
        postal_code=postal_code,
        country=country,
        latitude=Decimal(str(latitude)),
        longitude=Decimal(str(longitude)),
        formatted_address=label,
        place_id=_osm_place_id(feature),
    )


def _call_photon(path: str, params: dict) -> dict:
    """Shared HTTP call for both forward and reverse geocoding — same
    throttle, same timeout, same error handling, since both hit the
    same rate-limited instance."""
    _wait_for_throttle_slot()
    try:
        response = httpx.get(
            f"{settings.PHOTON_API_BASE_URL}{path}",
            params=params,
            timeout=_REQUEST_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        return response.json()
    except httpx.HTTPError as exc:
        logger.warning("Geocoding provider unreachable (%s): %s", path, exc)
        raise PlaceSearchUnavailableError("Address search is temporarily unavailable.") from exc


def search_places(query: str, *, limit: int = 6) -> list[PlaceSearchResult]:
    query = query.strip()
    if len(query) < 2:
        return []

    body = _call_photon("/api/", {"q": query, "limit": limit})

    results = []
    for feature in body.get("features", []):
        result = _to_result(feature)
        if result is not None:
            results.append(result)
    return results


def reverse_geocode(latitude: Decimal, longitude: Decimal) -> PlaceSearchResult | None:
    """Maps & Location System Phase 8 — the backend's own authoritative
    answer to "what address is at this coordinate," used when a customer
    confirms a point on the map picker. Never returns something the
    client supplied itself; either a real Photon-derived result, or
    None if nothing was found there (a customer can still fill the
    address in by hand either way — this never blocks saving)."""
    body = _call_photon("/reverse", {"lat": str(latitude), "lon": str(longitude)})

    features = body.get("features", [])
    if not features:
        return None
    return _to_result(features[0])
