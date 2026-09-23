"""Logging & Error Handling (Phase 26).

Verifies, for each named category, that a real request going down the
failure path actually produces a log record — not just that the HTTP
response is correct (already covered elsewhere) — and that nothing on the
"never log" list (passwords, JWT access/refresh tokens, payment secrets)
ever appears in a log message, even when the value that triggered the
failure is one of those secrets.
"""

import logging
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.core.security import create_access_token, hash_password
from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.models.user import User, UserRole


def _register_and_login(client, *, role="customer", email="logging-user@example.com", phone="9930000001", password="secure-pass-123"):
    client.post("/api/v1/auth/register", json={"name": "Logging Test", "email": email, "phone": phone, "password": password, "role": role})
    login = client.post("/api/v1/auth/login", json={"email": email, "password": password})
    return login.json()["access_token"], login.json()["refresh_token"]


def _make_admin(client, email="logging-admin@example.com", phone="9930000099"):
    from app.db.session import get_db

    db = next(client.app.dependency_overrides[get_db]())
    admin = User(name="Admin", email=email, phone=phone, password_hash=hash_password("x"), role=UserRole.ADMIN)
    db.add(admin)
    db.commit()
    token = create_access_token(admin.id)
    db.close()
    return token


def test_login_failure_is_logged_without_the_password(client, caplog):
    secret_password = "super-secret-attempt-value-9000"
    with caplog.at_level(logging.WARNING):
        response = client.post(
            "/api/v1/auth/login", json={"email": "nobody-here@example.com", "password": secret_password}
        )
    assert response.status_code == 401
    assert any("Login failed" in r.message for r in caplog.records)
    assert secret_password not in caplog.text


def test_invalid_access_token_is_logged_without_the_token_value(client, caplog):
    fake_token = "this-is-not-a-real-jwt-but-must-never-appear-in-a-log"
    with caplog.at_level(logging.WARNING):
        response = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {fake_token}"})
    assert response.status_code == 401
    assert any("Authentication failed" in r.message for r in caplog.records)
    assert fake_token not in caplog.text


def test_invalid_refresh_token_is_logged_without_the_token_value(client, caplog):
    fake_refresh = "this-is-not-a-real-refresh-token-but-must-never-appear-in-a-log"
    with caplog.at_level(logging.WARNING):
        response = client.post("/api/v1/auth/refresh", json={"refresh_token": fake_refresh})
    assert response.status_code == 401
    assert any("Token refresh failed" in r.message for r in caplog.records)
    assert fake_refresh not in caplog.text


def test_authorization_failure_is_logged(client, caplog):
    token, _ = _register_and_login(client, role="customer", email="logging-cust@example.com", phone="9930000002")
    with caplog.at_level(logging.WARNING):
        response = client.get("/api/v1/admin/dashboard", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 403
    assert any("Authorization failed" in r.message for r in caplog.records)


def test_order_error_invalid_transition_is_logged(client, caplog):
    from app.db.session import get_db
    from app.models.order import OrderStatus
    from app.services.orders import transition_order_status

    db = next(client.app.dependency_overrides[get_db]())
    owner = User(name="Owner", email="logging-owner@example.com", phone="9930000003", password_hash=hash_password("x"), role=UserRole.RESTAURANT_OWNER)
    customer = User(name="Cust", email="logging-cust2@example.com", phone="9930000004", password_hash=hash_password("x"), role=UserRole.CUSTOMER)
    db.add_all([owner, customer])
    db.commit()
    from app.models.restaurant import Restaurant

    restaurant = Restaurant(
        owner_id=owner.id, name="Logging Diner", phone="9876500099", address="1 Log Road",
        latitude=Decimal("12.1"), longitude=Decimal("77.1"), minimum_order=Decimal("0.00"), delivery_fee=Decimal("30.00"),
    )
    db.add(restaurant)
    db.commit()
    from app.models.product import Product
    from app.services.addresses import create_address
    from app.services.cart import add_item, create_cart_for_user
    from app.services.orders import create_order

    product = Product(restaurant_id=restaurant.id, name="Item", price=Decimal("100.00"))
    db.add(product)
    db.commit()
    address = create_address(db, customer.id, {
        "label": "Home", "recipient_name": "Cust", "phone": "9930000004",
        "address_line": "1 Log Road", "city": "Town", "state": "ST", "postal_code": "560001",
    })
    cart = create_cart_for_user(db, customer.id)
    add_item(db, cart, product.id, 1)
    order = create_order(db, customer, address.id)

    with caplog.at_level(logging.WARNING):
        with pytest.raises(ValueError):
            transition_order_status(db, order, OrderStatus.DELIVERED)  # PLACED -> DELIVERED is not a valid direct jump
    assert any("Order error" in r.message for r in caplog.records)
    db.close()


def test_admin_action_is_logged(client, caplog):
    from app.db.session import get_db

    admin_token = _make_admin(client)
    db = next(client.app.dependency_overrides[get_db]())
    rider = User(name="Rider", email="logging-rider@example.com", phone="9930000005", password_hash=hash_password("x"), role=UserRole.RIDER)
    db.add(rider)
    db.commit()
    rider_id = str(rider.id)
    db.close()

    with caplog.at_level(logging.INFO):
        response = client.post(
            f"/api/v1/admin/riders/{rider_id}/approve",
            headers={"Authorization": f"Bearer {admin_token}"},
            json={"reason": "looks good"},
        )
    assert response.status_code == 200
    assert any("Admin action" in r.message for r in caplog.records)


def test_unexpected_exception_is_logged_with_traceback(caplog, monkeypatch):
    """Uses its own raise_server_exceptions=False TestClient, same as
    test_security.py's own unhandled-exception test — the shared `client`
    fixture re-raises the exception into the test itself by default, which
    would fail this test even though the app's own exception handler
    already produced the correct sanitized response."""
    from app.services import restaurants as restaurant_service

    def _boom(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(restaurant_service, "list_active_restaurants", _boom)

    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)

    def override_get_db():
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    try:
        with caplog.at_level(logging.ERROR):
            with TestClient(app, raise_server_exceptions=False) as test_client:
                response = test_client.get("/api/v1/customer/restaurants")
        assert response.status_code == 500
        assert response.json() == {"detail": "Internal server error"}
        assert any("Unhandled exception" in r.message for r in caplog.records)
        # The traceback (with the real exception text) reaches the log, even
        # though it never reaches the client — that's the whole point of a
        # server-side log versus the sanitized client response.
        assert "RuntimeError" in caplog.text
        assert "boom" in caplog.text
    finally:
        app.dependency_overrides.clear()
        Base.metadata.drop_all(engine)
