from dataclasses import dataclass
from decimal import Decimal

from fastapi import HTTPException, Query, status


@dataclass(frozen=True)
class CustomerLocation:
    latitude: Decimal
    longitude: Decimal


def customer_location(
    latitude: Decimal | None = Query(default=None, ge=-90, le=90),
    longitude: Decimal | None = Query(default=None, ge=-180, le=180),
) -> CustomerLocation | None:
    """Optional ?latitude=&longitude= on customer discovery endpoints — the
    point restaurants are filtered to (by delivery radius) and sorted from."""
    if latitude is None and longitude is None:
        return None
    if latitude is None or longitude is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Provide both latitude and longitude, or neither.",
        )
    return CustomerLocation(latitude=latitude, longitude=longitude)
