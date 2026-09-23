"""Integration Phase 10 — Customer Order Tracking.

Two guarantees this file locks in together:

1. As a real order moves through its full lifecycle (PLACED -> CONFIRMED ->
   PREPARING -> READY_FOR_PICKUP -> RIDER_ASSIGNED -> PICKED_UP ->
   OUT_FOR_DELIVERY -> DELIVERED), the customer's own GET endpoints
   (order detail and tracking) always reflect the current, correct state.
2. A second, unrelated customer can never see or act on the first
   customer's order through any customer-facing order endpoint — every one
   of them must treat someone else's order exactly like a nonexistent one
   (404), never a 403 that would at least confirm it exists, and never any
   leaked data.
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
from app.models.delivery_partner import ApprovalStatus, DeliveryPartner
from app.services.addresses import create_address


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


def test_customer_sees_every_lifecycle_status_and_a_second_customer_is_locked_out(engine):
    with Session(engine) as seed:
        owner = User(name="Owner", email="owner-p10@example.com", phone="9500000001", password_hash=hash_password("x"), role=UserRole.RESTAURANT_OWNER)
        customer_a = User(name="Customer A", email="custa-p10@example.com", phone="9500000002", password_hash=hash_password("x"), role=UserRole.CUSTOMER)
        customer_b = User(name="Customer B", email="custb-p10@example.com", phone="9500000003", password_hash=hash_password("x"), role=UserRole.CUSTOMER)
        rider = User(name="Rider", email="rider-p10@example.com", phone="9500000004", password_hash=hash_password("x"), role=UserRole.RIDER)
        seed.add_all([owner, customer_a, customer_b, rider])
        seed.commit()
        seed.add(DeliveryPartner(user_id=rider.id, approval_status=ApprovalStatus.APPROVED, is_online=True))
        seed.commit()

        restaurant = Restaurant(
            owner_id=owner.id, name="Chai House", phone="9876543210", address="Main Road",
            latitude=Decimal("12.1"), longitude=Decimal("77.1"),
            minimum_order=Decimal("0.00"), delivery_fee=Decimal("30.00"),
        )
        seed.add(restaurant)
        seed.commit()
        product = Product(restaurant_id=restaurant.id, name="Masala Chai", price=Decimal("40.00"))
        seed.add(product)
        seed.commit()
        product_id = product.id

        address = create_address(seed, customer_a.id, {
            "label": "Home", "recipient_name": "Customer A", "phone": "9500000002",
            "address_line": "7 Lake View Road", "city": "Bengaluru", "state": "Karnataka", "postal_code": "560002",
        })
        address_id = address.id

        owner_token = create_access_token(owner.id)
        customer_a_token = create_access_token(customer_a.id)
        customer_b_token = create_access_token(customer_b.id)
        rider_token = create_access_token(rider.id)

    owner_headers = {"Authorization": f"Bearer {owner_token}"}
    a_headers = {"Authorization": f"Bearer {customer_a_token}"}
    b_headers = {"Authorization": f"Bearer {customer_b_token}"}
    rider_headers = {"Authorization": f"Bearer {rider_token}"}

    with TestClient(app) as client:
        add_item = client.post(
            "/api/v1/customer/cart/items", headers=a_headers,
            json={"product_id": str(product_id), "quantity": 1},
        )
        assert add_item.status_code == 201

        place = client.post("/api/v1/customer/orders", headers=a_headers, json={"address_id": str(address_id)})
        assert place.status_code == 201
        order_id = place.json()["id"]

        def a_sees(expected_status):
            detail = client.get(f"/api/v1/customer/orders/{order_id}", headers=a_headers)
            assert detail.status_code == 200
            assert detail.json()["status"] == expected_status, f"expected {expected_status}, got {detail.json()['status']}"
            tracking = client.get(f"/api/v1/customer/orders/{order_id}/tracking", headers=a_headers)
            assert tracking.status_code == 200
            assert tracking.json()["order_status"] == expected_status

        # ---- PLACED ----
        a_sees("placed")

        # ---- CONFIRMED / PREPARING / READY_FOR_PICKUP (restaurant-driven) ----
        assert client.post(f"/api/v1/restaurant/orders/{order_id}/accept", headers=owner_headers).status_code == 200
        a_sees("confirmed")
        assert client.post(f"/api/v1/restaurant/orders/{order_id}/preparing", headers=owner_headers).status_code == 200
        a_sees("preparing")
        assert client.post(f"/api/v1/restaurant/orders/{order_id}/ready", headers=owner_headers).status_code == 200
        a_sees("ready_for_pickup")

        # ---- RIDER_ASSIGNED / PICKED_UP / OUT_FOR_DELIVERY / DELIVERED (rider-driven) ----
        assert client.post(f"/api/v1/rider/deliveries/{order_id}/accept", headers=rider_headers).status_code == 200
        a_sees("rider_assigned")
        assert client.post(f"/api/v1/rider/deliveries/{order_id}/pickup", headers=rider_headers).status_code == 200
        a_sees("picked_up")
        assert client.post(f"/api/v1/rider/deliveries/{order_id}/start", headers=rider_headers).status_code == 200
        a_sees("out_for_delivery")
        assert client.post(f"/api/v1/rider/deliveries/{order_id}/cod-collect", headers=rider_headers).status_code == 200
        assert client.post(f"/api/v1/rider/deliveries/{order_id}/complete", headers=rider_headers).status_code == 200
        a_sees("delivered")

        # ---- IDOR sweep: Customer B against Customer A's order, on every customer-order-scoped endpoint ----
        idor_checks = [
            ("GET", f"/api/v1/customer/orders/{order_id}", None),
            ("GET", f"/api/v1/customer/orders/{order_id}/tracking", None),
            ("POST", f"/api/v1/customer/orders/{order_id}/cancel", None),
            ("POST", f"/api/v1/customer/orders/{order_id}/reorder", None),
            ("GET", f"/api/v1/customer/orders/{order_id}/review", None),
            ("POST", f"/api/v1/customer/orders/{order_id}/review", {"restaurant_rating": 5, "delivery_rating": 5}),
            ("POST", f"/api/v1/customer/orders/{order_id}/payment", None),
        ]
        for method, path, json_body in idor_checks:
            response = client.request(method, path, headers=b_headers, json=json_body)
            assert response.status_code in (403, 404), f"{method} {path} leaked info with status {response.status_code}: {response.text}"
            # This codebase's established convention is 404 (never confirm existence) —
            # verified explicitly, not just "any refusal is fine".
            assert response.status_code == 404, f"{method} {path} returned {response.status_code}, expected the never-leak-existence 404"

        # Customer A's own order is completely untouched by any of Customer B's attempts.
        final = client.get(f"/api/v1/customer/orders/{order_id}", headers=a_headers)
        assert final.status_code == 200
        assert final.json()["status"] == "delivered"
        assert final.json()["cancelled_reason"] is None

        # Customer B's own order list is empty — B's attempts never created
        # a phantom order or leaked A's order into B's own view.
        b_list = client.get("/api/v1/customer/orders", headers=b_headers)
        assert b_list.status_code == 200
        assert b_list.json() == []
