from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.restaurant import Restaurant
from app.models.restaurant_hours import RestaurantOperatingHours
from app.schemas.restaurant_hours import OperatingHourEntry


def get_hours_for_restaurant(db: Session, restaurant_id: UUID) -> list[RestaurantOperatingHours]:
    statement = (
        select(RestaurantOperatingHours)
        .where(RestaurantOperatingHours.restaurant_id == restaurant_id)
        .order_by(RestaurantOperatingHours.day_of_week)
    )
    return list(db.scalars(statement))


def replace_hours(
    db: Session, restaurant_id: UUID, entries: list[OperatingHourEntry]
) -> list[RestaurantOperatingHours]:
    """A full-week replace (PUT semantics) — simpler and less error-prone for
    the owner than per-day PATCHes, and matches how a weekly schedule is
    naturally edited as one form."""
    db.query(RestaurantOperatingHours).filter(RestaurantOperatingHours.restaurant_id == restaurant_id).delete()
    rows = [
        RestaurantOperatingHours(
            restaurant_id=restaurant_id,
            day_of_week=entry.day_of_week,
            is_closed=entry.is_closed,
            open_time=entry.open_time,
            close_time=entry.close_time,
        )
        for entry in entries
    ]
    db.add_all(rows)
    db.commit()
    return get_hours_for_restaurant(db, restaurant_id)


def is_within_operating_hours(hours: list[RestaurantOperatingHours], now: datetime) -> bool:
    """True if no hours are configured at all (an opt-in feature — until the
    owner sets a schedule, checkout keeps relying on the plain is_open
    toggle), or if `now` falls within today's configured window.

    Times are compared in UTC, consistent with how "today" is already defined
    elsewhere in this app (e.g. the Phase 2 dashboard's daily metrics) — there
    is no per-restaurant timezone field yet.
    """
    if not hours:
        return True
    today = now.weekday()  # 0=Monday .. 6=Sunday
    todays_hours = next((h for h in hours if h.day_of_week == today), None)
    if todays_hours is None or todays_hours.is_closed:
        return False
    if todays_hours.open_time is None or todays_hours.close_time is None:
        return False
    current_time = now.time()
    return todays_hours.open_time <= current_time < todays_hours.close_time


def compute_is_accepting_orders(
    restaurant: Restaurant, hours: list[RestaurantOperatingHours], now: datetime | None = None
) -> bool:
    """The single source of truth for "can this restaurant accept an order
    right now" — the owner's manual toggle AND, if a schedule is configured,
    being within today's window. Never just the toggle alone."""
    if not restaurant.is_open:
        return False
    return is_within_operating_hours(hours, now or datetime.now(UTC))


def get_today_hours(hours: list[RestaurantOperatingHours], now: datetime | None = None) -> RestaurantOperatingHours | None:
    now = now or datetime.now(UTC)
    today = now.weekday()
    return next((h for h in hours if h.day_of_week == today), None)
