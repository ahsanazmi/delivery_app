"""Restaurant Owner Portal — Phase 12: complete order lifecycle visibility, with
the restaurant explicitly locked out of rider-owned status transitions.

The restaurant-facing router only ever exposes accept/reject/preparing/ready
(see app/api/v1/restaurant/orders.py) — there is no route through which a
RESTAURANT_OWNER can reach RIDER_ASSIGNED, PICKED_UP, OUT_FOR_DELIVERY, or
DELIVERED. These tests pin that down as a regression guard: a restaurant
owner hitting the rider's pickup/deliver endpoints, or the admin's generic
status-override endpoint, must be rejected with 403, not merely "no button
in the UI for it."
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
from app.models import Product, Restaurant, User, UserRole
from app.models.order import OrderStatus
from app.services.addresses import create_address
from app.services.cart import add_item, create_cart_for_user
from app.services.orders import create_order, transition_order_status


@pytest.fixture()
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    Base.metadata.drop_all(engine)


def _owner(db, email="owner@example.com", phone="9000000001"):
    user = User(name="Owner", email=email, phone=phone, password_hash=hash_password("Passw0rd!"), role=UserRole.RESTAURANT_OWNER)
    db.add(user)
    db.commit()
    return user


def _restaurant(db, owner, name="Chai House"):
    restaurant = Restaurant(
        owner_id=owner.id, name=name, phone="9876543210", address="Main Road",
        latitude=Decimal("12.1"), longitude=Decimal("77.1"),
        minimum_order=Decimal("0.00"), delivery_fee=Decimal("30.00"),
    )
    db.add(restaurant)
    db.commit()
    return restaurant


def _place_order(db, restaurant, name="Amit Sharma", price=Decimal("100.00"), suffix="1"):
    customer = User(name=name, email=f"cust{suffix}@example.com", phone=f"92{suffix.zfill(8)}", password_hash="x", role=UserRole.CUSTOMER)
    db.add(customer)
    db.commit()
    product = Product(restaurant_id=restaurant.id, name="Item", price=price)
    db.add(product)
    db.commit()
    cart = create_cart_for_user(db, customer.id)
    add_item(db, cart, product.id, 1)
    address = create_address(db, customer.id, {
        "label": "Home", "recipient_name": name, "phone": "9999999999",
        "address_line": "15 Market Road", "city": "Bengaluru", "state": "Karnataka", "postal_code": "560001",
    })
    return create_order(db, customer, address.id)


def _ready_order(db, restaurant, suffix="1"):
    order = _place_order(db, restaurant, suffix=suffix)
    transition_order_status(db, order, OrderStatus.CONFIRMED)
    transition_order_status(db, order, OrderStatus.PREPARING)
    transition_order_status(db, order, OrderStatus.READY_FOR_PICKUP)
    return order


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


def test_restaurant_router_exposes_no_rider_stage_endpoints():
    """A restaurant owner has no route at all for rider-assigned/picked-up/
    out-for-delivery/delivered — those verbs simply don't exist on this router."""
    from app.api.v1.restaurant import orders as restaurant_orders_module

    paths = {route.path for route in restaurant_orders_module.router.routes}
    assert paths == {
        "/orders",
        "/orders/{order_id}",
        "/orders/{order_id}/accept",
        "/orders/{order_id}/reject",
        "/orders/{order_id}/preparing",
        "/orders/{order_id}/ready",
    }


def test_restaurant_owner_cannot_call_riders_pickup_endpoint():
    engine = _http_setup()
    try:
        with Session(engine) as seed:
            owner = _owner(seed)
            restaurant = _restaurant(seed, owner)
            order = _ready_order(seed, restaurant, suffix="1")
            order_id = order.id
            owner_token = create_access_token(owner.id)

        with TestClient(app) as client:
            response = client.post(
                f"/api/v1/rider/deliveries/{order_id}/pickup", headers={"Authorization": f"Bearer {owner_token}"}
            )
            assert response.status_code == 403
    finally:
        _teardown(engine)


