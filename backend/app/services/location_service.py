"""Maps & Location System Phase 16 — Distance Calculation. Extended by
Phase 17 (Routes Foundation) with route().

A single backend home for this platform's location primitives:

    LocationService
       ├── distance()          straight-line (haversine), always
       │                       available, no external call
       ├── geocode()           delegates to location_search.py's
       │                       Photon-backed forward search (Phase 9)
       ├── reverse_geocode()   delegates to location_search.py's
       │                       Photon-backed reverse lookup (Phase 8)
       └── route()             delegates to routing.py's OSRM-backed
                                real road distance/duration (Phase 17)

distance() is a plain great-circle calculation — fast, free, nothing to
configure or rate-limit. It's appropriate for estimates (e.g. "how far
is this rider from this restaurant"), never as a stand-in for actual
road distance if a future business rule prices delivery by distance
travelled — that case needs route()'s real routing distance instead,
per Phase 16's own instruction not to substitute straight-line for road
distance where road distance is what's actually required.
"""

from decimal import Decimal
from math import atan2, cos, radians, sin, sqrt

from app.schemas.location import PlaceSearchResult, RouteResult
from app.services.location_search import reverse_geocode as _reverse_geocode
from app.services.location_search import search_places as _search_places
from app.services.routing import get_route as _get_route

_EARTH_RADIUS_KM = 6371.0


def distance_km(lat1: Decimal | float, lon1: Decimal | float, lat2: Decimal | float, lon2: Decimal | float) -> float:
    """Great-circle distance between two points, in kilometers."""
    lat1_r, lon1_r, lat2_r, lon2_r = (radians(float(v)) for v in (lat1, lon1, lat2, lon2))
    dlat = lat2_r - lat1_r
    dlon = lon2_r - lon1_r
    a = sin(dlat / 2) ** 2 + cos(lat1_r) * cos(lat2_r) * sin(dlon / 2) ** 2
    return round(_EARTH_RADIUS_KM * 2 * atan2(sqrt(a), sqrt(1 - a)), 2)


def geocode(query: str, *, limit: int = 6) -> list[PlaceSearchResult]:
    return _search_places(query, limit=limit)


def reverse_geocode(latitude: Decimal, longitude: Decimal) -> PlaceSearchResult | None:
    return _reverse_geocode(latitude, longitude)


def route(
    origin_latitude: Decimal, origin_longitude: Decimal, destination_latitude: Decimal, destination_longitude: Decimal
) -> RouteResult | None:
    return _get_route(origin_latitude, origin_longitude, destination_latitude, destination_longitude)
