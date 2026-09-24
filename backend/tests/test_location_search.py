"""Maps & Location System Phase 9 — Forward Geocoding / Address Search.

Covers app/services/location_search.py (the Photon proxy + its shared
throttle) and the GET /api/v1/customer/location/search endpoint.
Mocks httpx.get directly (same pattern already used for push_notifications.py's
Expo API call) — never depends on Photon's real public instance being
reachable to pass.
"""

from decimal import Decimal
from unittest.mock import MagicMock

import pytest

from app.services import location_search


# A trimmed, real response shape (captured live from photon.komoot.io for
# "Azamgarh") — proves the mapping handles genuine Photon output, not a
# hand-crafted fixture that happens to match the code.
AZAMGARH_CITY_FEATURE = {
    "type": "Feature",
    "properties": {
        "osm_type": "N",
        "osm_id": 765060153,
        "osm_key": "place",
        "osm_value": "city",
        "type": "city",
        "name": "Azamgarh",
        "county": "Azamgarh",
        "state": "Uttar Pradesh",
        "country": "India",
        "postcode": "276001",
        "countrycode": "IN",
    },
    "geometry": {"type": "Point", "coordinates": [83.184439, 26.0654351]},
}

AZAMGARH_DISTRICT_FEATURE = {
    "type": "Feature",
    "properties": {
        "osm_type": "R",
        "osm_id": 1959868,
        "osm_key": "boundary",
        "osm_value": "administrative",
        "type": "county",
        "name": "Azamgarh",
        "state": "Uttar Pradesh",
        "country": "India",
        "countrycode": "IN",
        "extra": {"admin_level": "5"},
        "extent": [82.664862, 26.4117595, 83.4682939, 25.6358579],
    },
    "geometry": {"type": "Point", "coordinates": [83.0293105, 26.023639]},
}


@pytest.fixture(autouse=True)
def _reset_throttle():
    location_search._last_request_at = 0.0
    yield
    location_search._last_request_at = 0.0


def _fake_response(features: list[dict]):
    response = MagicMock()
    response.raise_for_status = MagicMock()
    response.json = MagicMock(return_value={"type": "FeatureCollection", "features": features})
    return response


def test_search_places_maps_a_real_photon_response_to_the_minimal_shape(monkeypatch):
    monkeypatch.setattr(location_search.httpx, "get", MagicMock(return_value=_fake_response([AZAMGARH_CITY_FEATURE])))

    results = location_search.search_places("Azamgarh")

    assert len(results) == 1
    result = results[0]
    assert result.city == "Azamgarh"
    assert result.state == "Uttar Pradesh"
    assert result.postal_code == "276001"
    assert result.country == "India"
    assert result.latitude == Decimal("26.0654351")
    assert result.longitude == Decimal("83.184439")
    assert result.place_id == "N:765060153"
    # District is dropped here — county == city for this result, so
    # surfacing it separately would just repeat "Azamgarh" twice.
    assert result.district is None


def test_search_places_never_stores_unnecessary_third_party_fields(monkeypatch):
    """The phase's own explicit instruction: osm_key/osm_value/extent/
    admin_level/countrycode are all real fields Photon returns, and
    none of them exist anywhere on PlaceSearchResult's schema at all —
    not just unset, structurally absent."""
    monkeypatch.setattr(location_search.httpx, "get", MagicMock(return_value=_fake_response([AZAMGARH_DISTRICT_FEATURE])))

    results = location_search.search_places("Azamgarh")

    result_fields = set(results[0].model_dump().keys())
    assert "osm_key" not in result_fields
    assert "osm_value" not in result_fields
    assert "extent" not in result_fields
    assert "admin_level" not in result_fields
    assert "countrycode" not in result_fields


def test_search_places_distinguishes_district_from_city_when_they_genuinely_differ(monkeypatch):
    """A real neighbourhood/suburb-level result: Photon gives both an
    explicit city AND a distinct enclosing county — the one case where
    district must actually carry information the city field doesn't."""
    feature = {
        "properties": {
            "osm_type": "N", "osm_id": 1, "name": "Civil Lines",
            "city": "Azamgarh", "county": "Azamgarh District", "state": "Uttar Pradesh",
            "country": "India", "postcode": "276001",
        },
        "geometry": {"coordinates": [83.2, 26.1]},
    }
    monkeypatch.setattr(location_search.httpx, "get", MagicMock(return_value=_fake_response([feature])))

    results = location_search.search_places("Civil Lines")

    assert results[0].city == "Azamgarh"
    assert results[0].district == "Azamgarh District"


