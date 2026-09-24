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
