from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.models import Address, Product, Restaurant, ServiceArea, ServiceAreaPostalCode, User, UserRole
from app.models.delivery_partner import ApprovalStatus
from app.models.restaurant_hours import RestaurantOperatingHours
from app.services import checkout as checkout_service
from app.services.cart import add_item, create_cart_for_user


@pytest.fixture()
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    Base.metadata.drop_all(engine)


def _customer(db, email="customer@example.com"):
    user = User(name="Customer", email=email, password_hash="x", role=UserRole.CUSTOMER)
    db.add(user)
    db.commit()
    return user


def _restaurant(db, **overrides):
    owner = User(name="Owner", email=f"owner-{overrides.get('name','x')}@example.com", password_hash="x", role=UserRole.RESTAURANT_OWNER)
    db.add(owner)
    db.commit()
    payload = {
        "owner_id": owner.id,
        "name": "Chai House",
        "phone": "9876543210",
        "address": "Main Road",
        "latitude": Decimal("12.1"),
        "longitude": Decimal("77.1"),
        "minimum_order": Decimal("100.00"),
        "delivery_fee": Decimal("30.00"),
        "is_active": True,
        "is_open": True,
    }
    payload.update(overrides)
    restaurant = Restaurant(**payload)
    db.add(restaurant)
    db.commit()
    return restaurant


def _address(db, user):
    address = Address(
        user_id=user.id,
        label="Home",
        recipient_name="Customer",
        phone="9999999999",
        address_line="15 Market Road",
        city="Bengaluru",
        state="Karnataka",
        postal_code="560001",
        is_default=True,
    )
    db.add(address)
    db.commit()
    return address


def test_checkout_preview_flags_empty_cart_and_missing_address(db):
    user = _customer(db)
    create_cart_for_user(db, user.id)

    result = checkout_service.get_checkout_preview(db, user)
    assert "Your cart is empty." in result["issues"]
    assert "Add a delivery address before checking out." in result["issues"]
    assert result["selected_address"] is None


def test_checkout_preview_flags_minimum_order_and_closed_restaurant(db):
    user = _customer(db)
    restaurant = _restaurant(db, is_open=False, minimum_order=Decimal("500.00"))
    product = Product(restaurant_id=restaurant.id, name="Tea", price=Decimal("40.00"))
    db.add(product)
    db.commit()

    cart = create_cart_for_user(db, user.id)
    add_item(db, cart, product.id, 1)
    _address(db, user)

    result = checkout_service.get_checkout_preview(db, user)
    assert "This restaurant is currently closed." in result["issues"]
    assert any("Minimum order" in issue for issue in result["issues"])
    assert result["subtotal"] == Decimal("40.00")


def test_validate_checkout_succeeds_when_everything_is_valid(db):
    user = _customer(db)
    restaurant = _restaurant(db)
    product = Product(restaurant_id=restaurant.id, name="Biryani", price=Decimal("220.00"))
    db.add(product)
    db.commit()

    cart = create_cart_for_user(db, user.id)
    add_item(db, cart, product.id, 1)
    address = _address(db, user)

    result = checkout_service.validate_checkout(db, user, address.id)
    assert result["valid"] is True
    assert result["issues"] == []
    assert result["total"] == Decimal("250.00")  # 220 subtotal + 30 delivery fee


def test_validate_checkout_rejects_address_owned_by_another_customer(db):
    user = _customer(db, email="a@example.com")
    other_user = _customer(db, email="b@example.com")
    restaurant = _restaurant(db)
    product = Product(restaurant_id=restaurant.id, name="Biryani", price=Decimal("220.00"))
    db.add(product)
    db.commit()

    cart = create_cart_for_user(db, user.id)
    add_item(db, cart, product.id, 1)
    other_address = _address(db, other_user)

    result = checkout_service.validate_checkout(db, user, other_address.id)
    assert result["valid"] is False
    assert "Select a valid delivery address." in result["issues"]


def test_validate_checkout_rejects_address_outside_every_active_service_area(db):
    user = _customer(db)
    restaurant = _restaurant(db)
    product = Product(restaurant_id=restaurant.id, name="Biryani", price=Decimal("220.00"))
    db.add(product)
    db.commit()

    cart = create_cart_for_user(db, user.id)
    add_item(db, cart, product.id, 1)
    address = _address(db, user)  # postal_code="560001", not covered by any zone below

    zone = ServiceArea(city="Bengaluru", zone_name="Indiranagar", is_active=True)
    db.add(zone)
    db.commit()
    db.add(ServiceAreaPostalCode(service_area_id=zone.id, postal_code="560038"))
    db.commit()

    result = checkout_service.validate_checkout(db, user, address.id)
    assert result["valid"] is False
    assert "We don't currently deliver to this address's area." in result["issues"]


