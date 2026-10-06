from decimal import Decimal

from pydantic import BaseModel


class PlaceSearchResult(BaseModel):
    """Maps & Location System Phase 9 — Forward Geocoding / Address
    Search. Deliberately minimal: "do not store unnecessary third-party
    place data" — this carries only what an Address row can actually
    use (matches Address's own city/district/state/postal_code/
    latitude/longitude/formatted_address/place_id fields from Phase 2),
    not Photon's/OSM's full feature properties (osm_key, osm_value,
    extent, admin_level, etc. are all dropped here)."""

    label: str
    address_line: str | None
    city: str | None
    district: str | None
    state: str | None
    postal_code: str | None
    country: str | None
    latitude: Decimal
    longitude: Decimal
    formatted_address: str
    # Not a Google place_id — synthesized from OSM's own stable
    # (osm_type, osm_id) pair as "{osm_type}:{osm_id}", e.g. "N:765060153".
    # Same conceptual role (a stable reference to which external place
    # this came from), explicitly OSM-sourced.
    place_id: str | None


class PlaceSearchResponse(BaseModel):
    results: list[PlaceSearchResult]


class ReverseGeocodeResponse(BaseModel):
    """Maps & Location System Phase 8 — Reverse Geocoding. `result` is
    None when nothing was found at the given coordinate (open water, a
    genuinely unmapped area) — never an error; the customer can still
    fill the address in by hand either way."""

    result: PlaceSearchResult | None


class RouteResult(BaseModel):
    """Maps & Location System Phase 17 — Routes Foundation. Real
    road-network distance/duration between two points (as opposed to
    LocationService.distance_km's straight-line estimate), via a
    routing provider. distance_km/duration_minutes only — no turn-by-
    turn geometry, since nothing built so far needs it and this phase
    is explicitly a foundation, not turn-by-turn navigation."""

    distance_km: float
    duration_minutes: float


class OrderRouteResponse(BaseModel):
    """Maps & Location System Phase 20 — Restaurant → Customer Route.
    `route` is None whenever either side has no pinned coordinates, or
    OSRM found no road route between them — a legitimate negative
    result, not an error (mirrors ReverseGeocodeResponse's own `result`
    field above)."""

    route: RouteResult | None
