"""Maps & Location System Phase 13 — Delivery Location Validation."""

from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.models.address import Address
from app.models.restaurant import Restaurant
from app.schemas.address import AddressCreate
from app.services.checkout import validate_delivery_location


def _address(**overrides) -> Address:
    payload = {
        "user_id": None,
        "label": "Home",
        "recipient_name": "Customer",
        "phone": "9999999999",
        "address_line": "15 Market Road",
        "city": "Bengaluru",
        "state": "Karnataka",
        "postal_code": "560001",
    }
    payload.update(overrides)
    return Address(**payload)


def _restaurant(**overrides) -> Restaurant:
    payload = {
        "owner_id": None,
        "name": "Chai House",
        "phone": "9876543210",
        "address": "Main Road",
        "latitude": Decimal("12.1"),
        "longitude": Decimal("77.1"),
        "minimum_order": Decimal("0.00"),
        "delivery_fee": Decimal("0.00"),
    }
    payload.update(overrides)
    return Restaurant(**payload)


def test_no_issues_when_address_has_no_coordinates_at_all():
    """Manual address entry without ever touching the map/search flow
    must keep working (Phase 2's own standing promise) — missing
    coordinates alone is never blocked."""
    issues = validate_delivery_location(_address(latitude=None, longitude=None), _restaurant())
    assert issues == []


def test_no_issues_when_address_has_valid_coordinates():
    issues = validate_delivery_location(_address(latitude=Decimal("12.97"), longitude=Decimal("77.59")), _restaurant())
    assert issues == []


def test_flags_a_lone_latitude_with_no_longitude():
    issues = validate_delivery_location(_address(latitude=Decimal("12.97"), longitude=None), _restaurant())
    assert "This address has an incomplete pinned location. Please update it on the map." in issues


def test_flags_a_lone_longitude_with_no_latitude():
    issues = validate_delivery_location(_address(latitude=None, longitude=Decimal("77.59")), _restaurant())
    assert "This address has an incomplete pinned location. Please update it on the map." in issues


def test_flags_an_out_of_range_latitude():
    """Defensive re-check — AddressCreate's own Field(ge=-90, le=90) and
    the DB already prevent this via the API, but a legacy row or a
    write that bypassed those guards must still be caught here."""
    address = _address(latitude=Decimal("95"), longitude=Decimal("77.59"))
    issues = validate_delivery_location(address, _restaurant())
    assert "This address has an invalid latitude." in issues


def test_flags_an_out_of_range_longitude():
    address = _address(latitude=Decimal("12.97"), longitude=Decimal("200"))
    issues = validate_delivery_location(address, _restaurant())
    assert "This address has an invalid longitude." in issues


def test_flags_a_restaurant_with_no_location_configured():
    restaurant = _restaurant()
    restaurant.latitude = None
    restaurant.longitude = None
    issues = validate_delivery_location(_address(latitude=None, longitude=None), restaurant)
    assert "This restaurant's location isn't configured yet." in issues


def test_skips_address_and_restaurant_checks_when_neither_is_provided():
    assert validate_delivery_location(None, None) == []


def test_address_create_rejects_a_lone_latitude_with_no_longitude():
    with pytest.raises(ValidationError, match="Both latitude and longitude"):
        AddressCreate(
            recipient_name="Customer", phone="9999999999", address_line="15 Market Road",
            city="Bengaluru", state="Karnataka", postal_code="560001",
            latitude=Decimal("12.97"), longitude=None,
        )


def test_address_create_accepts_both_coordinates_present():
    address = AddressCreate(
        recipient_name="Customer", phone="9999999999", address_line="15 Market Road",
        city="Bengaluru", state="Karnataka", postal_code="560001",
        latitude=Decimal("12.97"), longitude=Decimal("77.59"),
    )
    assert address.latitude == Decimal("12.97")


def test_address_create_accepts_neither_coordinate_present():
    address = AddressCreate(
        recipient_name="Customer", phone="9999999999", address_line="15 Market Road",
        city="Bengaluru", state="Karnataka", postal_code="560001",
    )
    assert address.latitude is None
    assert address.longitude is None