def test_validate_checkout_accepts_address_inside_an_active_service_area(db):
    user = _customer(db)
    restaurant = _restaurant(db)
    product = Product(restaurant_id=restaurant.id, name="Biryani", price=Decimal("220.00"))
    db.add(product)
    db.commit()

    cart = create_cart_for_user(db, user.id)
    add_item(db, cart, product.id, 1)
    address = _address(db, user)  # postal_code="560001"

    zone = ServiceArea(city="Bengaluru", zone_name="Market Road", is_active=True)
    db.add(zone)
    db.commit()
    db.add(ServiceAreaPostalCode(service_area_id=zone.id, postal_code="560001"))
    db.commit()

    result = checkout_service.validate_checkout(db, user, address.id)
    assert result["valid"] is True
    assert result["issues"] == []


def test_cannot_even_add_a_suspended_restaurants_product_to_the_cart(db):
    """SUSPENDED is an admin-imposed platform standing (distinct from the
    owner's own is_open/is_active toggles) — get_active_restaurant_or_404
    blocks it at add-to-cart time already, before checkout is ever reached."""
    from fastapi import HTTPException

    user = _customer(db)
    restaurant = _restaurant(db, approval_status=ApprovalStatus.SUSPENDED)
    product = Product(restaurant_id=restaurant.id, name="Biryani", price=Decimal("220.00"))
    db.add(product)
    db.commit()

    cart = create_cart_for_user(db, user.id)
    with pytest.raises(HTTPException) as excinfo:
        add_item(db, cart, product.id, 1)
    assert excinfo.value.status_code == 404


def test_validate_checkout_rejects_a_restaurant_outside_its_configured_hours_even_when_marked_open(db):
    """is_open=True alone isn't enough once a weekly schedule is configured —
    compute_is_accepting_orders must also confirm `now` falls inside today's window."""
    user = _customer(db)
    restaurant = _restaurant(db, is_open=True)
    product = Product(restaurant_id=restaurant.id, name="Biryani", price=Decimal("220.00"))
    db.add(product)
    db.commit()
    for day in range(7):
        db.add(RestaurantOperatingHours(restaurant_id=restaurant.id, day_of_week=day, is_closed=True))
    db.commit()

    cart = create_cart_for_user(db, user.id)
    add_item(db, cart, product.id, 1)
    address = _address(db, user)

    result = checkout_service.validate_checkout(db, user, address.id)
    assert result["valid"] is False
    assert "This restaurant is currently closed." in result["issues"]


def test_checkout_endpoints_over_http():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)

    def override_get_db():
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    try:
        with Session(engine) as seed:
            user = _customer(seed)
            restaurant = _restaurant(seed)
            product = Product(restaurant_id=restaurant.id, name="Biryani", price=Decimal("220.00"))
            seed.add(product)
            seed.commit()
            cart = create_cart_for_user(seed, user.id)
            add_item(seed, cart, product.id, 1)
            address = _address(seed, user)
            user_email, address_id = user.email, address.id

        with TestClient(app) as client:
            from app.core.security import create_access_token

            with Session(engine) as s:
                u = s.query(User).filter(User.email == user_email).first()
                token = create_access_token(u.id)

            headers = {"Authorization": f"Bearer {token}"}

            preview = client.get("/api/v1/customer/checkout", headers=headers)
            assert preview.status_code == 200
            body = preview.json()
            assert body["issues"] == []
            assert body["total"] == "250.00"

            validate = client.post(
                "/api/v1/customer/orders/validate", headers=headers, json={"address_id": str(address_id)}
            )
            assert validate.status_code == 200
            vbody = validate.json()
            assert vbody["valid"] is True
            assert vbody["address"]["id"] == str(address_id)

            missing_address = client.post(
                "/api/v1/customer/orders/validate",
                headers=headers,
                json={"address_id": "00000000-0000-0000-0000-000000000000"},
            )
            assert missing_address.status_code == 200
            assert missing_address.json()["valid"] is False
    finally:
        app.dependency_overrides.clear()
        Base.metadata.drop_all(engine)
