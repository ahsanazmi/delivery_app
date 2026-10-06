"""Maps & Location System Phase 16 — Distance Calculation / LocationService."""

from decimal import Decimal
from unittest.mock import patch

from app.services import location_service


def test_distance_km_is_zero_for_the_same_point():
    assert location_service.distance_km(26.068, 83.1836, 26.068, 83.1836) == 0.0


def test_distance_km_matches_a_known_real_world_distance():
    # Delhi to Mumbai — a well-known real-world great-circle distance,
    # roughly 1150 km.
    km = location_service.distance_km(28.6139, 77.2090, 19.0760, 72.8777)
    assert 1100 < km < 1200


def test_distance_km_accepts_decimal_inputs_like_the_actual_model_columns_use():
    km = location_service.distance_km(Decimal("26.0680000"), Decimal("83.1836000"), Decimal("26.0680000"), Decimal("83.1836000"))
    assert km == 0.0


def test_geocode_delegates_to_the_existing_photon_backed_search():
    with patch("app.services.location_service._search_places") as mocked:
        mocked.return_value = ["result"]
        result = location_service.geocode("Azamgarh", limit=3)
        mocked.assert_called_once_with("Azamgarh", limit=3)
        assert result == ["result"]


def test_reverse_geocode_delegates_to_the_existing_photon_backed_reverse_lookup():
    with patch("app.services.location_service._reverse_geocode") as mocked:
        mocked.return_value = "result"
        result = location_service.reverse_geocode(Decimal("26.068"), Decimal("83.1836"))
        mocked.assert_called_once_with(Decimal("26.068"), Decimal("83.1836"))
        assert result == "result"


def test_route_delegates_to_the_osrm_backed_routing_service():
    """Maps & Location System Phase 17 — route() completes the
    LocationService shape this phase's own diagram described."""
    with patch("app.services.location_service._get_route") as mocked:
        mocked.return_value = "route-result"
        result = location_service.route(Decimal("26.068"), Decimal("83.1836"), Decimal("26.1"), Decimal("83.2"))
        mocked.assert_called_once_with(Decimal("26.068"), Decimal("83.1836"), Decimal("26.1"), Decimal("83.2"))
        assert result == "route-result"
