"""Live Rider Tracking Phases 22–24 — Live ETA / ETA Staleness / Route
Refresh Strategy.

Every test here mocks location_service.route() directly (the same
pattern test_order_route.py already uses) — none of this ever depends on
OSRM's real public instance being reachable.
"""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from unittest.mock import MagicMock

import pytest

from app.models.order import Order, OrderStatus
from app.schemas.location import RouteResult
from app.services import eta as eta_module
from app.services.eta import clear_eta_cache, get_live_eta
from app.services.routing import RouteUnavailableError


def _order(**overrides) -> Order:
    payload = {
        "id": __import__("uuid").uuid4(),
        "user_id": __import__("uuid").uuid4(),
        "restaurant_id": "rest-1",
        "order_number": "ORD-ETA-1",
        "status": OrderStatus.RIDER_ASSIGNED,
        "address_line": "1 Road",
        "city": "Town",
        "postal_code": "560001",
        "latitude": Decimal("12.97"),
        "longitude": Decimal("77.59"),
    }
    payload.update(overrides)
    return Order(**payload)


@pytest.fixture(autouse=True)
def _clear_cache():
    eta_module._eta_cache.clear()
    yield
    eta_module._eta_cache.clear()


def test_computes_a_live_eta_from_the_current_rider_position(monkeypatch):
    order = _order()
    mock_route = MagicMock(return_value=RouteResult(distance_km=4.3, duration_minutes=9.0))
    monkeypatch.setattr(eta_module.location_service, "route", mock_route)

    estimated_delivery_at, source = get_live_eta(order, Decimal("12.1"), Decimal("77.1"))

    mock_route.assert_called_once_with(Decimal("12.1"), Decimal("77.1"), Decimal("12.97"), Decimal("77.59"))
    assert source == "live"
    assert estimated_delivery_at is not None


def test_returns_unavailable_when_the_order_has_no_delivery_coordinates(monkeypatch):
    order = _order(latitude=None, longitude=None)
    mock_route = MagicMock()
    monkeypatch.setattr(eta_module.location_service, "route", mock_route)

    estimated_delivery_at, source = get_live_eta(order, Decimal("12.1"), Decimal("77.1"))

    assert estimated_delivery_at is None
    assert source == "unavailable"
    mock_route.assert_not_called()


def test_returns_unavailable_when_routing_fails_and_nothing_was_ever_cached(monkeypatch):
    order = _order()
    monkeypatch.setattr(eta_module.location_service, "route", MagicMock(side_effect=RouteUnavailableError("down")))

    estimated_delivery_at, source = get_live_eta(order, Decimal("12.1"), Decimal("77.1"))

    assert estimated_delivery_at is None
    assert source == "unavailable"


def test_falls_back_to_the_last_good_cached_eta_when_routing_fails(monkeypatch):
    order = _order()
    monkeypatch.setattr(eta_module.location_service, "route", MagicMock(return_value=RouteResult(distance_km=4.3, duration_minutes=9.0)))
    first_eta, _ = get_live_eta(order, Decimal("12.1"), Decimal("77.1"))

    monkeypatch.setattr(eta_module.location_service, "route", MagicMock(side_effect=RouteUnavailableError("down")))
    # Move far enough to force a refresh attempt, which now fails.
    second_eta, source = get_live_eta(order, Decimal("13.0"), Decimal("78.0"))

    assert source == "live"
    assert second_eta == first_eta


def test_does_not_recompute_for_a_small_movement_within_the_refresh_window(monkeypatch):
    """Live Rider Tracking Phase 24 — do NOT call the routing API for
    every GPS point."""
    order = _order()
    mock_route = MagicMock(return_value=RouteResult(distance_km=4.3, duration_minutes=9.0))
    monkeypatch.setattr(eta_module.location_service, "route", mock_route)

    get_live_eta(order, Decimal("12.1"), Decimal("77.1"))
    # ~11 meters away — well under the 300m movement threshold.
    get_live_eta(order, Decimal("12.1001"), Decimal("77.1"))

    assert mock_route.call_count == 1


def test_recomputes_once_the_rider_has_moved_far_enough(monkeypatch):
    order = _order()
    mock_route = MagicMock(return_value=RouteResult(distance_km=4.3, duration_minutes=9.0))
    monkeypatch.setattr(eta_module.location_service, "route", mock_route)

    get_live_eta(order, Decimal("12.1"), Decimal("77.1"))
    # ~1.1km away — well over the 300m threshold.
    get_live_eta(order, Decimal("12.11"), Decimal("77.1"))

    assert mock_route.call_count == 2


def test_recomputes_once_enough_time_has_passed_even_without_movement(monkeypatch):
    order = _order()
    mock_route = MagicMock(return_value=RouteResult(distance_km=4.3, duration_minutes=9.0))
    monkeypatch.setattr(eta_module.location_service, "route", mock_route)

    get_live_eta(order, Decimal("12.1"), Decimal("77.1"))

    cached = eta_module._eta_cache[order.id]
    cached.computed_at = datetime.now(UTC) - timedelta(seconds=61)

    get_live_eta(order, Decimal("12.1"), Decimal("77.1"))

    assert mock_route.call_count == 2


def test_recomputes_when_the_order_moves_to_a_different_status_even_without_movement_or_elapsed_time(monkeypatch):
    """A status change (e.g. RIDER_ASSIGNED -> PICKED_UP) means a
    different leg of the trip even if the rider hasn't physically moved
    yet — the cached ETA no longer reflects the real trip."""
    order = _order(status=OrderStatus.RIDER_ASSIGNED)
    mock_route = MagicMock(return_value=RouteResult(distance_km=4.3, duration_minutes=9.0))
    monkeypatch.setattr(eta_module.location_service, "route", mock_route)

    get_live_eta(order, Decimal("12.1"), Decimal("77.1"))
    order.status = OrderStatus.PICKED_UP
    get_live_eta(order, Decimal("12.1"), Decimal("77.1"))

    assert mock_route.call_count == 2


def test_clear_eta_cache_removes_the_cached_entry(monkeypatch):
    order = _order()
    monkeypatch.setattr(eta_module.location_service, "route", MagicMock(return_value=RouteResult(distance_km=4.3, duration_minutes=9.0)))
    get_live_eta(order, Decimal("12.1"), Decimal("77.1"))
    assert order.id in eta_module._eta_cache

    clear_eta_cache(order.id)

    assert order.id not in eta_module._eta_cache
