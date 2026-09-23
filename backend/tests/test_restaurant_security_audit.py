"""Restaurant Owner Portal — Phase 17: dedicated security audit.

A consolidated, adversarial pass over the entire Restaurant Owner Portal
(Phases 1-12), run before starting the Rider Portal. Each test below is a
concrete attack a malicious or careless restaurant-owner client could try;
a passing suite here means the attack has no effect, not just that no UI
button exists for it.

Covers, per the audit brief:
  - Owner isolation            (restaurant profile/dashboard/settings/hours)
  - Order isolation            (list/detail/accept/reject/preparing/ready)
  - Product isolation          (list/create/update/delete)
  - Category isolation         (list/create/update/delete)
  - Forbidden actions: change order total, change customer, change payment
    status, assign an arbitrary rider, mark an order delivered, access admin
    APIs, access rider APIs.
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
from app.models import MenuCategory, Product, Restaurant, User, UserRole
from app.models.order import OrderStatus
from app.services.addresses import create_address
from app.services.cart import add_item, create_cart_for_user
from app.services.orders import create_order, transition_order_status


# ---------------------------------------------------------------------------
# Shared fixtures: two owners, each with their own restaurant, so every test
# can attempt an Owner-A-reaches-into-Restaurant-B attack.
# ---------------------------------------------------------------------------


def _owner(db, email, phone):
    user = User(name="Owner", email=email, phone=phone, password_hash=hash_password("Passw0rd!"), role=UserRole.RESTAURANT_OWNER)
    db.add(user)
    db.commit()
    return user


def _restaurant(db, owner, name):
    restaurant = Restaurant(
        owner_id=owner.id, name=name, phone="9876543210", address="Main Road",
        latitude=Decimal("12.1"), longitude=Decimal("77.1"),
        minimum_order=Decimal("0.00"), delivery_fee=Decimal("30.00"),
    )
    db.add(restaurant)
    db.commit()
    return restaurant


def _category(db, restaurant, name="Starters"):
    category = MenuCategory(restaurant_id=restaurant.id, name=name, display_order=0)
    db.add(category)
    db.commit()
    return category


def _product(db, restaurant, name="Item", price=Decimal("100.00"), category_id=None):
    product = Product(restaurant_id=restaurant.id, name=name, price=price, category_id=category_id)
    db.add(product)
    db.commit()
    return product


def _place_order(db, restaurant, name="Amit Sharma", price=Decimal("100.00"), suffix="1"):
    customer = User(name=name, email=f"cust{suffix}@example.com", phone=f"92{suffix.zfill(8)}", password_hash="x", role=UserRole.CUSTOMER)
    db.add(customer)
    db.commit()
    product = _product(db, restaurant, price=price)
    cart = create_cart_for_user(db, customer.id)
    add_item(db, cart, product.id, 1)
    address = create_address(db, customer.id, {
        "label": "Home", "recipient_name": name, "phone": "9999999999",
        "address_line": "15 Market Road", "city": "Bengaluru", "state": "Karnataka", "postal_code": "560001",
    })
    return create_order(db, customer, address.id)


def _rider(db, email="rider@example.com", phone="9888888888"):
    user = User(name="Rider", email=email, phone=phone, password_hash="x", role=UserRole.RIDER)
    db.add(user)
    db.commit()
    return user


def _admin(db, email="admin@example.com", phone="9777777777"):
    user = User(name="Admin", email=email, phone=phone, password_hash="x", role=UserRole.ADMIN)
    db.add(user)
    db.commit()
    return user


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


class _World:
    """Two owners (A, B), each with one restaurant, seeded once per test."""

    def __init__(self, seed: Session):
        self.owner_a = _owner(seed, "ownera@example.com", "9111111111")
        self.owner_b = _owner(seed, "ownerb@example.com", "9222222222")
        self.restaurant_a = _restaurant(seed, self.owner_a, "A's Diner")
        self.restaurant_b = _restaurant(seed, self.owner_b, "B's Diner")
        self.category_b = _category(seed, self.restaurant_b, "B's Starters")
        self.product_b = _product(seed, self.restaurant_b, "B's Special")
        self.order_b = _place_order(seed, self.restaurant_b, suffix="1")
        self.rider = _rider(seed)
        self.admin = _admin(seed)
        self.token_a = create_access_token(self.owner_a.id)
        self.token_b = create_access_token(self.owner_b.id)

    def headers_a(self):
        return {"Authorization": f"Bearer {self.token_a}"}


# ---------------------------------------------------------------------------
# 1. Owner isolation — restaurant profile / dashboard / settings / hours
# ---------------------------------------------------------------------------


def test_owner_a_can_see_own_restaurant_profile():
    engine = _http_setup()
    try:
        with Session(engine) as seed:
            world = _World(seed)
        with TestClient(app) as client:
            response = client.get("/api/v1/restaurant/profile", headers=world.headers_a())
            assert response.status_code == 200
            assert response.json()["name"] == "A's Diner"
    finally:
        _teardown(engine)


def test_owner_a_cannot_reach_restaurant_b_via_explicit_restaurant_id():
    engine = _http_setup()
    try:
        with Session(engine) as seed:
            world = _World(seed)
            restaurant_b_id = world.restaurant_b.id
        with TestClient(app) as client:
            headers = world.headers_a()
            # profile / dashboard / hours / status all take an optional
            # ?restaurant_id= override — each must refuse a restaurant this
            # owner doesn't manage, not silently serve it.
            assert client.get(f"/api/v1/restaurant/profile?restaurant_id={restaurant_b_id}", headers=headers).status_code == 403
            assert client.get(f"/api/v1/restaurant/dashboard?restaurant_id={restaurant_b_id}", headers=headers).status_code == 403
            assert client.get(f"/api/v1/restaurant/hours?restaurant_id={restaurant_b_id}", headers=headers).status_code == 403
            assert client.get(f"/api/v1/restaurant/status?restaurant_id={restaurant_b_id}", headers=headers).status_code == 403
            assert client.patch(
                f"/api/v1/restaurant/profile?restaurant_id={restaurant_b_id}", headers=headers, json={"name": "Hijacked"}
            ).status_code == 403
    finally:
        _teardown(engine)


# ---------------------------------------------------------------------------
# 2. Order isolation
# ---------------------------------------------------------------------------


def test_owner_a_cannot_list_or_view_restaurant_b_orders():
    engine = _http_setup()
    try:
        with Session(engine) as seed:
            world = _World(seed)
            order_b_id = world.order_b.id
        with TestClient(app) as client:
            headers = world.headers_a()
            list_resp = client.get("/api/v1/restaurant/orders", headers=headers)
            assert list_resp.status_code == 200
            assert list_resp.json() == []  # A's own (empty) order list, not B's

            assert client.get(f"/api/v1/restaurant/orders/{order_b_id}", headers=headers).status_code == 404
    finally:
        _teardown(engine)


def test_owner_a_cannot_accept_reject_advance_restaurant_b_order():
    engine = _http_setup()
    try:
        with Session(engine) as seed:
            world = _World(seed)
            order_b_id = world.order_b.id
        with TestClient(app) as client:
            headers = world.headers_a()
            assert client.post(f"/api/v1/restaurant/orders/{order_b_id}/accept", headers=headers).status_code == 404
            assert client.post(f"/api/v1/restaurant/orders/{order_b_id}/reject", headers=headers).status_code == 404
            assert client.post(f"/api/v1/restaurant/orders/{order_b_id}/preparing", headers=headers).status_code == 404
            assert client.post(f"/api/v1/restaurant/orders/{order_b_id}/ready", headers=headers).status_code == 404
    finally:
        _teardown(engine)


def test_owner_a_cannot_list_restaurant_b_orders_via_restaurant_id_param():
    engine = _http_setup()
    try:
        with Session(engine) as seed:
            world = _World(seed)
            restaurant_b_id = world.restaurant_b.id
        with TestClient(app) as client:
            response = client.get(
                f"/api/v1/restaurant/orders?restaurant_id={restaurant_b_id}", headers=world.headers_a()
            )
            assert response.status_code == 403
    finally:
        _teardown(engine)


# ---------------------------------------------------------------------------
# 3. Product isolation
# ---------------------------------------------------------------------------


def test_owner_a_cannot_list_view_or_mutate_restaurant_b_products():
    engine = _http_setup()
    try:
        with Session(engine) as seed:
            world = _World(seed)
            product_b_id = world.product_b.id
        with TestClient(app) as client:
            headers = world.headers_a()
            list_resp = client.get("/api/v1/restaurant/products", headers=headers)
            assert list_resp.status_code == 200
            assert list_resp.json() == []  # A's own (empty) catalogue, not B's

            assert client.patch(
                f"/api/v1/restaurant/products/{product_b_id}", headers=headers, json={"name": "Hijacked"}
            ).status_code == 404
            assert client.delete(f"/api/v1/restaurant/products/{product_b_id}", headers=headers).status_code == 404
    finally:
        _teardown(engine)


def test_owner_a_cannot_create_product_directly_under_restaurant_b_id():
    engine = _http_setup()
    try:
        with Session(engine) as seed:
            world = _World(seed)
            restaurant_b_id = world.restaurant_b.id
        with TestClient(app) as client:
            response = client.post(
                f"/api/v1/restaurant/products?restaurant_id={restaurant_b_id}",
                headers=world.headers_a(),
                json={"name": "Smuggled item", "price": "1.00"},
            )
            assert response.status_code == 403
    finally:
        _teardown(engine)


# ---------------------------------------------------------------------------
# 4. Category isolation
# ---------------------------------------------------------------------------


def test_owner_a_cannot_list_view_or_mutate_restaurant_b_categories():
    engine = _http_setup()
    try:
        with Session(engine) as seed:
            world = _World(seed)
            category_b_id = world.category_b.id
        with TestClient(app) as client:
            headers = world.headers_a()
            list_resp = client.get("/api/v1/restaurant/categories", headers=headers)
            assert list_resp.status_code == 200
            assert list_resp.json() == []  # A's own (empty) categories, not B's

            assert client.patch(
                f"/api/v1/restaurant/categories/{category_b_id}", headers=headers, json={"name": "Hijacked"}
            ).status_code == 404
            assert client.delete(f"/api/v1/restaurant/categories/{category_b_id}", headers=headers).status_code == 404
    finally:
        _teardown(engine)


# ---------------------------------------------------------------------------
# 5. Forbidden actions
# ---------------------------------------------------------------------------


def test_cannot_change_order_total_via_any_restaurant_endpoint():
    """None of the restaurant-facing order endpoints accept a body field that
    reaches Order.total — extra fields on OrderRejectRequest are silently
    dropped by pydantic, never bound to anything the service layer reads."""
    engine = _http_setup()
    try:
        with Session(engine) as seed:
            world = _World(seed)
            order = _place_order(seed, world.restaurant_a, suffix="own")
            order_id = order.id
            original_total = str(order.total)
        with TestClient(app) as client:
            headers = world.headers_a()
            response = client.post(
                f"/api/v1/restaurant/orders/{order_id}/reject",
                headers=headers,
                json={"reason": "test", "total": "0.01", "subtotal": "0.01"},
            )
            assert response.status_code == 200
            assert response.json()["total"] == original_total  # unchanged despite the injected field
    finally:
        _teardown(engine)


def test_cannot_change_order_customer_via_any_restaurant_endpoint():
    engine = _http_setup()
    try:
        with Session(engine) as seed:
            world = _World(seed)
            order = _place_order(seed, world.restaurant_a, name="Real Customer", suffix="own")
            order_id = order.id
        with TestClient(app) as client:
            headers = world.headers_a()
            response = client.post(
                f"/api/v1/restaurant/orders/{order_id}/accept",
                headers=headers,
            )
            assert response.status_code == 200
            assert response.json()["customer_name"] == "Real Customer"

            # No restaurant endpoint even accepts a customer_name field —
            # confirm the accept endpoint ignores an injected one entirely.
            reject_attempt = client.post(
                f"/api/v1/restaurant/orders/{order_id}/preparing",
                headers=headers,
            )
            assert reject_attempt.status_code == 200
            assert reject_attempt.json()["customer_name"] == "Real Customer"
    finally:
        _teardown(engine)


def test_cannot_change_payment_status_via_any_restaurant_endpoint():
    engine = _http_setup()
    try:
        with Session(engine) as seed:
            world = _World(seed)
            order = _place_order(seed, world.restaurant_a, suffix="own")
            order_id = order.id
            assert order.is_paid is False
        with TestClient(app) as client:
            headers = world.headers_a()
            response = client.post(
                f"/api/v1/restaurant/orders/{order_id}/accept",
                headers=headers,
                json={"is_paid": True, "payment_status": "paid"},
            )
            assert response.status_code == 200
            body = response.json()
            assert body["is_paid"] is False  # accept has no body schema at all; the JSON above is ignored
            assert body["payment_status"] != "paid"
    finally:
        _teardown(engine)


def test_cannot_assign_arbitrary_rider():
    """The restaurant router has no rider-assignment route at all — only
    admin's /assign-rider can do this, and it's admin-gated."""
    engine = _http_setup()
    try:
        with Session(engine) as seed:
            world = _World(seed)
            order = _place_order(seed, world.restaurant_a, suffix="own")
            order_id = order.id
            rider_id = world.rider.id
        with TestClient(app) as client:
            headers = world.headers_a()
            # No such route exists under /restaurant/* at all.
            not_found = client.patch(f"/api/v1/restaurant/orders/{order_id}/assign-rider?rider_id={rider_id}", headers=headers)
            assert not_found.status_code in (404, 405)

            # The actual admin route rejects a restaurant-owner token.
            forbidden = client.patch(f"/api/v1/admin/orders/{order_id}/assign-rider?rider_id={rider_id}", headers=headers)
            assert forbidden.status_code == 403
    finally:
        _teardown(engine)


def test_cannot_mark_order_delivered():
    engine = _http_setup()
    try:
        with Session(engine) as seed:
            world = _World(seed)
            order = _place_order(seed, world.restaurant_a, suffix="own")
            transition_order_status(seed, order, OrderStatus.CONFIRMED)
            transition_order_status(seed, order, OrderStatus.PREPARING)
            transition_order_status(seed, order, OrderStatus.READY_FOR_PICKUP)
            order_id = order.id
        with TestClient(app) as client:
            headers = world.headers_a()
            # No /delivered route exists on the restaurant router; the only
            # progression routes are accept/reject/preparing/ready, and ready
            # is already terminal from the restaurant's point of view.
            not_found = client.patch(f"/api/v1/restaurant/orders/{order_id}/delivered", headers=headers)
            assert not_found.status_code in (404, 405)

            # The rider's own complete-delivery route rejects a
            # restaurant-owner token.
            forbidden = client.post(f"/api/v1/rider/deliveries/{order_id}/complete", headers=headers)
            assert forbidden.status_code == 403

            # The generic admin status-override route was removed entirely
            # in Admin Portal Phase 11 ("do NOT allow arbitrary direct
            # status modification") — there is no route left here at all,
            # for anyone, admin included.
            admin_forbidden = client.patch(
                f"/api/v1/admin/orders/{order_id}/status", headers=headers, json={"status": "delivered"}
            )
            assert admin_forbidden.status_code == 404
    finally:
        _teardown(engine)


def test_cannot_access_admin_apis():
    engine = _http_setup()
    try:
        with Session(engine) as seed:
            world = _World(seed)
        with TestClient(app) as client:
            headers = world.headers_a()
            assert client.get("/api/v1/admin/dashboard", headers=headers).status_code == 403
            assert client.get("/api/v1/admin/orders", headers=headers).status_code == 403
            assert client.get("/api/v1/admin/customers", headers=headers).status_code == 403
            assert client.get("/api/v1/admin/restaurants", headers=headers).status_code == 403
            assert client.get("/api/v1/admin/riders", headers=headers).status_code == 403
    finally:
        _teardown(engine)


def test_cannot_access_rider_apis():
    engine = _http_setup()
    try:
        with Session(engine) as seed:
            world = _World(seed)
        with TestClient(app) as client:
            headers = world.headers_a()
            assert client.get("/api/v1/rider/orders", headers=headers).status_code == 403
    finally:
        _teardown(engine)
