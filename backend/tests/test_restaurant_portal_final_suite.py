"""Restaurant Owner Portal — Phase 20: final testing pass.

This is not a rewrite of the per-phase test files (test_restaurant_owner_auth,
test_restaurant_dashboard, test_restaurant_profile_settings,
test_restaurant_hours_and_status, test_restaurant_categories,
test_restaurant_products, test_restaurant_incoming_orders,
test_restaurant_order_decisions, test_restaurant_order_preparation,
test_restaurant_order_lifecycle_boundary, test_restaurant_security_audit,
test_integration_customer_restaurant_order_flow) — together those already
cover, and passingly so:

  - Authentication: login, logout, token refresh, unauthorized access, wrong role
      -> test_restaurant_owner_auth.py
  - Restaurant: profile, open/close, hours
      -> test_restaurant_profile_settings.py, test_restaurant_hours_and_status.py
  - Menu: categories, products, availability
      -> test_restaurant_categories.py, test_restaurant_products.py
  - Orders: receive, view, accept, reject, preparing, ready
      -> test_restaurant_incoming_orders.py, test_restaurant_order_decisions.py,
         test_restaurant_order_preparation.py
  - Security: owner isolation, API authorization, invalid status transitions
      -> test_restaurant_security_audit.py, test_restaurant_order_lifecycle_boundary.py
  - Financial (sales/pending earnings): test_restaurant_dashboard.py

This file closes the specific gaps that survey left: cancelled-order handling
from the restaurant's side (a customer-initiated cancellation, not a
restaurant one), IDOR/invalid-ID probing with malformed and well-formed-but-
foreign UUIDs, and decimal-exactness under values that would reveal a stray
float in the money path. "Commission" from the audit brief has no
corresponding feature anywhere in the codebase — no commission model, field,
rate, or endpoint was ever specified in Phases 1-19 — so there is nothing to
test; it's called out explicitly rather than silently skipped.
"""

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
from app.models import Coupon, DiscountType, Product, Restaurant, User, UserRole
from app.models.order import OrderStatus
from app.services.addresses import create_address
from app.services.cart import add_item, create_cart_for_user
from app.services.orders import cancel_order, create_order, transition_order_status


@pytest.fixture()
def engine():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)

    def override_get_db():
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    yield engine
    app.dependency_overrides.clear()
    Base.metadata.drop_all(engine)


def _owner(db, email="owner@example.com", phone="9000000001"):
    user = User(name="Owner", email=email, phone=phone, password_hash=hash_password("Passw0rd!"), role=UserRole.RESTAURANT_OWNER)
    db.add(user)
    db.commit()
    return user


def _restaurant(db, owner, name="Chai House", delivery_fee=Decimal("30.00")):
    restaurant = Restaurant(
        owner_id=owner.id, name=name, phone="9876543210", address="Main Road",
        latitude=Decimal("12.1"), longitude=Decimal("77.1"),
        minimum_order=Decimal("0.00"), delivery_fee=delivery_fee,
    )
    db.add(restaurant)
    db.commit()
    return restaurant


def _place_order(db, restaurant, price, quantity=1, name="Amit Sharma", suffix="1", coupon=None):
    customer = User(name=name, email=f"cust{suffix}@example.com", phone=f"92{suffix.zfill(8)}", password_hash="x", role=UserRole.CUSTOMER)
    db.add(customer)
    db.commit()
    product = Product(restaurant_id=restaurant.id, name="Item", price=price)
    db.add(product)
    db.commit()
    cart = create_cart_for_user(db, customer.id)
    add_item(db, cart, product.id, quantity)
    if coupon is not None:
        cart.coupon_id = coupon.id
        db.commit()
    address = create_address(db, customer.id, {
        "label": "Home", "recipient_name": name, "phone": "9999999999",
        "address_line": "15 Market Road", "city": "Bengaluru", "state": "Karnataka", "postal_code": "560001",
    })
    return create_order(db, customer, address.id)


def _http_setup():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)

    def override_get_db():
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    return engine


def _teardown(engine):
    app.dependency_overrides.clear()
    Base.metadata.drop_all(engine)


# --------------------------- Cancelled order handling ---------------------------