def test_search_places_leaves_district_unset_when_theres_no_separate_city_to_distinguish_it_from(monkeypatch):
    """A village/POI result with only a county, no explicit city, at all
    — e.g. Photon's own data for many rural OSM places. There's nothing
    more specific than the county to call a "district" distinct from
    it, so city falls back to the county name and district stays unset
    rather than redundantly repeating the same value in both fields."""
    feature = {
        "properties": {
            "osm_type": "N", "osm_id": 2, "name": "Some Village",
            "county": "Azamgarh", "state": "Uttar Pradesh", "country": "India", "postcode": "276128",
        },
        "geometry": {"coordinates": [83.2, 26.1]},
    }
    monkeypatch.setattr(location_search.httpx, "get", MagicMock(return_value=_fake_response([feature])))

    results = location_search.search_places("Some Village")

    assert results[0].city == "Azamgarh"
    assert results[0].district is None


def test_search_places_returns_empty_for_a_too_short_query_without_calling_the_provider(monkeypatch):
    mock_get = MagicMock()
    monkeypatch.setattr(location_search.httpx, "get", mock_get)

    assert location_search.search_places("a") == []
    mock_get.assert_not_called()


def test_search_places_raises_when_the_provider_is_unreachable(monkeypatch):
    import httpx as real_httpx

    def raise_connect_error(*args, **kwargs):
        raise real_httpx.ConnectError("connection refused")

    monkeypatch.setattr(location_search.httpx, "get", raise_connect_error)

    with pytest.raises(location_search.PlaceSearchUnavailableError):
        location_search.search_places("Azamgarh")


def test_throttle_waits_between_rapid_successive_calls(monkeypatch):
    sleep_calls = []
    monkeypatch.setattr(location_search.time, "sleep", lambda seconds: sleep_calls.append(seconds))

    location_search._last_request_at = location_search.time.monotonic()  # simulate a call that "just happened"
    location_search._wait_for_throttle_slot()

    assert len(sleep_calls) == 1
    assert 0 < sleep_calls[0] <= location_search._MIN_SECONDS_BETWEEN_REQUESTS


def test_throttle_raises_rather_than_waiting_past_the_max_bound(monkeypatch):
    monkeypatch.setattr(location_search, "_MIN_SECONDS_BETWEEN_REQUESTS", 100.0)
    location_search._last_request_at = location_search.time.monotonic()

    with pytest.raises(location_search.PlaceSearchUnavailableError):
        location_search._wait_for_throttle_slot()


# ---------------------------------------------------------------------------
# HTTP endpoint
# ---------------------------------------------------------------------------


def test_search_endpoint_returns_mapped_results(client, monkeypatch):
    from app.api.v1.customer import location as location_endpoint

    monkeypatch.setattr(
        location_endpoint, "search_places",
        lambda q: [
            location_search.PlaceSearchResult(
                label="Azamgarh, Uttar Pradesh", address_line=None, city="Azamgarh", district=None,
                state="Uttar Pradesh", postal_code="276001", country="India",
                latitude=Decimal("26.0654351"), longitude=Decimal("83.184439"),
                formatted_address="Azamgarh, Uttar Pradesh", place_id="N:765060153",
            )
        ],
    )

    response = client.get("/api/v1/customer/location/search?q=Azamgarh")
    assert response.status_code == 200
    body = response.json()
    assert body["results"][0]["city"] == "Azamgarh"
    assert body["results"][0]["place_id"] == "N:765060153"


def test_search_endpoint_returns_503_when_the_provider_is_unavailable(client, monkeypatch):
    from app.api.v1.customer import location as location_endpoint

    def raise_unavailable(q):
        raise location_search.PlaceSearchUnavailableError("Address search is temporarily unavailable.")

    monkeypatch.setattr(location_endpoint, "search_places", raise_unavailable)

    response = client.get("/api/v1/customer/location/search?q=Azamgarh")
    assert response.status_code == 503


def test_search_endpoint_requires_a_query_param(client):
    response = client.get("/api/v1/customer/location/search")
    assert response.status_code == 422


def test_search_endpoint_is_rate_limited_per_ip(client, monkeypatch):
    from app.api.v1.customer import location as location_endpoint

    monkeypatch.setattr(location_endpoint, "search_places", lambda q: [])

    for _ in range(30):
        assert client.get("/api/v1/customer/location/search?q=test").status_code == 200

    assert client.get("/api/v1/customer/location/search?q=test").status_code == 429
