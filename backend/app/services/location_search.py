"""Maps & Location System Phase 9 — Forward Geocoding / Address Search.

Proxies to Photon (https://github.com/komoot/photon), an open-source
geocoder built on OpenStreetMap data, purpose-built for exactly this
"as-you-type" place-suggestion UX (unlike raw Nominatim, which is a
general-purpose geocoder). Called from the backend, not directly from
customer-mobile, for two reasons: (1) Photon needs no API key at all,
so there's no credential to keep off the client, but komoot's public
instance has a documented, GLOBAL 1 request/second fair-use limit —
proxying through one backend process lets every customer's searches
share a single, correctly-throttled queue instead of each device
hammering it independently; (2) it keeps the provider swappable
(PHOTON_API_BASE_URL) without ever touching customer-mobile.
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


def search_places(query: str, *, limit: int = 6) -> list[PlaceSearchResult]:
    query = query.strip()
    if len(query) < 2:
        return []

    _wait_for_throttle_slot()

    try:
        response = httpx.get(
            f"{settings.PHOTON_API_BASE_URL}/",
            params={"q": query, "limit": limit},
            timeout=_REQUEST_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        body = response.json()
    except httpx.HTTPError as exc:
        logger.warning("Place search provider unreachable: %s", exc)
        raise PlaceSearchUnavailableError("Address search is temporarily unavailable.") from exc

    results = []
    for feature in body.get("features", []):
        result = _to_result(feature)
        if result is not None:
            results.append(result)
    return results
