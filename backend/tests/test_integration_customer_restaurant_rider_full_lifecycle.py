"""Phase 26 — Customer <-> Restaurant <-> Rider full integration test.

The single most important integration test in the whole project: three real
accounts (Customer A, Restaurant Owner A, Rider A), driven entirely through
real HTTP calls on each portal's own endpoints — never a direct service-layer
shortcut — through the complete order lifecycle exactly as diagrammed in the
phase brief:

    CUSTOMER places -> RESTAURANT accepts/prepares/readies ->
    RIDER accepts/picks up/starts/delivers -> DELIVERED

At every single arrow, this asserts that all three roles who can see the
order (or, before assignment, would-be riders) observe the *same* status
through their own portal's endpoints — not just that the backend's internal
state changed, but that every documented consumer of that state agrees.

Customer A and Rider A are created through the real POST /auth/register +
POST /auth/login endpoints (both self-registerable roles) — genuinely "real
test accounts," not direct DB rows standing in for them. Restaurant Owner A
is seeded directly, matching Phase 18's existing customer<->restaurant
integration test precedent (RESTAURANT_OWNER isn't a self-registerable role
in this system).
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


def test_full_customer_restaurant_rider_lifecycle_visible_to_every_role(engine):
    # ------------------------------------------------------------------
    # Setup: seed Restaurant Owner A + Restaurant A + a product directly
    # (not self-registerable), and create real Customer A / Rider A
    # accounts through the actual registration endpoint.
    # ------------------------------------------------------------------
    with Session(engine) as seed:
        owner = User(
            name="Owner A", email="owner-a@example.com", phone="9100000001",
            password_hash=hash_password("Passw0rd!"), role=UserRole.RESTAURANT_OWNER,
        )
        seed.add(owner)
        seed.commit()

        restaurant = Restaurant(
            owner_id=owner.id, name="Chai House", phone="9876543210", address="Main Road",
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

    with TestClient(app) as client:
        owner_headers = {"Authorization": f"Bearer {owner_token}"}

        # --- Real test accounts: Customer A and Rider A, via real registration ---
        register_customer = client.post(
            "/api/v1/auth/register",
            json={
                "name": "Customer A", "email": "customer-a@example.com", "password": "secure-pass-123",
                "phone": "9100000002", "role": "CUSTOMER",
            },
        )
        assert register_customer.status_code == 201
        customer_login = client.post(
            "/api/v1/auth/login", json={"email": "customer-a@example.com", "password": "secure-pass-123"}
        )
        assert customer_login.status_code == 200
        customer_token = customer_login.json()["access_token"]
        customer_headers = {"Authorization": f"Bearer {customer_token}"}
        customer_id = client.get("/api/v1/auth/me", headers=customer_headers).json()["id"]

        register_rider = client.post(
            "/api/v1/auth/register",
            json={
                "name": "Rider A", "email": "rider-a@example.com", "password": "secure-pass-123",
                "phone": "9100000003", "role": "RIDER",
            },
        )
        assert register_rider.status_code == 201
        rider_login = client.post(
            "/api/v1/auth/login", json={"email": "rider-a@example.com", "password": "secure-pass-123"}
        )
        assert rider_login.status_code == 200
        rider_token = rider_login.json()["access_token"]
        rider_headers = {"Authorization": f"Bearer {rider_token}"}
        rider_id = client.get("/api/v1/auth/me", headers=rider_headers).json()["id"]

        # Rider A must be approved, fully documented, vehicle-registered, and
        # online before they're eligible for anything — the exact same
        # onboarding sequence Phases 3-7 built and every rider test since
        # has used, exercised here for real against a genuinely fresh account.
        admin = User(name="Admin", email="admin-p26@example.com", phone="9100000099", password_hash=hash_password("x"), role=UserRole.ADMIN)
        with Session(engine) as db:
            db.add(admin)
            db.commit()
            admin_token = create_access_token(admin.id)
        admin_headers = {"Authorization": f"Bearer {admin_token}"}

        approve = client.patch(
            f"/api/v1/admin/riders/{rider_id}/verification", headers=admin_headers, json={"approval_status": "APPROVED"}
        )
        assert approve.status_code == 200
        for doc_type in ("DRIVING_LICENSE", "VEHICLE_REGISTRATION", "IDENTITY_DOCUMENT", "PROFILE_PHOTO"):
            created = client.post(
                "/api/v1/rider/documents", headers=rider_headers,
                json={"document_type": doc_type, "document_url": f"https://example.com/{doc_type.lower()}.jpg"},
            ).json()
            review = client.patch(
                f"/api/v1/admin/riders/{rider_id}/documents/{created['id']}",
                headers=admin_headers, json={"verification_status": "APPROVED"},
            )
            assert review.status_code == 200
        vehicle = client.patch(
            "/api/v1/rider/vehicle", headers=rider_headers,
            json={"vehicle_type": "BIKE", "vehicle_number": "KA01AB1234"},
        )
        assert vehicle.status_code == 200
        go_online = client.patch("/api/v1/rider/status", headers=rider_headers, json={"is_online": True})
        assert go_online.status_code == 200
        assert go_online.json()["is_online"] is True

        # ------------------------------------------------------------------
        # CUSTOMER: place the order through the real cart/checkout path.
        # ------------------------------------------------------------------
        address = client.post(
            "/api/v1/customer/addresses", headers=customer_headers,
            json={
                "label": "Home", "recipient_name": "Customer A", "phone": "9100000002",
                "address_line": "42 MG Road", "city": "Bengaluru", "state": "Karnataka", "postal_code": "560001",
                "latitude": "12.9750", "longitude": "77.6050",
            },
        )
        assert address.status_code == 201
        address_id = address.json()["id"]

        add_item = client.post(
            "/api/v1/customer/cart/items", headers=customer_headers,
            json={"product_id": product_id, "quantity": 1},
        )
        assert add_item.status_code == 201

        # payment_method is COD-only at this real endpoint today (see
        # CustomerOrderCreate) — online payment isn't yet exposed to a real
        # customer checkout, so this genuine end-to-end flow is a COD order,
        # which means the rider must also collect cash (Phase 16) before
        # they can mark it delivered (Phase 17) later in this same test.
        place = client.post(
            "/api/v1/customer/orders", headers=customer_headers,
            json={"address_id": address_id},
        )
        assert place.status_code == 201
        order = place.json()
        order_id = order["id"]
        assert order["status"] == "placed"
        assert order["payment_method"] == "cod"
        assert order["total"] == "155.00"  # 120 + 35 delivery fee

        # ------------------------------------------------------------------
        # RESTAURANT: accept -> CONFIRMED. Customer must see it immediately.
        # ------------------------------------------------------------------
        incoming = client.get("/api/v1/restaurant/orders?status=pending", headers=owner_headers)
        assert incoming.status_code == 200
        assert len(incoming.json()) == 1
        assert incoming.json()[0]["id"] == order_id

        accept = client.post(f"/api/v1/restaurant/orders/{order_id}/accept", headers=owner_headers)
        assert accept.status_code == 200
        assert accept.json()["status"] == "confirmed"

        customer_view = client.get(f"/api/v1/customer/orders/{order_id}", headers=customer_headers)
        assert customer_view.json()["status"] == "confirmed"
        tracking = client.get(f"/api/v1/customer/orders/{order_id}/tracking", headers=customer_headers)
        assert tracking.json()["order_status"] == "confirmed"
        assert tracking.json()["assignment_status"] == "unassigned"

        # ------------------------------------------------------------------
        # RESTAURANT: prepare -> PREPARING.
        # ------------------------------------------------------------------
        preparing = client.post(f"/api/v1/restaurant/orders/{order_id}/preparing", headers=owner_headers)
        assert preparing.status_code == 200
        assert preparing.json()["status"] == "preparing"

        customer_view = client.get(f"/api/v1/customer/orders/{order_id}", headers=customer_headers)
        assert customer_view.json()["status"] == "preparing"

        # ------------------------------------------------------------------
        # RESTAURANT: ready -> READY_FOR_PICKUP. This is the moment Rider A
        # should see it appear as an available delivery — and no one else's
        # rider account should, since this whole test only ever creates one.
        # ------------------------------------------------------------------
        ready = client.post(f"/api/v1/restaurant/orders/{order_id}/ready", headers=owner_headers)
        assert ready.status_code == 200
        assert ready.json()["status"] == "ready_for_pickup"

        customer_view = client.get(f"/api/v1/customer/orders/{order_id}", headers=customer_headers)
        assert customer_view.json()["status"] == "ready_for_pickup"

        available = client.get("/api/v1/rider/deliveries/available", headers=rider_headers)
        assert available.status_code == 200
        matching_available = [d for d in available.json() if d["order_id"] == order_id]
        assert len(matching_available) == 1
        # Phase 9 privacy rule re-verified here, in the full integration
        # context: no customer name/phone/exact address before acceptance.
        assert "customer_name" not in matching_available[0]
        assert matching_available[0]["customer_area"] == "Bengaluru"
        assert matching_available[0]["restaurant_name"] == "Chai House"

        # A rider-side notification should have gone out the moment this
        # became available (Phase 21's NEW_DELIVERY trigger).
        rider_notifications = client.get("/api/v1/rider/notifications", headers=rider_headers).json()
        assert any(n["type"] == "new_delivery" and n["order_id"] == order_id for n in rider_notifications)

        # ------------------------------------------------------------------
        # RIDER: accept -> RIDER_ASSIGNED / ACCEPTED. Customer must now see a
        # rider is assigned; the restaurant's own order record must show it too.
        # ------------------------------------------------------------------
        rider_accept = client.post(f"/api/v1/rider/deliveries/{order_id}/accept", headers=rider_headers)
        assert rider_accept.status_code == 200
        assert rider_accept.json()["status"] == "rider_assigned"

        customer_view = client.get(f"/api/v1/customer/orders/{order_id}", headers=customer_headers)
        assert customer_view.json()["status"] == "rider_assigned"

        tracking = client.get(f"/api/v1/customer/orders/{order_id}/tracking", headers=customer_headers)
        assert tracking.json()["order_status"] == "rider_assigned"
        assert tracking.json()["assignment_status"] == "assigned"
        assert tracking.json()["rider"]["name"] == "Rider A"

        restaurant_view = client.get(f"/api/v1/restaurant/orders/{order_id}", headers=owner_headers)
        assert restaurant_view.status_code == 200
        assert restaurant_view.json()["status"] == "rider_assigned"
        assert restaurant_view.json()["rider_id"] == rider_id

        rider_delivery_detail = client.get(f"/api/v1/rider/deliveries/{order_id}", headers=rider_headers)
        assert rider_delivery_detail.status_code == 200
        assert rider_delivery_detail.json()["status"] == "rider_assigned"
        assert rider_delivery_detail.json()["assignment_status"] == "ACCEPTED"
        # Once assigned, the rider now legitimately sees what was hidden
        # from the available-deliveries list a moment ago.
        assert rider_delivery_detail.json()["customer_name"] == "Customer A"

        # ------------------------------------------------------------------
        # RIDER: pickup -> PICKED_UP.
        # ------------------------------------------------------------------
        pickup = client.post(f"/api/v1/rider/deliveries/{order_id}/pickup", headers=rider_headers)
        assert pickup.status_code == 200
        assert pickup.json()["status"] == "picked_up"

        for view, headers in (
            (client.get(f"/api/v1/customer/orders/{order_id}", headers=customer_headers), None),
            (client.get(f"/api/v1/restaurant/orders/{order_id}", headers=owner_headers), None),
        ):
            assert view.json()["status"] == "picked_up"

        rider_delivery_detail = client.get(f"/api/v1/rider/deliveries/{order_id}", headers=rider_headers)
        assert rider_delivery_detail.json()["assignment_status"] == "PICKED_UP"

        # ------------------------------------------------------------------
        # RIDER: start delivery -> OUT_FOR_DELIVERY. Report a live GPS
        # position and confirm the customer's tracking view picks it up —
        # the Phase 22 -> Phase 23 pipeline, exercised inside this exact
        # three-way flow rather than in isolation.
        # ------------------------------------------------------------------
        start = client.post(f"/api/v1/rider/deliveries/{order_id}/start", headers=rider_headers)
        assert start.status_code == 200
        assert start.json()["status"] == "out_for_delivery"

        location_update = client.patch(
            "/api/v1/rider/location", headers=rider_headers,
            json={"latitude": "12.9760", "longitude": "77.6060", "accuracy": "6.0"},
        )
        assert location_update.status_code == 200

        customer_view = client.get(f"/api/v1/customer/orders/{order_id}", headers=customer_headers)
        assert customer_view.json()["status"] == "out_for_delivery"

        tracking = client.get(f"/api/v1/customer/orders/{order_id}/tracking", headers=customer_headers)
        assert tracking.json()["order_status"] == "out_for_delivery"
        assert tracking.json()["rider_location"] is not None
        assert float(tracking.json()["rider_location"]["latitude"]) == pytest.approx(12.976)

        restaurant_view = client.get(f"/api/v1/restaurant/orders/{order_id}", headers=owner_headers)
        assert restaurant_view.json()["status"] == "out_for_delivery"

        # ------------------------------------------------------------------
        # RIDER: collect the COD cash — required before completion (Phase 16
        # -> Phase 17) for a real order placed the only way a customer
        # actually can today.
        # ------------------------------------------------------------------
        cod_collect = client.post(f"/api/v1/rider/deliveries/{order_id}/cod-collect", headers=rider_headers)
        assert cod_collect.status_code == 200
        assert Decimal(cod_collect.json()["amount"]) == Decimal("155.00")

        # ------------------------------------------------------------------
        # RIDER: complete -> DELIVERED. Final state, verified on every side.
        # ------------------------------------------------------------------
        complete = client.post(f"/api/v1/rider/deliveries/{order_id}/complete", headers=rider_headers)
        assert complete.status_code == 200
        assert complete.json()["status"] == "delivered"

        customer_view = client.get(f"/api/v1/customer/orders/{order_id}", headers=customer_headers)
        assert customer_view.json()["status"] == "delivered"

        tracking = client.get(f"/api/v1/customer/orders/{order_id}/tracking", headers=customer_headers)
        assert tracking.json()["order_status"] == "delivered"
        # Phase 15's privacy window has now closed on the rider's side (see
        # below), but the customer's OWN tracking view was never gated by
        # it in the first place — a customer can always see their own
        # order's full status history regardless of delivery state.
        assert [h["status"] for h in tracking.json()["status_history"]] == [
            "placed", "confirmed", "preparing", "ready_for_pickup",
            "rider_assigned", "picked_up", "out_for_delivery", "delivered",
        ]

        customer_notifications = client.get("/api/v1/customer/notifications", headers=customer_headers).json()
        assert any(n["type"] == "order_delivered" and n["order_id"] == order_id for n in customer_notifications)

        restaurant_view = client.get(f"/api/v1/restaurant/orders/{order_id}", headers=owner_headers)
        assert restaurant_view.json()["status"] == "delivered"

        # Rider's own three views of "this delivery is done": the detail
        # endpoint (masked per Phase 15, since it's no longer in progress),
        # history, and earnings.
        rider_delivery_detail = client.get(f"/api/v1/rider/deliveries/{order_id}", headers=rider_headers)
        assert rider_delivery_detail.json()["status"] == "delivered"
        assert rider_delivery_detail.json()["assignment_status"] == "DELIVERED"
        assert rider_delivery_detail.json()["customer_phone"] is None

        history = client.get("/api/v1/rider/history", headers=rider_headers).json()
        assert len(history) == 1
        assert history[0]["order_id"] == order_id
        assert history[0]["status"] == "delivered"

        earnings = client.get("/api/v1/rider/earnings", headers=rider_headers).json()
        assert len(earnings) == 1
        assert earnings[0]["order_id"] == order_id
        assert Decimal(earnings[0]["amount"]) == Decimal("35.00")  # the restaurant's own delivery_fee

        wallet = client.get("/api/v1/rider/wallet", headers=rider_headers).json()
        assert Decimal(wallet["total_earnings"]) == Decimal("35.00")
        # The rider is now holding the platform's/restaurant's ₹155 in cash —
        # tracked entirely separately from their own ₹35 earning (Phase 20's
        # central rule), which is why the wallet balance is negative here.
        assert Decimal(wallet["total_cod_collected"]) == Decimal("155.00")
        assert Decimal(wallet["wallet_balance"]) == Decimal("35.00") - Decimal("155.00")

        dashboard = client.get("/api/v1/rider/dashboard", headers=rider_headers).json()
        assert dashboard["completed_deliveries_count"] == 1
        assert dashboard["current_assignment"] is None  # nothing active anymore
