from decimal import Decimal
from math import cos, radians
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.delivery_partner import ApprovalStatus
from app.models.restaurant import Restaurant
from app.services.admin_settings import get_platform_settings
from app.services.location_service import distance_km

# Degrees of latitude per km is ~constant; used only for a coarse bounding
# box that narrows the candidate rows before the exact great-circle check.
_KM_PER_DEGREE_LATITUDE = 111.0


def effective_radius_km(restaurant: Restaurant, default_radius_km: Decimal) -> Decimal:
    return restaurant.delivery_radius_km if restaurant.delivery_radius_km is not None else default_radius_km


def restaurants_delivering_to(db: Session, latitude: Decimal | float, longitude: Decimal | float) -> dict[UUID, float]:
    """{restaurant_id: distance_km} for every live (active + approved)
    restaurant whose own delivery radius — or the platform default — covers
    this point. Straight-line distance, same as checkout's distance_km."""
    default_radius = get_platform_settings(db).default_delivery_radius_km
    largest_override = db.scalar(select(func.max(Restaurant.delivery_radius_km))) or Decimal("0")
    search_radius = float(max(default_radius, largest_override))

    lat = float(latitude)
    lng = float(longitude)
    lat_delta = search_radius / _KM_PER_DEGREE_LATITUDE
    # Longitude degrees shrink toward the poles; clamp so the box never
    # degenerates (or divides by ~0) at extreme latitudes.
    lng_delta = search_radius / (_KM_PER_DEGREE_LATITUDE * max(cos(radians(lat)), 0.01))

    candidates = db.scalars(
        select(Restaurant).where(
            Restaurant.is_active.is_(True),
            Restaurant.approval_status == ApprovalStatus.APPROVED,
            Restaurant.latitude.between(lat - lat_delta, lat + lat_delta),
            Restaurant.longitude.between(lng - lng_delta, lng + lng_delta),
        )
    )
    in_range: dict[UUID, float] = {}
    for restaurant in candidates:
        distance = distance_km(lat, lng, restaurant.latitude, restaurant.longitude)
        if distance <= float(effective_radius_km(restaurant, default_radius)):
            in_range[restaurant.id] = distance
    return in_range


def delivery_range_issue(db: Session, restaurant: Restaurant, latitude: Decimal | float, longitude: Decimal | float) -> str | None:
    """Checkout's version of the same rule: a human-readable reason when this
    point is outside the restaurant's delivery radius, else None."""
    radius = effective_radius_km(restaurant, get_platform_settings(db).default_delivery_radius_km)
    distance = distance_km(latitude, longitude, restaurant.latitude, restaurant.longitude)
    if distance <= float(radius):
        return None
    return (
        f"{restaurant.name} delivers within {radius.normalize():f} km, and this address is {distance:.1f} km away. "
        "Choose a closer address or another restaurant."
    )