def test_customer_cancellation_is_visible_to_restaurant_and_locks_out_further_action():
    engine = _http_setup()
    try:
        with Session(engine) as seed:
            owner = _owner(seed)
            restaurant = _restaurant(seed, owner)
            order = _place_order(seed, restaurant, Decimal("100.00"), suffix="1")
            order_id = order.id
            customer_id = order.user_id
            owner_token = create_access_token(owner.id)

        with TestClient(app) as client:
            headers = {"Authorization": f"Bearer {owner_token}"}

            # Customer cancels their own still-PLACED order via the service
            # layer (the exact same path the customer-facing endpoint uses).
            with Session(engine) as db:
                cancel_order(db, customer_id, order_id, "Changed my mind")

            # The restaurant sees it as cancelled, not as a phantom pending order.
            order_view = client.get(f"/api/v1/restaurant/orders/{order_id}", headers=headers)
            assert order_view.status_code == 200
            assert order_view.json()["status"] == "cancelled"
            assert order_view.json()["cancelled_reason"] == "Changed my mind"

            pending = client.get("/api/v1/restaurant/orders?status=pending", headers=headers)
            assert pending.json() == []
            cancelled_bucket = client.get("/api/v1/restaurant/orders?status=cancelled", headers=headers)
            assert len(cancelled_bucket.json()) == 1
            assert cancelled_bucket.json()[0]["id"] == str(order_id)

            # The restaurant can no longer act on it at all — every
            # restaurant-side transition is now illegal from CANCELLED.
            assert client.post(f"/api/v1/restaurant/orders/{order_id}/accept", headers=headers).status_code == 409
            assert client.post(f"/api/v1/restaurant/orders/{order_id}/reject", headers=headers).status_code == 409
            assert client.post(f"/api/v1/restaurant/orders/{order_id}/preparing", headers=headers).status_code == 409
            assert client.post(f"/api/v1/restaurant/orders/{order_id}/ready", headers=headers).status_code == 409

            # And it must not count toward the dashboard's pending/preparing/ready buckets.
            dashboard = client.get("/api/v1/restaurant/dashboard", headers=headers)
            assert dashboard.json()["pending_orders_count"] == 0
            assert dashboard.json()["preparing_orders_count"] == 0
            assert dashboard.json()["ready_orders_count"] == 0
    finally:
        _teardown(engine)


def test_customer_cannot_cancel_once_restaurant_has_started_preparing():
    """Not a restaurant-portal bug to fix — confirms the existing customer-side
    rule (CUSTOMER_CANCELLABLE_STATUSES) still holds once the restaurant has
    moved the order past CONFIRMED, so the two portals can't race each other."""
    engine = _http_setup()
    try:
        with Session(engine) as seed:
            owner = _owner(seed)
            restaurant = _restaurant(seed, owner)
            order = _place_order(seed, restaurant, Decimal("100.00"), suffix="1")
            transition_order_status(seed, order, OrderStatus.CONFIRMED)
            transition_order_status(seed, order, OrderStatus.PREPARING)
            order_id = order.id
            customer_id = order.user_id

        from fastapi import HTTPException

        with Session(engine) as db:
            with pytest.raises(HTTPException) as exc:
                cancel_order(db, customer_id, order_id, "Too late")
            assert exc.value.status_code == 409
    finally:
        _teardown(engine)


# --------------------------- IDOR / invalid ID probing ---------------------------


def test_malformed_uuid_in_order_id_returns_422_not_500():
    engine = _http_setup()
    try:
        with Session(engine) as seed:
            owner = _owner(seed)
            _restaurant(seed, owner)
            token = create_access_token(owner.id)

        with TestClient(app) as client:
            headers = {"Authorization": f"Bearer {token}"}
            requests = (
                ("GET", "/api/v1/restaurant/orders/not-a-uuid"),
                ("POST", "/api/v1/restaurant/orders/not-a-uuid/accept"),
                ("POST", "/api/v1/restaurant/orders/not-a-uuid/reject"),
                ("GET", "/api/v1/restaurant/products/not-a-uuid"),
                ("GET", "/api/v1/restaurant/categories/not-a-uuid"),
            )
            for method, path in requests:
                response = client.request(method, path, headers=headers)
                assert response.status_code == 422, f"{method} {path} returned {response.status_code}"
    finally:
        _teardown(engine)


def test_well_formed_but_nonexistent_uuid_returns_404_not_500():
    engine = _http_setup()
    try:
        with Session(engine) as seed:
            owner = _owner(seed)
            _restaurant(seed, owner)
            token = create_access_token(owner.id)

        random_id = "00000000-0000-0000-0000-000000000000"
        with TestClient(app) as client:
            headers = {"Authorization": f"Bearer {token}"}
            assert client.get(f"/api/v1/restaurant/orders/{random_id}", headers=headers).status_code == 404
            assert client.get(f"/api/v1/restaurant/products/{random_id}", headers=headers).status_code == 404
            assert client.patch(
                f"/api/v1/restaurant/categories/{random_id}", headers=headers, json={"name": "x"}
            ).status_code == 404
    finally:
        _teardown(engine)


