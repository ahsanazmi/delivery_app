"""Phase 27 — Complete COD end-to-end test.

Drives the exact sequence from the phase brief through real HTTP calls on
every portal's own endpoints:

  Customer places COD order -> Restaurant accepts/prepares/marks ready ->
  Rider accepts -> Rider picks up -> Rider sees COD amount ->
  Customer pays cash -> Rider records COD collection ->
  Rider completes delivery -> Order = DELIVERED -> Payment = PAID ->
  Rider's financial ledger updated.

Then a dedicated section attempts, at every point a client could plausibly
try, to manipulate the collected amount — and confirms every attempt is a
no-op: the amount recorded is always order.total, re-read server-side, no
matter what a request body claims.

Note on "settlement ledger": COD collection itself doesn't create a
RiderSettlement row; it updates the Payment audit trail
(collected_by_rider_id/collected_at/amount) and, on completion, the
RiderEarning ledger — both of which feed directly into GET /rider/wallet's
total_cod_collected/total_earnings/wallet_balance figures. The two tests
below verify that composite "financial ledger" (wallet + earnings +
payment audit trail) immediately after collection. A RiderSettlement row
(PAYOUT/REMITTANCE — the rider physically handing collected cash back to
the platform) is a separate, later, admin-only step: see
admin_settle_cod() in app/services/admin_cod.py and
test_integration_cod_settlement_and_admin_reconciliation below, which
chains collection all the way through admin settlement and reconciliation.
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


def _onboard_rider(client, rider_headers, rider_id, admin_headers):
    client.patch(f"/api/v1/admin/riders/{rider_id}/verification", headers=admin_headers, json={"approval_status": "APPROVED"})
    for doc_type in ("DRIVING_LICENSE", "VEHICLE_REGISTRATION", "IDENTITY_DOCUMENT", "PROFILE_PHOTO"):
        created = client.post(
            "/api/v1/rider/documents", headers=rider_headers,
            json={"document_type": doc_type, "document_url": f"https://example.com/{doc_type.lower()}.jpg"},
        ).json()
        client.patch(
            f"/api/v1/admin/riders/{rider_id}/documents/{created['id']}",
            headers=admin_headers, json={"verification_status": "APPROVED"},
        )
    client.patch("/api/v1/rider/vehicle", headers=rider_headers, json={"vehicle_type": "BIKE", "vehicle_number": "KA01AB1234"})
    response = client.patch("/api/v1/rider/status", headers=rider_headers, json={"is_online": True})
    assert response.status_code == 200, response.json()


def test_complete_cod_flow_end_to_end_and_amount_is_tamper_proof(engine):
    with Session(engine) as seed:
        owner = User(name="Owner", email="owner-cod@example.com", phone="9400000001", password_hash=hash_password("x"), role=UserRole.RESTAURANT_OWNER)
        seed.add(owner)
        seed.commit()
        restaurant = Restaurant(
            owner_id=owner.id, name="Cash Diner", phone="9876500000", address="Main Road",
            latitude=Decimal("12.9716"), longitude=Decimal("77.5946"),
            minimum_order=Decimal("0.00"), delivery_fee=Decimal("45.00"),
        )
        seed.add(restaurant)
        seed.commit()
        product = Product(restaurant_id=restaurant.id, name="Thali", price=Decimal("230.00"))
        seed.add(product)
        seed.commit()
        product_id = str(product.id)
        owner_token = create_access_token(owner.id)

        admin = User(name="Admin", email="admin-cod@example.com", phone="9400000099", password_hash=hash_password("x"), role=UserRole.ADMIN)
        seed.add(admin)
        seed.commit()
        admin_token = create_access_token(admin.id)

    with TestClient(app) as client:
        owner_headers = {"Authorization": f"Bearer {owner_token}"}
        admin_headers = {"Authorization": f"Bearer {admin_token}"}

        client.post(
            "/api/v1/auth/register",
            json={"name": "Cash Customer", "email": "customer-cod@example.com", "password": "secure-pass-123", "phone": "9400000002", "role": "CUSTOMER"},
        )
        customer_token = client.post(
            "/api/v1/auth/login", json={"email": "customer-cod@example.com", "password": "secure-pass-123"}
        ).json()["access_token"]
        customer_headers = {"Authorization": f"Bearer {customer_token}"}

        client.post(
            "/api/v1/auth/register",
            json={"name": "Cash Rider", "email": "rider-cod@example.com", "password": "secure-pass-123", "phone": "9400000003", "role": "RIDER"},
        )
        rider_token = client.post(
            "/api/v1/auth/login", json={"email": "rider-cod@example.com", "password": "secure-pass-123"}
        ).json()["access_token"]
        rider_headers = {"Authorization": f"Bearer {rider_token}"}
        rider_id = client.get("/api/v1/auth/me", headers=rider_headers).json()["id"]
        _onboard_rider(client, rider_headers, rider_id, admin_headers)

        # ------------------------------------------------------------
        # Customer places a COD order (the only real payment method the
        # actual checkout endpoint exposes today).
        # ------------------------------------------------------------
        address = client.post(
            "/api/v1/customer/addresses", headers=customer_headers,
            json={
                "label": "Home", "recipient_name": "Cash Customer", "phone": "9400000002",
                "address_line": "9 Cash Lane", "city": "Bengaluru", "state": "Karnataka", "postal_code": "560003",
            },
        ).json()
        client.post("/api/v1/customer/cart/items", headers=customer_headers, json={"product_id": product_id, "quantity": 1})
        order = client.post(
            "/api/v1/customer/orders", headers=customer_headers, json={"address_id": address["id"]}
        ).json()
        order_id = order["id"]
        expected_total = order["total"]
        assert order["payment_method"] == "cod"
        assert order["payment_status"] == "pending"
        assert order["is_paid"] is False
        assert expected_total == "275.00"  # 230 + 45 delivery fee

        # ------------------------------------------------------------
        # Restaurant: accept -> prepare -> ready.
        # ------------------------------------------------------------
        assert client.post(f"/api/v1/restaurant/orders/{order_id}/accept", headers=owner_headers).status_code == 200
        assert client.post(f"/api/v1/restaurant/orders/{order_id}/preparing", headers=owner_headers).status_code == 200
        assert client.post(f"/api/v1/restaurant/orders/{order_id}/ready", headers=owner_headers).status_code == 200

        # ------------------------------------------------------------
        # Rider: accept -> pick up.
        # ------------------------------------------------------------
        assert client.post(f"/api/v1/rider/deliveries/{order_id}/accept", headers=rider_headers).status_code == 200
        assert client.post(f"/api/v1/rider/deliveries/{order_id}/pickup", headers=rider_headers).status_code == 200

        # --- "Rider sees COD amount" ---
        rider_view = client.get(f"/api/v1/rider/deliveries/{order_id}", headers=rider_headers).json()
        assert rider_view["payment_method"] == "cod"
        assert rider_view["is_paid"] is False
        assert rider_view["cod_amount"] == expected_total

        assert client.post(f"/api/v1/rider/deliveries/{order_id}/start", headers=rider_headers).status_code == 200

        # --- "Customer pays cash" -> "Rider records COD collection" ---
        collect = client.post(f"/api/v1/rider/deliveries/{order_id}/cod-collect", headers=rider_headers)
        assert collect.status_code == 200
        collect_body = collect.json()
        assert collect_body["order_id"] == order_id
        assert collect_body["amount"] == expected_total
        assert collect_body["payment_status"] == "paid"
        assert collect_body["collected_by_rider_id"] == rider_id
        assert collect_body["collected_at"] is not None

        # The COD prompt disappears everywhere it was shown, immediately —
        # no separate "confirm" step needed, no stale prompt left behind.
        rider_view_after_collect = client.get(f"/api/v1/rider/deliveries/{order_id}", headers=rider_headers).json()
        assert rider_view_after_collect["cod_amount"] is None
        assert rider_view_after_collect["is_paid"] is True

        # --- "Rider completes delivery" -> Order = DELIVERED, Payment = PAID ---
        complete = client.post(f"/api/v1/rider/deliveries/{order_id}/complete", headers=rider_headers)
        assert complete.status_code == 200
        assert complete.json()["status"] == "delivered"
        assert complete.json()["payment_status"] == "paid"
        assert complete.json()["is_paid"] is True

        # Every role that can see this order agrees: delivered, and paid.
        customer_final = client.get(f"/api/v1/customer/orders/{order_id}", headers=customer_headers).json()
        assert customer_final["status"] == "delivered"
        assert customer_final["payment_status"] == "paid"
        assert customer_final["is_paid"] is True

        restaurant_final = client.get(f"/api/v1/restaurant/orders/{order_id}", headers=owner_headers).json()
        assert restaurant_final["status"] == "delivered"
        assert restaurant_final["payment_status"] == "paid"

        # --- "Rider's financial ledger updated" (see module docstring for
        # why this checks the wallet/earnings ledger rather than a
        # RiderSettlement row) ---
        earnings = client.get("/api/v1/rider/earnings", headers=rider_headers).json()
        matching_earning = [e for e in earnings if e["order_id"] == order_id]
        assert len(matching_earning) == 1
        assert matching_earning[0]["earning_type"] == "DELIVERY_FEE"
        assert matching_earning[0]["amount"] == "45.00"  # the restaurant's own delivery_fee, not the COD total

        wallet = client.get("/api/v1/rider/wallet", headers=rider_headers).json()
        assert Decimal(wallet["total_earnings"]) == Decimal("45.00")
        assert Decimal(wallet["total_cod_collected"]) == Decimal(expected_total)
        # The rider is holding far more cash (275) than they earned (45) —
        # COD collected is never treated as income (Phase 20's central rule).
        assert Decimal(wallet["wallet_balance"]) == Decimal("45.00") - Decimal(expected_total)
        assert Decimal(wallet["total_settled"]) == Decimal("0.00")  # no PAYOUT/REMITTANCE has happened yet


def test_no_client_can_manipulate_the_cod_amount(engine):
    """A dedicated adversarial pass: every request body a client could send
    at any point in the COD flow that contains an amount-shaped field is
    exercised with a spoofed value, and the recorded amount is proven to
    still equal order.total every single time."""
    with Session(engine) as seed:
        owner = User(name="Owner", email="owner-cod2@example.com", phone="9400000010", password_hash=hash_password("x"), role=UserRole.RESTAURANT_OWNER)
        seed.add(owner)
        seed.commit()
        restaurant = Restaurant(
            owner_id=owner.id, name="Cash Diner 2", phone="9876500001", address="Main Road",
            latitude=Decimal("12.9716"), longitude=Decimal("77.5946"),
            minimum_order=Decimal("0.00"), delivery_fee=Decimal("50.00"),
        )
        seed.add(restaurant)
        seed.commit()
        product = Product(restaurant_id=restaurant.id, name="Biryani", price=Decimal("300.00"))
        seed.add(product)
        seed.commit()
        product_id = str(product.id)
        owner_token = create_access_token(owner.id)

        admin = User(name="Admin", email="admin-cod2@example.com", phone="9400000098", password_hash=hash_password("x"), role=UserRole.ADMIN)
        seed.add(admin)
        seed.commit()
        admin_token = create_access_token(admin.id)

    with TestClient(app) as client:
        owner_headers = {"Authorization": f"Bearer {owner_token}"}
        admin_headers = {"Authorization": f"Bearer {admin_token}"}

        client.post(
            "/api/v1/auth/register",
            json={"name": "Cash Customer 2", "email": "customer-cod2@example.com", "password": "secure-pass-123", "phone": "9400000011", "role": "CUSTOMER"},
        )
        customer_token = client.post(
            "/api/v1/auth/login", json={"email": "customer-cod2@example.com", "password": "secure-pass-123"}
        ).json()["access_token"]
        customer_headers = {"Authorization": f"Bearer {customer_token}"}

        client.post(
            "/api/v1/auth/register",
            json={"name": "Cash Rider 2", "email": "rider-cod2@example.com", "password": "secure-pass-123", "phone": "9400000012", "role": "RIDER"},
        )
        rider_token = client.post(
            "/api/v1/auth/login", json={"email": "rider-cod2@example.com", "password": "secure-pass-123"}
        ).json()["access_token"]
        rider_headers = {"Authorization": f"Bearer {rider_token}"}
        rider_id = client.get("/api/v1/auth/me", headers=rider_headers).json()["id"]
        _onboard_rider(client, rider_headers, rider_id, admin_headers)

        address = client.post(
            "/api/v1/customer/addresses", headers=customer_headers,
            json={
                "label": "Home", "recipient_name": "Cash Customer 2", "phone": "9400000011",
                "address_line": "10 Cash Lane", "city": "Bengaluru", "state": "Karnataka", "postal_code": "560004",
            },
        ).json()
        client.post("/api/v1/customer/cart/items", headers=customer_headers, json={"product_id": product_id, "quantity": 1})
        order = client.post(
            "/api/v1/customer/orders", headers=customer_headers, json={"address_id": address["id"]}
        ).json()
        order_id = order["id"]
        real_total = order["total"]
        assert real_total == "350.00"  # 300 + 50 delivery fee

        client.post(f"/api/v1/restaurant/orders/{order_id}/accept", headers=owner_headers)
        client.post(f"/api/v1/restaurant/orders/{order_id}/preparing", headers=owner_headers)
        client.post(f"/api/v1/restaurant/orders/{order_id}/ready", headers=owner_headers)

        tampering_payload = {
            "amount": "0.01",
            "total": "0.01",
            "cod_amount": "0.01",
            "payment_amount": "999999.00",
            "delivery_fee": "0.00",
        }

        # Attempt 1: tamper on accept.
        accept = client.post(f"/api/v1/rider/deliveries/{order_id}/accept", headers=rider_headers, json=tampering_payload)
        assert accept.status_code == 200

        # Attempt 2: tamper on pickup.
        client.post(f"/api/v1/rider/deliveries/{order_id}/pickup", headers=rider_headers, json=tampering_payload)

        rider_view = client.get(f"/api/v1/rider/deliveries/{order_id}", headers=rider_headers).json()
        assert rider_view["cod_amount"] == real_total  # untouched by either tampering attempt

        client.post(f"/api/v1/rider/deliveries/{order_id}/start", headers=rider_headers)

        # Attempt 3 (the critical one): tamper on the actual collection call.
        collect = client.post(f"/api/v1/rider/deliveries/{order_id}/cod-collect", headers=rider_headers, json=tampering_payload)
        assert collect.status_code == 200
        assert collect.json()["amount"] == real_total
        assert collect.json()["amount"] != "0.01"
        assert collect.json()["amount"] != "999999.00"

        # Attempt 4: try to collect again with a different spoofed amount.
        # Phase 28: a second collect by the SAME rider is treated as an
        # idempotent retry (200), not an error — but it must still return
        # the ORIGINAL real amount, completely ignoring this new spoofed
        # payload. Tamper-resistance holds on the retry path too.
        second_collect = client.post(
            f"/api/v1/rider/deliveries/{order_id}/cod-collect", headers=rider_headers, json={"amount": "1.00"}
        )
        assert second_collect.status_code == 200
        assert second_collect.json()["amount"] == real_total
        assert second_collect.json()["amount"] != "1.00"

        # Attempt 5: tamper on completion.
        complete = client.post(f"/api/v1/rider/deliveries/{order_id}/complete", headers=rider_headers, json=tampering_payload)
        assert complete.status_code == 200
        assert complete.json()["total"] == real_total

        # The ledger reflects the real amount throughout, never the spoofed one.
        wallet = client.get("/api/v1/rider/wallet", headers=rider_headers).json()
        assert Decimal(wallet["total_cod_collected"]) == Decimal(real_total)

        earnings = client.get("/api/v1/rider/earnings", headers=rider_headers).json()
        matching_earning = [e for e in earnings if e["order_id"] == order_id]
        assert matching_earning[0]["amount"] == "50.00"  # the real delivery_fee, not anything from the payload


def test_integration_cod_settlement_and_admin_reconciliation(engine):
    """Integration Phase 13 — the two links the other tests in this file
    stop short of: after COD is collected, admin's reconciliation view must
    show the correct expected/collected/outstanding amounts and PENDING
    status; a partial settlement must move it to PARTIAL with the right
    outstanding balance; settling the remainder must move it to SETTLED
    with zero outstanding. Chains the full diagram end to end in one test:
    Customer places COD order -> Restaurant prepares -> Rider accepts ->
    picks up -> delivers -> COD collected -> Rider settlement (admin) ->
    Admin reconciliation."""
    with Session(engine) as seed:
        owner = User(name="Owner", email="owner-cod3@example.com", phone="9400000020", password_hash=hash_password("x"), role=UserRole.RESTAURANT_OWNER)
        seed.add(owner)
        seed.commit()
        restaurant = Restaurant(
            owner_id=owner.id, name="Cash Diner 3", phone="9876500002", address="Main Road",
            latitude=Decimal("12.9716"), longitude=Decimal("77.5946"),
            minimum_order=Decimal("0.00"), delivery_fee=Decimal("30.00"),
        )
        seed.add(restaurant)
        seed.commit()
        product = Product(restaurant_id=restaurant.id, name="Dosa", price=Decimal("170.00"))
        seed.add(product)
        seed.commit()
        product_id = str(product.id)
        owner_token = create_access_token(owner.id)

        admin = User(name="Admin", email="admin-cod3@example.com", phone="9400000097", password_hash=hash_password("x"), role=UserRole.ADMIN)
        seed.add(admin)
        seed.commit()
        admin_token = create_access_token(admin.id)

    with TestClient(app) as client:
        owner_headers = {"Authorization": f"Bearer {owner_token}"}
        admin_headers = {"Authorization": f"Bearer {admin_token}"}

        client.post(
            "/api/v1/auth/register",
            json={"name": "Cash Customer 3", "email": "customer-cod3@example.com", "password": "secure-pass-123", "phone": "9400000021", "role": "CUSTOMER"},
        )
        customer_token = client.post(
            "/api/v1/auth/login", json={"email": "customer-cod3@example.com", "password": "secure-pass-123"}
        ).json()["access_token"]
        customer_headers = {"Authorization": f"Bearer {customer_token}"}

        client.post(
            "/api/v1/auth/register",
            json={"name": "Cash Rider 3", "email": "rider-cod3@example.com", "password": "secure-pass-123", "phone": "9400000022", "role": "RIDER"},
        )
        rider_token = client.post(
            "/api/v1/auth/login", json={"email": "rider-cod3@example.com", "password": "secure-pass-123"}
        ).json()["access_token"]
        rider_headers = {"Authorization": f"Bearer {rider_token}"}
        rider_id = client.get("/api/v1/auth/me", headers=rider_headers).json()["id"]
        _onboard_rider(client, rider_headers, rider_id, admin_headers)

        # ---- Customer places COD order -> Restaurant prepares ----
        address = client.post(
            "/api/v1/customer/addresses", headers=customer_headers,
            json={
                "label": "Home", "recipient_name": "Cash Customer 3", "phone": "9400000021",
                "address_line": "11 Cash Lane", "city": "Bengaluru", "state": "Karnataka", "postal_code": "560005",
            },
        ).json()
        client.post("/api/v1/customer/cart/items", headers=customer_headers, json={"product_id": product_id, "quantity": 1})
        order = client.post(
            "/api/v1/customer/orders", headers=customer_headers, json={"address_id": address["id"]}
        ).json()
        order_id = order["id"]
        real_total = order["total"]
        assert real_total == "200.00"  # 170 + 30 delivery fee

        client.post(f"/api/v1/restaurant/orders/{order_id}/accept", headers=owner_headers)
        client.post(f"/api/v1/restaurant/orders/{order_id}/preparing", headers=owner_headers)
        client.post(f"/api/v1/restaurant/orders/{order_id}/ready", headers=owner_headers)

        # ---- Rider accepts -> picks up -> delivers -> COD collected ----
        client.post(f"/api/v1/rider/deliveries/{order_id}/accept", headers=rider_headers)
        client.post(f"/api/v1/rider/deliveries/{order_id}/pickup", headers=rider_headers)
        client.post(f"/api/v1/rider/deliveries/{order_id}/start", headers=rider_headers)
        collect = client.post(f"/api/v1/rider/deliveries/{order_id}/cod-collect", headers=rider_headers)
        assert collect.status_code == 200
        assert collect.json()["amount"] == real_total
        client.post(f"/api/v1/rider/deliveries/{order_id}/complete", headers=rider_headers)

        # ---- Admin reconciliation: PENDING, fully outstanding ----
        detail = client.get(f"/api/v1/admin/cod/{rider_id}", headers=admin_headers)
        assert detail.status_code == 200
        body = detail.json()
        assert body["cod_collected"] == real_total
        assert body["expected_settlement"] == real_total
        assert body["settled_amount"] == "0.00"
        assert body["outstanding_amount"] == real_total
        assert body["status"] == "PENDING"

        cod_list = client.get("/api/v1/admin/cod?status=PENDING", headers=admin_headers)
        assert any(item["rider_id"] == rider_id for item in cod_list.json()["items"])

        # ---- Rider settlement (admin, partial) ----
        partial_settle = client.post(
            f"/api/v1/admin/cod/{rider_id}/settle", headers=admin_headers,
            json={"amount": "120.00", "note": "Partial remittance collected at depot"},
        )
        assert partial_settle.status_code == 200
        partial_body = partial_settle.json()
        assert partial_body["settled_amount"] == "120.00"
        assert partial_body["outstanding_amount"] == "80.00"
        assert partial_body["status"] == "PARTIAL"

        # ---- Rider settlement (admin, remainder) -> fully SETTLED ----
        final_settle = client.post(
            f"/api/v1/admin/cod/{rider_id}/settle", headers=admin_headers,
            json={"amount": "80.00", "note": "Remainder remitted"},
        )
        assert final_settle.status_code == 200
        final_body = final_settle.json()
        assert final_body["settled_amount"] == "200.00"
        assert final_body["outstanding_amount"] == "0.00"
        assert final_body["status"] == "SETTLED"
        assert len(final_body["settlements"]) == 2

        # A settlement can never exceed what's actually outstanding — the
        # backend, not the rider or the admin's own request, is the one
        # source of truth for the expected COD amount here.
        over_settle = client.post(
            f"/api/v1/admin/cod/{rider_id}/settle", headers=admin_headers, json={"amount": "1.00"}
        )
        assert over_settle.status_code == 409
