"""Admin Portal — Phase 27: Complete Order Lifecycle Test.

Runs the exact lifecycle diagrammed in this phase's own brief, end to end,
through real HTTP calls on every role's own portal (never a service-layer
shortcut):

    CUSTOMER places -> RESTAURANT accepts/prepares/readies ->
    RIDER accepts/picks up/starts/delivers -> DELIVERED

At every single node of that diagram, this asserts that Customer,
Restaurant, Rider, and Admin all report *consistent* information through
their own respective endpoints — not just that the backend's internal
state changed. This goes one step further than
test_admin_cross_role_data_integrity.py's own (checkpoint-based) order
test: every node in the diagram gets a full four-way consistency check,
and the test closes by confirming Admin's own order-detail view exposes
the complete, correctly-ordered status history end to end.
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
from app.models import ApprovalStatus, DeliveryPartner, Product, Restaurant, User, UserRole


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


def test_complete_order_lifecycle_consistent_across_all_four_roles(engine):
    # ------------------------------------------------------------------
    # Setup: Restaurant Owner + Restaurant + Product seeded directly (not
    # self-registerable); Customer and Rider created through the real
    # registration endpoint; Admin seeded directly (also not
    # self-registerable). Rider approval seeded directly too — this test
    # is about lifecycle *consistency*, not re-proving Phase 7-9's own
    # onboarding workflow.
    # ------------------------------------------------------------------
    with Session(engine) as seed:
        owner = User(name="Owner P27", email="p27-owner@example.com", phone="9300000001", password_hash=hash_password("x"), role=UserRole.RESTAURANT_OWNER)
        admin = User(name="Admin P27", email="p27-admin@example.com", phone="9300000002", password_hash=hash_password("x"), role=UserRole.ADMIN)
        seed.add_all([owner, admin])
        seed.commit()

        restaurant = Restaurant(
            owner_id=owner.id, name="Chai House P27", phone="9876500000", address="Main Road",
            latitude=Decimal("12.9716"), longitude=Decimal("77.5946"),
            minimum_order=Decimal("0.00"), delivery_fee=Decimal("35.00"),
        )
        seed.add(restaurant)
        seed.commit()

        product = Product(restaurant_id=restaurant.id, name="Masala Dosa", price=Decimal("120.00"))
        seed.add(product)
        seed.commit()
        product_id = str(product.id)
        owner_token = create_access_token(owner.id)
        admin_token = create_access_token(admin.id)

    with TestClient(app) as client:
        owner_headers = {"Authorization": f"Bearer {owner_token}"}
        admin_headers = {"Authorization": f"Bearer {admin_token}"}

        register_customer = client.post(
            "/api/v1/auth/register",
            json={"name": "Customer P27", "email": "p27-customer@example.com", "password": "secure-pass-123", "phone": "9300000010", "role": "CUSTOMER"},
        )
        assert register_customer.status_code == 201
        customer_token = client.post("/api/v1/auth/login", json={"email": "p27-customer@example.com", "password": "secure-pass-123"}).json()["access_token"]
        customer_headers = {"Authorization": f"Bearer {customer_token}"}

        register_rider = client.post(
            "/api/v1/auth/register",
            json={"name": "Rider P27", "email": "p27-rider@example.com", "password": "secure-pass-123", "phone": "9300000011", "role": "RIDER"},
        )
        assert register_rider.status_code == 201
        rider_token = client.post("/api/v1/auth/login", json={"email": "p27-rider@example.com", "password": "secure-pass-123"}).json()["access_token"]
        rider_headers = {"Authorization": f"Bearer {rider_token}"}
        rider_id = client.get("/api/v1/auth/me", headers=rider_headers).json()["id"]

        with Session(engine) as db:
            from uuid import UUID

            db.add(DeliveryPartner(user_id=UUID(rider_id), approval_status=ApprovalStatus.APPROVED, is_online=True))
            db.commit()

        def consistent_status(order_id: str, expected: str, *, restaurant_visible: bool = True):
            """Fetches this order through every role's own view and
            asserts they all agree it's at `expected`. Rider is only
            checked once assigned — before that, there is no rider
            endpoint that could report this order's status at all."""
            customer_view = client.get(f"/api/v1/customer/orders/{order_id}", headers=customer_headers)
            assert customer_view.status_code == 200
            assert customer_view.json()["status"] == expected, ("customer", expected, customer_view.json()["status"])

            admin_view = client.get(f"/api/v1/admin/orders/{order_id}", headers=admin_headers)
            assert admin_view.status_code == 200
            assert admin_view.json()["status"] == expected, ("admin", expected, admin_view.json()["status"])
            assert admin_view.json()["id"] == order_id

            if restaurant_visible:
                restaurant_view = client.get(f"/api/v1/restaurant/orders/{order_id}", headers=owner_headers)
                assert restaurant_view.status_code == 200
                assert restaurant_view.json()["status"] == expected, ("restaurant", expected, restaurant_view.json()["status"])

        # ------------------------------------------------------------------
        # CUSTOMER -> Place Order -> PLACED
        # ------------------------------------------------------------------
        address = client.post(
            "/api/v1/customer/addresses", headers=customer_headers,
            json={
                "label": "Home", "recipient_name": "Customer P27", "phone": "9300000010",
                "address_line": "42 MG Road", "city": "Bengaluru", "state": "Karnataka", "postal_code": "560001",
                "latitude": "12.9750", "longitude": "77.6050",
            },
        )
        assert address.status_code == 201
        address_id = address.json()["id"]

        client.post("/api/v1/customer/cart/items", headers=customer_headers, json={"product_id": product_id, "quantity": 1})
        place = client.post("/api/v1/customer/orders", headers=customer_headers, json={"address_id": address_id})
        assert place.status_code == 201
        order = place.json()
        order_id = order["id"]
        assert order["status"] == "placed"
        assert order["total"] == "155.00"

        consistent_status(order_id, "placed")

        incoming = client.get("/api/v1/restaurant/orders?status=pending", headers=owner_headers)
        assert any(o["id"] == order_id for o in incoming.json())

        # ------------------------------------------------------------------
        # RESTAURANT -> Accept -> CONFIRMED
        # ------------------------------------------------------------------
        accept = client.post(f"/api/v1/restaurant/orders/{order_id}/accept", headers=owner_headers)
        assert accept.status_code == 200
        assert accept.json()["status"] == "confirmed"
        consistent_status(order_id, "confirmed")

        # ------------------------------------------------------------------
        # RESTAURANT -> Prepare -> PREPARING
        # ------------------------------------------------------------------
        preparing = client.post(f"/api/v1/restaurant/orders/{order_id}/preparing", headers=owner_headers)
        assert preparing.status_code == 200
        assert preparing.json()["status"] == "preparing"
        consistent_status(order_id, "preparing")

        # ------------------------------------------------------------------
        # RESTAURANT -> Ready -> READY_FOR_PICKUP
        # ------------------------------------------------------------------
        ready = client.post(f"/api/v1/restaurant/orders/{order_id}/ready", headers=owner_headers)
        assert ready.status_code == 200
        assert ready.json()["status"] == "ready_for_pickup"
        consistent_status(order_id, "ready_for_pickup")

        # The moment it becomes available, the rider role gains its own
        # first view of this order — as an unclaimed opportunity, not yet
        # assigned to them by id.
        available = client.get("/api/v1/rider/deliveries/available", headers=rider_headers)
        assert any(d["order_id"] == order_id for d in available.json())

        admin_assignments = client.get("/api/v1/admin/delivery-assignments?status=PENDING", headers=admin_headers)
        assert any(a["order_id"] == order_id for a in admin_assignments.json()["items"])

        # ------------------------------------------------------------------
        # RIDER -> Accept -> ACCEPTED (assignment) / RIDER_ASSIGNED (order)
        # ------------------------------------------------------------------
        rider_accept = client.post(f"/api/v1/rider/deliveries/{order_id}/accept", headers=rider_headers)
        assert rider_accept.status_code == 200
        assert rider_accept.json()["status"] == "rider_assigned"
        consistent_status(order_id, "rider_assigned")

        rider_view = client.get(f"/api/v1/rider/deliveries/{order_id}", headers=rider_headers)
        assert rider_view.status_code == 200
        assert rider_view.json()["status"] == "rider_assigned"
        assert rider_view.json()["assignment_status"] == "ACCEPTED"

        admin_order = client.get(f"/api/v1/admin/orders/{order_id}", headers=admin_headers)
        assert admin_order.json()["rider_name"] == "Rider P27"

        admin_assignment_list = client.get(f"/api/v1/admin/delivery-assignments?status=ACCEPTED", headers=admin_headers)
        matching_assignment = next(a for a in admin_assignment_list.json()["items"] if a["order_id"] == order_id)
        assignment_id = matching_assignment["id"]
        admin_assignment_detail = client.get(f"/api/v1/admin/delivery-assignments/{assignment_id}", headers=admin_headers)
        assert admin_assignment_detail.json()["rider_id"] == rider_id
        assert admin_assignment_detail.json()["status"] == "ACCEPTED"

        # ------------------------------------------------------------------
        # RIDER -> Pickup -> PICKED_UP
        # ------------------------------------------------------------------
        pickup = client.post(f"/api/v1/rider/deliveries/{order_id}/pickup", headers=rider_headers)
        assert pickup.status_code == 200
        assert pickup.json()["status"] == "picked_up"
        consistent_status(order_id, "picked_up")

        rider_view = client.get(f"/api/v1/rider/deliveries/{order_id}", headers=rider_headers)
        assert rider_view.json()["assignment_status"] == "PICKED_UP"

        admin_assignment_detail = client.get(f"/api/v1/admin/delivery-assignments/{assignment_id}", headers=admin_headers)
        assert admin_assignment_detail.json()["status"] == "PICKED_UP"
        assert admin_assignment_detail.json()["picked_up_at"] is not None

        # ------------------------------------------------------------------
        # RIDER -> Start -> OUT_FOR_DELIVERY
        # ------------------------------------------------------------------
        start = client.post(f"/api/v1/rider/deliveries/{order_id}/start", headers=rider_headers)
        assert start.status_code == 200
        assert start.json()["status"] == "out_for_delivery"
        consistent_status(order_id, "out_for_delivery")

        rider_view = client.get(f"/api/v1/rider/deliveries/{order_id}", headers=rider_headers)
        assert rider_view.json()["assignment_status"] == "OUT_FOR_DELIVERY"

        admin_assignment_detail = client.get(f"/api/v1/admin/delivery-assignments/{assignment_id}", headers=admin_headers)
        assert admin_assignment_detail.json()["status"] == "OUT_FOR_DELIVERY"

        # Cash collected before completion, since this real order (placed
        # the only way a real customer actually can today) is COD.
        cod_collect = client.post(f"/api/v1/rider/deliveries/{order_id}/cod-collect", headers=rider_headers)
        assert cod_collect.status_code == 200
        payment_id = cod_collect.json()["payment_id"]

        # ------------------------------------------------------------------
        # RIDER -> Deliver -> DELIVERED
        # ------------------------------------------------------------------
        complete = client.post(f"/api/v1/rider/deliveries/{order_id}/complete", headers=rider_headers)
        assert complete.status_code == 200
        assert complete.json()["status"] == "delivered"
        consistent_status(order_id, "delivered")

        rider_view = client.get(f"/api/v1/rider/deliveries/{order_id}", headers=rider_headers)
        assert rider_view.json()["assignment_status"] == "DELIVERED"

        admin_assignment_detail = client.get(f"/api/v1/admin/delivery-assignments/{assignment_id}", headers=admin_headers)
        assert admin_assignment_detail.json()["status"] == "DELIVERED"
        assert admin_assignment_detail.json()["delivered_at"] is not None

        admin_payment = client.get(f"/api/v1/admin/payments/{payment_id}", headers=admin_headers)
        assert admin_payment.status_code == 200
        assert admin_payment.json()["status"] == "PAID"
        assert Decimal(admin_payment.json()["amount"]) == Decimal("155.00")

        # ------------------------------------------------------------------
        # Final check: Admin must be able to see the *complete* lifecycle,
        # not just its current state — the full, correctly-ordered
        # status history, exactly matching every arrow in this phase's
        # own diagram.
        # ------------------------------------------------------------------
        admin_final = client.get(f"/api/v1/admin/orders/{order_id}", headers=admin_headers)
        assert admin_final.status_code == 200
        history_statuses = [entry["status"] for entry in admin_final.json()["status_history"]]
        assert history_statuses == [
            "placed", "confirmed", "preparing", "ready_for_pickup",
            "rider_assigned", "picked_up", "out_for_delivery", "delivered",
        ]

        # And every other role's own final view still agrees, one last time.
        assert client.get(f"/api/v1/customer/orders/{order_id}", headers=customer_headers).json()["status"] == "delivered"
        assert client.get(f"/api/v1/restaurant/orders/{order_id}", headers=owner_headers).json()["status"] == "delivered"
        assert client.get(f"/api/v1/rider/deliveries/{order_id}", headers=rider_headers).json()["status"] == "delivered"
