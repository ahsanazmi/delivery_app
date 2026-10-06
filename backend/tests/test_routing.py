"""Maps & Location System Phase 17 — Routes Foundation.

Covers app/services/routing.py (the OSRM proxy + its shared throttle).
Mocks httpx.get directly, same pattern as test_location_search.py — never
depends on OSRM's real public demo server being reachable to pass.
"""

from decimal import Decimal
from unittest.mock import MagicMock

import httpx
import pytest

from app.services import routing


# A trimmed, real response shape (captured live from router.project-osrm.org
# for a real Azamgarh-area route) — proves the mapping handles genuine
# OSRM output, not a hand-crafted fixture that happens to match the code.
REAL_OSRM_ROUTE_RESPONSE = {
    "code": "Ok",
    "routes": [{"distance": 4287.9, "duration": 262.9, "weight": 262.9, "weight_name": "routability", "legs": []}],
    "waypoints": [
        {"hint": "abc", "location": [83.183934, 26.067892], "name": "", "distance": 35.5},
        {"hint": "def", "location": [83.199071, 26.099811], "name": "", "distance": 95.3},
    ],
}


@pytest.fixture(autouse=True)
def _reset_throttle():
    routing._last_request_at = 0.0
    routing._route_cache._store.clear()
    yield
    routing._last_request_at = 0.0
    routing._route_cache._store.clear()


def _fake_response(body: dict):
    response = MagicMock()
    response.raise_for_status = MagicMock()
    response.json = MagicMock(return_value=body)
    return response


def test_get_route_maps_a_real_osrm_response(monkeypatch):
    monkeypatch.setattr(routing.httpx, "get", MagicMock(return_value=_fake_response(REAL_OSRM_ROUTE_RESPONSE)))

    result = routing.get_route(Decimal("26.068"), Decimal("83.1836"), Decimal("26.0998"), Decimal("83.1991"))

    assert result is not None
    assert result.distance_km == 4.29
    assert result.duration_minutes == 4.4


def test_get_route_requests_coordinates_in_lon_lat_order(monkeypatch):
    mock_get = MagicMock(return_value=_fake_response(REAL_OSRM_ROUTE_RESPONSE))
    monkeypatch.setattr(routing.httpx, "get", mock_get)

    routing.get_route(Decimal("26.068"), Decimal("83.1836"), Decimal("26.0998"), Decimal("83.1991"))

    called_url = mock_get.call_args.args[0]
    assert "83.1836,26.068;83.1991,26.0998" in called_url


def test_get_route_returns_none_when_osrm_finds_no_route(monkeypatch):
    monkeypatch.setattr(routing.httpx, "get", MagicMock(return_value=_fake_response({"code": "NoRoute", "routes": []})))

    result = routing.get_route(Decimal("0"), Decimal("0"), Decimal("89"), Decimal("179"))

    assert result is None


def test_get_route_raises_when_the_provider_is_unreachable(monkeypatch):
    def raise_connect_error(*args, **kwargs):
        raise httpx.ConnectError("boom")

    monkeypatch.setattr(routing.httpx, "get", raise_connect_error)

    with pytest.raises(routing.RouteUnavailableError):
        routing.get_route(Decimal("26.068"), Decimal("83.1836"), Decimal("26.0998"), Decimal("83.1991"))


def test_throttle_waits_between_rapid_successive_calls(monkeypatch):
    # Deliberately different destinations on each call — same-coordinate
    # requests are now cache hits (Phase 27) and wouldn't reach the
    # throttle at all, which is a different behavior this has its own
    # dedicated coverage for below.
    sleep_calls = []
    monkeypatch.setattr(routing.time, "sleep", lambda seconds: sleep_calls.append(seconds))
    monkeypatch.setattr(routing.httpx, "get", MagicMock(return_value=_fake_response(REAL_OSRM_ROUTE_RESPONSE)))

    routing.get_route(Decimal("26.068"), Decimal("83.1836"), Decimal("26.0998"), Decimal("83.1991"))
    routing.get_route(Decimal("26.068"), Decimal("83.1836"), Decimal("27.0"), Decimal("84.0"))

    assert len(sleep_calls) == 1
    assert sleep_calls[0] > 0


def test_throttle_raises_rather_than_waiting_past_the_max_bound(monkeypatch):
    monkeypatch.setattr(routing, "_MIN_SECONDS_BETWEEN_REQUESTS", 100.0)
    monkeypatch.setattr(routing.httpx, "get", MagicMock(return_value=_fake_response(REAL_OSRM_ROUTE_RESPONSE)))

    routing.get_route(Decimal("26.068"), Decimal("83.1836"), Decimal("26.0998"), Decimal("83.1991"))
    with pytest.raises(routing.RouteUnavailableError):
        routing.get_route(Decimal("26.068"), Decimal("83.1836"), Decimal("27.0"), Decimal("84.0"))


def test_get_route_returns_a_cached_result_for_a_repeat_request_without_calling_the_provider_again(monkeypatch):
    """Maps & Location System Phase 27 — Map Billing & Quota Safety: a
    repeat request for the same origin/destination is answered from
    cache, never a second call to OSRM."""
    mock_get = MagicMock(return_value=_fake_response(REAL_OSRM_ROUTE_RESPONSE))
    monkeypatch.setattr(routing.httpx, "get", mock_get)

    first = routing.get_route(Decimal("26.068"), Decimal("83.1836"), Decimal("26.0998"), Decimal("83.1991"))
    second = routing.get_route(Decimal("26.068"), Decimal("83.1836"), Decimal("26.0998"), Decimal("83.1991"))

    assert mock_get.call_count == 1
    assert first == second


def test_get_route_raises_rather_than_crashing_on_an_unparseable_body(monkeypatch):
    """Live Rider Tracking Phase 32 — Offline/Failure Handling. A
    reachable OSRM that responds 200 with a non-JSON body is a distinct
    failure mode from being unreachable (httpx.HTTPError wouldn't catch
    it), but must degrade the exact same way — the caller only ever
    catches RouteUnavailableError."""
    response = MagicMock()
    response.raise_for_status = MagicMock()
    response.json = MagicMock(side_effect=ValueError("not json"))
    monkeypatch.setattr(routing.httpx, "get", MagicMock(return_value=response))

    with pytest.raises(routing.RouteUnavailableError):
        routing.get_route(Decimal("26.068"), Decimal("83.1836"), Decimal("26.0998"), Decimal("83.1991"))


def test_get_route_raises_rather_than_crashing_on_a_malformed_route_shape(monkeypatch):
    """Live Rider Tracking Phase 32 — a 200 "Ok" response whose route
    entry is missing the fields this code reads (a corrupted/truncated
    body, not just "no route found") must also degrade to
    RouteUnavailableError, not an uncaught KeyError."""
    malformed = {"code": "Ok", "routes": [{"weight": 1.0}]}  # no distance/duration
    monkeypatch.setattr(routing.httpx, "get", MagicMock(return_value=_fake_response(malformed)))

    with pytest.raises(routing.RouteUnavailableError):
        routing.get_route(Decimal("26.068"), Decimal("83.1836"), Decimal("26.0998"), Decimal("83.1991"))
