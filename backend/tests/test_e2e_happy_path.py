"""Phase 28 — Complete Happy-Path E2E Test.

The permanent, CI-run codification of the exact 24-step scenario the phase
names — live-verified once already against the real Postgres-backed dev
server (all 24 steps passed; see this phase's completion report), and
captured here so it runs on every future test session instead of only
when someone remembers to run it by hand. Every step goes through the
real HTTP endpoint each portal's own frontend actually calls — never a
direct service-layer shortcut for anything the phase's steps name.
"""

from decimal import Decimal

from app.core.security import create_access_token, hash_password
from app.models.user import User, UserRole


def _db(client):
    from app.db.session import get_db

    return next(client.app.dependency_overrides[get_db]())


def test_complete_happy_path_all_24_steps(client):
    from app.models.commission_rule import CommissionRule, CommissionType

    db = _db(client)

    # ---- STEP 4: Login Admin (seeded — no public admin self-registration) ----
    admin = User(name="Admin", email="e2e-admin@example.com", phone="9800000001", password_hash=hash_password("x"), role=UserRole.ADMIN)
    db.add(admin)
    # A platform-wide commission rule, the same realistic config Phase 23's
    # own financial-consistency test seeds — without one, commission_amount
    # is legitimately None (no rule configured), which would make step 24's
    # commission math trivially untestable rather than actually verified.
    db.add(CommissionRule(restaurant_id=None, commission_type=CommissionType.PERCENTAGE, value=Decimal("10.00")))
    db.commit()
    admin_headers = {"Authorization": f"Bearer {create_access_token(admin.id)}"}
    db.close()

    # ---- STEP 1: Create/login Customer ----
    reg = client.post("/api/v1/auth/register", json={
        "name": "E2E Customer", "email": "e2e-customer@example.com", "phone": "9800000002",
        "password": "TestPass123!", "role": "customer",
    })
    assert reg.status_code == 201
    login = client.post("/api/v1/auth/login", json={"email": "e2e-customer@example.com", "password": "TestPass123!"})
    assert login.status_code == 200
    customer_headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    # ---- STEP 2: Create/login Restaurant Owner (admin-provisioned, no self-registration) ----
    db = _db(client)
    owner = User(name="E2E Owner", email="e2e-owner@example.com", phone="9800000003", password_hash=hash_password("TestPass123!"), role=UserRole.RESTAURANT_OWNER)
    db.add(owner)
    db.commit()
    db.close()
    owner_login = client.post("/api/v1/auth/login", json={"email": "e2e-owner@example.com", "password": "TestPass123!"})
    assert owner_login.status_code == 200
    owner_headers = {"Authorization": f"Bearer {owner_login.json()['access_token']}"}

    # ---- STEP 3: Create/login approved Rider — real onboarding through the real endpoints ----
    rider_reg = client.post("/api/v1/auth/register", json={
        "name": "E2E Rider", "email": "e2e-rider@example.com", "phone": "9800000004",
        "password": "TestPass123!", "role": "rider",
    })
    assert rider_reg.status_code == 201
    rider_login = client.post("/api/v1/auth/login", json={"email": "e2e-rider@example.com", "password": "TestPass123!"})
    assert rider_login.status_code == 200
    rider_headers = {"Authorization": f"Bearer {rider_login.json()['access_token']}"}
    rider_id = client.get("/api/v1/auth/me", headers=rider_headers).json()["id"]

    for doc_type in ("DRIVING_LICENSE", "VEHICLE_REGISTRATION", "IDENTITY_DOCUMENT", "PROFILE_PHOTO"):
        created = client.post(
            "/api/v1/rider/documents", headers=rider_headers,
            json={"document_type": doc_type, "document_url": f"https://example.com/{doc_type.lower()}.jpg"},
        )
        assert created.status_code == 201
        approved = client.post(f"/api/v1/admin/riders/{rider_id}/documents/{created.json()['id']}/approve", headers=admin_headers)
        assert approved.status_code == 200

    vehicle = client.patch("/api/v1/rider/vehicle", headers=rider_headers, json={"vehicle_type": "BIKE", "vehicle_number": "KA01E2E9999"})
    assert vehicle.status_code == 200

    approve_rider = client.post(f"/api/v1/admin/riders/{rider_id}/approve", headers=admin_headers, json={"reason": "E2E happy path"})
    assert approve_rider.status_code == 200

    go_online = client.patch("/api/v1/rider/status", headers=rider_headers, json={"is_online": True})
    assert go_online.status_code == 200
    assert go_online.json()["is_online"] is True

    # ---- STEP 5: Restaurant is active ----
    restaurant = client.post("/api/v1/restaurants", headers=owner_headers, json={
        "name": "E2E Diner", "phone": "9800000005", "address": "1 E2E Road, Azamgarh",
        "latitude": "26.0680", "longitude": "83.1840",
    })
    assert restaurant.status_code == 201
    restaurant_id = restaurant.json()["id"]
    assert restaurant.json()["is_active"] is True
    assert client.get(f"/api/v1/restaurants/{restaurant_id}", headers=owner_headers).json()["is_active"] is True

    # ---- STEP 6: Product is available ----
    product = client.post("/api/v1/restaurant/products", headers=owner_headers, json={
        "name": "E2E Masala Dosa", "price": "150.00", "is_available": True,
    })
    assert product.status_code == 201
    product_id = product.json()["id"]
    assert product.json()["is_available"] is True
    catalog = client.get(f"/api/v1/customer/restaurants/{restaurant_id}/products")
    assert any(p["id"] == product_id for p in catalog.json())

    # ---- STEP 7: Customer adds product ----
    added = client.post("/api/v1/customer/cart/items", headers=customer_headers, json={"product_id": product_id, "quantity": 2})
    assert added.status_code == 201
    assert added.json()["total_items"] == 2

    # ---- STEP 8: Customer places order ----
    address = client.post("/api/v1/addresses", headers=customer_headers, json={
        "label": "Home", "recipient_name": "E2E Customer", "phone": "9800000002",
        "address_line": "12 Sanjarpur Road", "city": "Azamgarh", "state": "UP", "postal_code": "223227",
    })
    assert address.status_code == 201
    placed = client.post("/api/v1/customer/orders", headers=customer_headers, json={
        "address_id": address.json()["id"], "payment_method": "cod",
    })
    assert placed.status_code == 201
    order = placed.json()
    order_id = order["id"]
    assert order["status"] == "placed"
    assert order["item_count"] == 2

    # ---- STEP 9: Restaurant receives order ----
    pending = client.get("/api/v1/restaurant/orders?status=pending", headers=owner_headers)
    assert any(o["id"] == order_id for o in pending.json())
    detail = client.get(f"/api/v1/restaurant/orders/{order_id}", headers=owner_headers)
    assert detail.json()["status"] == "placed"

    # ---- STEP 10: Restaurant confirms ----
    confirmed = client.post(f"/api/v1/restaurant/orders/{order_id}/accept", headers=owner_headers)
    assert confirmed.status_code == 200
    assert confirmed.json()["status"] == "confirmed"

    # ---- STEP 11: Restaurant prepares ----
    preparing = client.post(f"/api/v1/restaurant/orders/{order_id}/preparing", headers=owner_headers)
    assert preparing.status_code == 200
    assert preparing.json()["status"] == "preparing"

    # ---- STEP 12: Restaurant marks READY_FOR_PICKUP ----
    ready = client.post(f"/api/v1/restaurant/orders/{order_id}/ready", headers=owner_headers)
    assert ready.status_code == 200
    assert ready.json()["status"] == "ready_for_pickup"

    # ---- STEP 13: Delivery assignment becomes available ----
    available = client.get("/api/v1/rider/deliveries/available", headers=rider_headers)
    assert available.status_code == 200
    assert any(d["order_id"] == order_id for d in available.json())

    # ---- STEP 14: Rider accepts ----
    accepted = client.post(f"/api/v1/rider/deliveries/{order_id}/accept", headers=rider_headers)
    assert accepted.status_code == 200
    assert accepted.json()["status"] == "rider_assigned"

    # ---- STEP 15: Rider picks up ----
    picked_up = client.post(f"/api/v1/rider/deliveries/{order_id}/pickup", headers=rider_headers)
    assert picked_up.status_code == 200
    assert picked_up.json()["status"] == "picked_up"

    # ---- STEP 16: Rider starts delivery ----
    started = client.post(f"/api/v1/rider/deliveries/{order_id}/start", headers=rider_headers)
    assert started.status_code == 200
    assert started.json()["status"] == "out_for_delivery"

    # ---- STEP 17: Customer sees OUT_FOR_DELIVERY ----
    tracking = client.get(f"/api/v1/customer/orders/{order_id}/tracking", headers=customer_headers)
    assert tracking.status_code == 200
    assert tracking.json()["order_status"] == "out_for_delivery"

    # ---- STEP 18: Rider delivers (COD collection is a required prerequisite) ----
    collect = client.post(f"/api/v1/rider/deliveries/{order_id}/cod-collect", headers=rider_headers)
    assert collect.status_code == 200
    expected_total = Decimal(order["total"])
    assert Decimal(collect.json()["amount"]) == expected_total
    completed = client.post(f"/api/v1/rider/deliveries/{order_id}/complete", headers=rider_headers)
    assert completed.status_code == 200
    assert completed.json()["status"] == "delivered"

    # ---- STEP 19: Order becomes DELIVERED ----
    admin_view = client.get(f"/api/v1/admin/orders/{order_id}", headers=admin_headers)
    assert admin_view.status_code == 200
    assert admin_view.json()["status"] == "delivered"
    assert admin_view.json()["payment_status"] == "paid"

    # ---- STEP 20: Customer sees completed order ----
    customer_view = client.get(f"/api/v1/customer/orders/{order_id}", headers=customer_headers)
    assert customer_view.json()["status"] == "delivered"
    customer_list = client.get("/api/v1/customer/orders", headers=customer_headers)
    assert any(o["id"] == order_id and o["status"] == "delivered" for o in customer_list.json())

    # ---- STEP 21: Restaurant sees completed order ----
    restaurant_completed = client.get("/api/v1/restaurant/orders?status=completed", headers=owner_headers)
    assert any(o["id"] == order_id for o in restaurant_completed.json())

    # ---- STEP 22: Rider sees completed delivery ----
    rider_history = client.get("/api/v1/rider/history", headers=rider_headers)
    assert any(h["order_id"] == order_id and h["status"] == "delivered" for h in rider_history.json())

    # ---- STEP 23: Admin sees completed order ----
    admin_delivered = client.get("/api/v1/admin/orders?status=delivered", headers=admin_headers)
    assert any(o["id"] == order_id for o in admin_delivered.json()["items"])

    # ---- STEP 24: Financial records are consistent ----
    from uuid import UUID as _UUID

    from app.models.order import Order
    from app.models.payment import Payment
    from app.models.rider_earning import RiderEarning
    from app.services.admin_reports import _order_financials

    db = _db(client)
    order_row = db.query(Order).filter(Order.id == _UUID(order_id)).one()
    assert order_row.total == order_row.subtotal + order_row.delivery_fee - order_row.discount + order_row.tax

    payment = db.query(Payment).filter(Payment.order_id == order_row.id).one()
    assert payment.amount == order_row.total

    earning = db.query(RiderEarning).filter(RiderEarning.order_id == order_row.id).one()
    assert earning.amount == order_row.delivery_fee
    assert earning.rider_id == _UUID(rider_id)

    assert order_row.commission_amount is not None
    assert order_row.subtotal - order_row.commission_amount >= Decimal("0.00")

    revenue, commission, restaurant_earnings = _order_financials(db, None, None)
    assert revenue == order_row.total
    assert commission == order_row.commission_amount
    assert restaurant_earnings == order_row.subtotal - order_row.commission_amount
    db.close()
