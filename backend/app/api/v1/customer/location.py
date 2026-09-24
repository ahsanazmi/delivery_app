from decimal import Decimal

from fastapi import APIRouter, HTTPException, Query, Request, status

from app.core.rate_limit import rate_limit
from app.schemas.location import PlaceSearchResponse, ReverseGeocodeResponse
from app.services.location_search import PlaceSearchUnavailableError, reverse_geocode, search_places

router = APIRouter()

# Maps & Location System Phase 8/9 — Reverse Geocoding and Forward
# Geocoding / Address Search. No auth dependency, matching
# customer/search.py's own pattern for discovery endpoints that never
# touch customer-specific data — neither a place search result nor a
# reverse-geocoded address is private. Rate-limited per-IP regardless
# (in addition to location_search.py's own shared, global 1 req/s
# throttle on the outbound Photon call), since this proxies to a free
# external service this backend doesn't want a single abusive client to
# exhaust.


@router.get("/location/search", response_model=PlaceSearchResponse)
def search_location(
    request: Request,
    q: str = Query(min_length=1, max_length=200),
) -> PlaceSearchResponse:
    rate_limit(request, max_attempts=30, window_seconds=60)
    try:
        results = search_places(q)
    except PlaceSearchUnavailableError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc
    return PlaceSearchResponse(results=results)


@router.get("/location/reverse", response_model=ReverseGeocodeResponse)
def reverse_geocode_location(
    request: Request,
    lat: Decimal = Query(ge=-90, le=90),
    lon: Decimal = Query(ge=-180, le=180),
) -> ReverseGeocodeResponse:
    rate_limit(request, max_attempts=30, window_seconds=60)
    try:
        result = reverse_geocode(lat, lon)
    except PlaceSearchUnavailableError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc
    return ReverseGeocodeResponse(result=result)