def test_idor_attempt_with_another_owners_real_id_is_rejected():
    """The specific IDOR shape: Owner A has a *real, valid* ID from Owner B's
    data (e.g. scraped from a shared link or guessed sequential-looking UUID)
    and tries it directly — must behave exactly like a nonexistent ID, never
    partially succeed."""
    engine = _http_setup()
    try:
        with Session(engine) as seed:
            owner_a = _owner(seed, "ownera@example.com", "9111111111")
            owner_b = _owner(seed, "ownerb@example.com", "9222222222")
            restaurant_a = _restaurant(seed, owner_a, "A's Diner")
            restaurant_b = _restaurant(seed, owner_b, "B's Diner")
            order_b = _place_order(seed, restaurant_b, Decimal("50.00"), suffix="1")
            order_b_id = order_b.id
            token_a = create_access_token(owner_a.id)

        with TestClient(app) as client:
            headers = {"Authorization": f"Bearer {token_a}"}
            assert client.get(f"/api/v1/restaurant/orders/{order_b_id}", headers=headers).status_code == 404
            assert client.post(f"/api/v1/restaurant/orders/{order_b_id}/accept", headers=headers).status_code == 404
    finally:
        _teardown(engine)


# --------------------------- Financial: decimal exactness ---------------------------


def test_order_totals_are_decimal_exact_not_float_drifted():
    """10.10 * 3 is 30.299999999999997 in binary float, but must be exactly
    30.30 as a Decimal all the way through subtotal -> total -> the API's
    JSON serialization (Pydantic renders Decimal as an exact string, not a
    float, so this also guards against a schema field ever being typed as
    `float` by mistake)."""
    engine = _http_setup()
    try:
        with Session(engine) as seed:
            owner = _owner(seed)
            restaurant = _restaurant(seed, owner, delivery_fee=Decimal("19.99"))
            order = _place_order(seed, restaurant, Decimal("10.10"), quantity=3, suffix="1")
            order_id = order.id
            assert order.subtotal == Decimal("30.30")
            assert order.total == Decimal("50.29")
            token = create_access_token(owner.id)

        with TestClient(app) as client:
            response = client.get(
                f"/api/v1/restaurant/orders/{order_id}", headers={"Authorization": f"Bearer {token}"}
            )
            body = response.json()
            assert body["subtotal"] == "30.30"
            assert body["total"] == "50.29"
    finally:
        _teardown(engine)


def test_fixed_discount_is_decimal_exact():
    engine = _http_setup()
    try:
        with Session(engine) as seed:
            owner = _owner(seed)
            restaurant = _restaurant(seed, owner, delivery_fee=Decimal("19.99"))
            coupon = Coupon(
                code="SAVE505", discount_type=DiscountType.FIXED, discount_value=Decimal("5.05"),
                min_order=Decimal("0.00"),
            )
            seed.add(coupon)
            seed.commit()
            order = _place_order(seed, restaurant, Decimal("10.10"), quantity=3, suffix="1", coupon=coupon)
            # subtotal 30.30 + delivery 19.99 - discount 5.05 = 45.24, exactly.
            assert order.discount == Decimal("5.05")
            assert order.total == Decimal("45.24")
    finally:
        _teardown(engine)


def test_dashboard_sales_aggregation_does_not_accumulate_float_drift():
    """Three delivered orders whose subtotals are individually float-drift-prone
    (10.10 * 3 = 30.30 each) must sum to exactly 90.90, not
    90.89999999999999 or 90.90000000000001 — this is the one place a stray
    `sum(...)` over floats instead of Decimals in the dashboard aggregation
    would actually surface."""
    engine = _http_setup()
    try:
        with Session(engine) as seed:
            owner = _owner(seed)
            restaurant = _restaurant(seed, owner)
            for suffix in ("1", "2", "3"):
                order = _place_order(seed, restaurant, Decimal("10.10"), quantity=3, suffix=suffix)
                transition_order_status(seed, order, OrderStatus.CONFIRMED)
                transition_order_status(seed, order, OrderStatus.PREPARING)
                transition_order_status(seed, order, OrderStatus.READY_FOR_PICKUP)
                transition_order_status(seed, order, OrderStatus.RIDER_ASSIGNED)
                transition_order_status(seed, order, OrderStatus.PICKED_UP)
                transition_order_status(seed, order, OrderStatus.OUT_FOR_DELIVERY)
                transition_order_status(seed, order, OrderStatus.DELIVERED)
            token = create_access_token(owner.id)

        with TestClient(app) as client:
            response = client.get(
                "/api/v1/restaurant/dashboard", headers={"Authorization": f"Bearer {token}"}
            )
            assert response.json()["today_sales"] == "90.90"
    finally:
        _teardown(engine)


def test_pending_earnings_sums_in_flight_orders_exactly():
    engine = _http_setup()
    try:
        with Session(engine) as seed:
            owner = _owner(seed)
            restaurant = _restaurant(seed, owner)
            _place_order(seed, restaurant, Decimal("10.10"), quantity=3, suffix="1")  # placed, in-flight
            second = _place_order(seed, restaurant, Decimal("10.10"), quantity=3, suffix="2")
            transition_order_status(seed, second, OrderStatus.CONFIRMED)  # still in-flight
            token = create_access_token(owner.id)

        with TestClient(app) as client:
            response = client.get(
                "/api/v1/restaurant/dashboard", headers={"Authorization": f"Bearer {token}"}
            )
            assert response.json()["pending_earnings"] == "60.60"
    finally:
        _teardown(engine)