def test_restaurant_owner_cannot_call_riders_deliver_endpoint():
    engine = _http_setup()
    try:
        with Session(engine) as seed:
            owner = _owner(seed)
            restaurant = _restaurant(seed, owner)
            order = _ready_order(seed, restaurant, suffix="1")
            order_id = order.id
            owner_token = create_access_token(owner.id)

        with TestClient(app) as client:
            response = client.post(
                f"/api/v1/rider/deliveries/{order_id}/complete", headers={"Authorization": f"Bearer {owner_token}"}
            )
            assert response.status_code == 403
    finally:
        _teardown(engine)


def test_admin_status_override_route_no_longer_exists():
    """Admin Portal Phase 11 removed PATCH /admin/orders/{id}/status
    entirely ("do NOT allow arbitrary direct status modification") — there
    is no route left at this path for anyone, not even an admin. The one
    transition it enabled with a clear business rule (cancellation) now has
    its own explicit, audited action: POST /admin/orders/{id}/cancel."""
    engine = _http_setup()
    try:
        with Session(engine) as seed:
            owner = _owner(seed)
            restaurant = _restaurant(seed, owner)
            order = _ready_order(seed, restaurant, suffix="1")
            order_id = order.id
            owner_token = create_access_token(owner.id)

        with TestClient(app) as client:
            response = client.patch(
                f"/api/v1/admin/orders/{order_id}/status",
                headers={"Authorization": f"Bearer {owner_token}"},
                json={"status": "picked_up"},
            )
            assert response.status_code == 404
    finally:
        _teardown(engine)


def test_customer_and_admin_see_every_restaurant_driven_status_change_live():
    """Integration Phase 6 — as the restaurant owner walks an order through
    PLACED -> CONFIRMED -> PREPARING -> READY_FOR_PICKUP, both the customer
    and an admin must see each new status immediately, from the same
    underlying Order row (see transition_order_status's single choke point)."""
    engine = _http_setup()
    try:
        with Session(engine) as seed:
            owner = _owner(seed)
            restaurant = _restaurant(seed, owner)
            order = _place_order(seed, restaurant, suffix="1")
            order_id = order.id
            owner_token = create_access_token(owner.id)
            customer_token = create_access_token(order.user_id)
            admin = User(name="Admin", email="admin-p6@example.com", phone="9500000001", password_hash=hash_password("x"), role=UserRole.ADMIN)
            seed.add(admin)
            seed.commit()
            admin_token = create_access_token(admin.id)

        owner_headers = {"Authorization": f"Bearer {owner_token}"}
        customer_headers = {"Authorization": f"Bearer {customer_token}"}
        admin_headers = {"Authorization": f"Bearer {admin_token}"}

        with TestClient(app) as client:
            steps = [
                (f"/api/v1/restaurant/orders/{order_id}/accept", "confirmed"),
                (f"/api/v1/restaurant/orders/{order_id}/preparing", "preparing"),
                (f"/api/v1/restaurant/orders/{order_id}/ready", "ready_for_pickup"),
            ]
            for path, expected_status in steps:
                action = client.post(path, headers=owner_headers)
                assert action.status_code == 200
                assert action.json()["status"] == expected_status

                customer_view = client.get(f"/api/v1/customer/orders/{order_id}", headers=customer_headers)
                assert customer_view.json()["status"] == expected_status

                admin_view = client.get(f"/api/v1/admin/orders/{order_id}", headers=admin_headers)
                assert admin_view.json()["status"] == expected_status
    finally:
        _teardown(engine)


def test_restaurant_owner_cannot_use_admin_assign_rider():
    engine = _http_setup()
    try:
        with Session(engine) as seed:
            owner = _owner(seed)
            restaurant = _restaurant(seed, owner)
            order = _ready_order(seed, restaurant, suffix="1")
            order_id = order.id
            owner_token = create_access_token(owner.id)

        with TestClient(app) as client:
            response = client.patch(
                f"/api/v1/admin/orders/{order_id}/assign-rider?rider_id={owner.id}",
                headers={"Authorization": f"Bearer {owner_token}"},
            )
            assert response.status_code == 403
    finally:
        _teardown(engine)
