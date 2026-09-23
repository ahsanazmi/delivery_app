"""Phase 29 — Complete Failure-Path E2E Test.

The permanent, CI-run codification of the 11 named failure scenarios —
live-verified once already against the real Postgres-backed dev server
(all 43 checks passed; see this phase's completion report) and captured
here so it runs on every future test session. For every scenario, checks
every affected role's own view of the outcome, not just the acting role's
immediate response — that cross-role verification is this phase's own
addition on top of the (already extensive) single-role coverage these
same mechanics get in test_security.py, test_rider_concurrency_and_failure_handling.py,
and test_customer_payments.py.
"""

from decimal import Decimal

from app.core.security import create_access_token, hash_password
from app.models.user import User, UserRole


def _db(client):
    from app.db.session import get_db

    return next(client.app.dependency_overrides[get_db]())


def _register_login(client, role, tag):
    email = f"e2e-fail-{tag}@example.com"
    phone = f"98{hash(tag) % 100000000:08d}"[:10]
    r = client.post("/api/v1/auth/register", json={
        "name": f"E2E {tag}", "email": email, "phone": phone, "password": "TestPass123!", "role": role,
    })
    assert r.status_code == 201, r.text
    login = client.post("/api/v1/auth/login", json={"email": email, "password": "TestPass123!"})
    assert login.status_code == 200, login.text
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    me = client.get("/api/v1/auth/me", headers=headers)
    return {"headers": headers, "id": me.json()["id"], "phone": phone}


def _seed_user(client, role, tag):
    db = _db(client)
    user = User(name=f"E2E {tag}", email=f"e2e-fail-{tag}@example.com", phone=f"97{hash(tag) % 100000000:08d}"[:10],
                password_hash=hash_password("TestPass123!"), role=role)
    db.add(user)
    db.commit()
    email, uid = user.email, user.id
    db.close()
    login = client.post("/api/v1/auth/login", json={"email": email, "password": "TestPass123!"})
    assert login.status_code == 200, login.text
    return {"headers": {"Authorization": f"Bearer {login.json()['access_token']}"}, "id": str(uid)}


def _onboard_rider(client, rider, admin_headers, tag):
    for doc_type in ("DRIVING_LICENSE", "VEHICLE_REGISTRATION", "IDENTITY_DOCUMENT", "PROFILE_PHOTO"):
        created = client.post("/api/v1/rider/documents", headers=rider["headers"],
                               json={"document_type": doc_type, "document_url": f"https://example.com/{tag}-{doc_type.lower()}.jpg"})
        assert created.status_code == 201, created.text
        approved = client.post(f"/api/v1/admin/riders/{rider['id']}/documents/{created.json()['id']}/approve", headers=admin_headers)
        assert approved.status_code == 200, approved.text
    vehicle = client.patch("/api/v1/rider/vehicle", headers=rider["headers"], json={"vehicle_type": "BIKE", "vehicle_number": f"KA{tag.upper()}9999"})
    assert vehicle.status_code == 200, vehicle.text
    approve = client.post(f"/api/v1/admin/riders/{rider['id']}/approve", headers=admin_headers, json={"reason": "setup"})
    assert approve.status_code == 200, approve.text
    online = client.patch("/api/v1/rider/status", headers=rider["headers"], json={"is_online": True})
    assert online.status_code == 200, online.text


def _make_address(client, customer, tag):
    r = client.post("/api/v1/addresses", headers=customer["headers"], json={
        "label": "Home", "recipient_name": "E2E Customer", "phone": customer["phone"],
        "address_line": f"{tag} Sanjarpur Road", "city": "Azamgarh", "state": "UP", "postal_code": "223227",
    })
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _place_order(client, customer, product_id, address_id):
    add = client.post("/api/v1/customer/cart/items", headers=customer["headers"], json={"product_id": product_id, "quantity": 1})
    assert add.status_code == 201, add.text
    placed = client.post("/api/v1/customer/orders", headers=customer["headers"], json={"address_id": address_id, "payment_method": "cod"})
    assert placed.status_code == 201, placed.text
    return placed.json()


def _drive_to_ready(client, owner, order_id):
    assert client.post(f"/api/v1/restaurant/orders/{order_id}/accept", headers=owner["headers"]).status_code == 200
    assert client.post(f"/api/v1/restaurant/orders/{order_id}/preparing", headers=owner["headers"]).status_code == 200
    assert client.post(f"/api/v1/restaurant/orders/{order_id}/ready", headers=owner["headers"]).status_code == 200


def test_all_11_failure_path_scenarios(client, monkeypatch):
    admin = _seed_user(client, UserRole.ADMIN, "admin")
    customer_a = _register_login(client, "customer", "custA")
    customer_b = _register_login(client, "customer", "custB")
    owner = _seed_user(client, UserRole.RESTAURANT_OWNER, "owner")
    rider_a = _register_login(client, "rider", "riderA")
    rider_b = _register_login(client, "rider", "riderB")
    _onboard_rider(client, rider_a, admin["headers"], "ra")
    _onboard_rider(client, rider_b, admin["headers"], "rb")

    restaurant = client.post("/api/v1/restaurants", headers=owner["headers"], json={
        "name": "E2E Fail Diner", "phone": "9611111111", "address": "1 Fail Road, Azamgarh",
        "latitude": "26.0680", "longitude": "83.1840",
    }).json()
    restaurant_id = restaurant["id"]
    product = client.post("/api/v1/restaurant/products", headers=owner["headers"], json={
        "name": "E2E Fail Item", "price": "100.00", "is_available": True,
    }).json()
    product_id = product["id"]
    address_a = _make_address(client, customer_a, "A")
    address_b = _make_address(client, customer_b, "B")

    # ---- 1. Customer cancellation ----
    order = _place_order(client, customer_a, product_id, address_a)
    order_id = order["id"]
    assert client.post(f"/api/v1/customer/orders/{order_id}/cancel", headers=customer_a["headers"]).status_code == 200
    assert client.get(f"/api/v1/customer/orders/{order_id}", headers=customer_a["headers"]).json()["status"] == "cancelled"
    rest_cancelled = client.get("/api/v1/restaurant/orders?status=cancelled", headers=owner["headers"])
    assert any(o["id"] == order_id for o in rest_cancelled.json())
    assert client.get(f"/api/v1/admin/orders/{order_id}", headers=admin["headers"]).json()["status"] == "cancelled"

    # ---- 2. Restaurant rejection ----
    order = _place_order(client, customer_a, product_id, address_a)
    order_id = order["id"]
    reject = client.post(f"/api/v1/restaurant/orders/{order_id}/reject", headers=owner["headers"], json={"reason": "Out of stock"})
    assert reject.status_code == 200 and reject.json()["status"] == "rejected"
    assert client.get(f"/api/v1/customer/orders/{order_id}", headers=customer_a["headers"]).json()["status"] == "rejected"
    notifs = client.get("/api/v1/customer/notifications", headers=customer_a["headers"])
    assert any(n["order_id"] == order_id and n["type"] == "order_rejected" for n in notifs.json())
    assert client.get(f"/api/v1/admin/orders/{order_id}", headers=admin["headers"]).json()["status"] == "rejected"

    # ---- 3. Rider rejection ----
    order = _place_order(client, customer_a, product_id, address_a)
    order_id = order["id"]
    _drive_to_ready(client, owner, order_id)
    reject_r = client.post(f"/api/v1/rider/deliveries/{order_id}/reject", headers=rider_a["headers"], json={"reason": "Too far"})
    assert reject_r.status_code == 200, reject_r.text
    assert client.get(f"/api/v1/admin/orders/{order_id}", headers=admin["headers"]).json()["status"] == "ready_for_pickup"
    rider_a_avail = client.get("/api/v1/rider/deliveries/available", headers=rider_a["headers"])
    assert not any(d["order_id"] == order_id for d in rider_a_avail.json())
    rider_b_avail = client.get("/api/v1/rider/deliveries/available", headers=rider_b["headers"])
    assert any(d["order_id"] == order_id for d in rider_b_avail.json())
    assert client.post(f"/api/v1/rider/deliveries/{order_id}/accept", headers=rider_b["headers"]).status_code == 200

    # ---- 4. Rider suspension ----
    order = _place_order(client, customer_a, product_id, address_a)
    order_id = order["id"]
    _drive_to_ready(client, owner, order_id)
    assert client.post(f"/api/v1/rider/deliveries/{order_id}/accept", headers=rider_a["headers"]).status_code == 200
    assert client.post(f"/api/v1/rider/deliveries/{order_id}/pickup", headers=rider_a["headers"]).status_code == 200
    suspend = client.post(f"/api/v1/admin/riders/{rider_a['id']}/suspend", headers=admin["headers"], json={"reason": "Safety report"})
    assert suspend.status_code == 200, suspend.text
    blocked = client.post(f"/api/v1/rider/deliveries/{order_id}/start", headers=rider_a["headers"])
    assert blocked.status_code == 403
    admin_rider = client.get(f"/api/v1/admin/riders/{rider_a['id']}", headers=admin["headers"])
    assert admin_rider.json()["approval_status"] == "SUSPENDED"
    assert client.get(f"/api/v1/admin/orders/{order_id}", headers=admin["headers"]).json()["status"] == "picked_up"
    reinstate = client.post(f"/api/v1/admin/riders/{rider_a['id']}/activate", headers=admin["headers"], json={"reason": "cleanup"})
    assert reinstate.status_code == 200
    client.patch("/api/v1/rider/status", headers=rider_a["headers"], json={"is_online": True})

    # ---- 5. Payment failure ----
    # Seed a PENDING razorpay payment directly and set a local (fake,
    # test-only) key id/secret, so this exercises the TRUE signature-
    # mismatch branch (PaymentService.verify_payment()'s own FAILED path,
    # with notifications) regardless of whatever real credentials this
    # environment's own .env carries — the automated suite always runs
    # with Razorpay unconfigured by default (see conftest.py), and this is
    # the one test that deliberately opts back in, locally, to reach the
    # signature-mismatch branch specifically rather than "not configured."
    from app.core.config import settings as app_settings
    from app.models.payment import Payment, PaymentProvider, PaymentStatus

    order = _place_order(client, customer_a, product_id, address_a)
    order_id = order["id"]
    db = _db(client)
    from uuid import UUID as _UUID

    payment = Payment(
        order_id=_UUID(order_id), user_id=_UUID(customer_a["id"]), provider=PaymentProvider.RAZORPAY,
        payment_status=PaymentStatus.PENDING, amount=Decimal(order["total"]), razorpay_order_id="order_e2e_fail",
    )
    db.add(payment)
    db.commit()
    payment_id = payment.id
    db.close()

    original_key_id = app_settings.RAZORPAY_KEY_ID
    original_secret = app_settings.RAZORPAY_KEY_SECRET
    app_settings.RAZORPAY_KEY_ID = "key_test_for_e2e_failure_path"
    app_settings.RAZORPAY_KEY_SECRET = "test-secret-for-e2e-failure-path"
    try:
        verify = client.post(f"/api/v1/payments/{payment_id}/verify", headers=customer_a["headers"], json={
            "provider_order_id": "order_e2e_fail", "provider_payment_id": "pay_e2e_fail",
            "signature": "not-the-real-signature",
        })
        assert verify.status_code == 400, verify.text
    finally:
        app_settings.RAZORPAY_KEY_ID = original_key_id
        app_settings.RAZORPAY_KEY_SECRET = original_secret

    assert client.get(f"/api/v1/customer/orders/{order_id}", headers=customer_a["headers"]).json()["is_paid"] is False
    admin_notifs = client.get("/api/v1/admin/notifications", headers=admin["headers"])
    assert any(n["order_id"] == order_id and n["type"] == "payment_failure" for n in admin_notifs.json())
    cust_notifs = client.get("/api/v1/customer/notifications", headers=customer_a["headers"])
    assert any(n["order_id"] == order_id and n["type"] == "payment_update" for n in cust_notifs.json())

    # ---- 6. Duplicate order request ----
    # SQLite (this suite's engine) has no safe way to run genuinely
    # concurrent writes across threads through TestClient — the same
    # constraint Phase 16's own test file documents. This phase's live
    # script already proved the real race against Postgres with two
    # genuinely simultaneous threaded HTTP requests (see the completion
    # report); here the exact same race is reproduced deterministically
    # with the established monkeypatch technique from
    # test_customer_orders.py's own test_two_concurrent_place_order_calls_never_create_two_orders:
    # a competitor wins the cart claim in the gap between this call's own
    # validate_checkout read and its own claim attempt.
    from sqlalchemy import update as sa_update

    from app.models.cart import Cart
    from app.services import orders as orders_module

    add = client.post("/api/v1/customer/cart/items", headers=customer_b["headers"], json={"product_id": product_id, "quantity": 1})
    assert add.status_code == 201
    real_validate_checkout = orders_module.validate_checkout

    def validate_checkout_then_let_a_competitor_win(db_, user, address_id):
        result = real_validate_checkout(db_, user, address_id)
        db_.execute(sa_update(Cart).where(Cart.id == result["cart"].id).values(restaurant_id=None))
        db_.commit()
        return result

    monkeypatch.setattr(orders_module, "validate_checkout", validate_checkout_then_let_a_competitor_win)
    loser = client.post("/api/v1/customer/orders", headers=customer_b["headers"], json={"address_id": address_b, "payment_method": "cod"})
    assert loser.status_code == 422, loser.text
    monkeypatch.setattr(orders_module, "validate_checkout", real_validate_checkout)

    listing = client.get("/api/v1/customer/orders", headers=customer_b["headers"])
    placed_today = [o for o in listing.json() if o["restaurant_id"] == restaurant_id and o["status"] == "placed"]
    assert len(placed_today) == 0  # the "competitor" claimed the cart but never actually placed an order

    # ---- 7. Duplicate rider acceptance ----
    # Same SQLite constraint as above — deterministic reproduction, matching
    # test_rider_concurrency_and_failure_handling.py's own established
    # sequential-acceptance pattern. The genuinely concurrent race (loser
    # rejected by the atomic claim's WHERE clause, not merely a stale list)
    # is what the live script already proved against real Postgres.
    order = _place_order(client, customer_a, product_id, address_a)
    order_id = order["id"]
    _drive_to_ready(client, owner, order_id)
    winner = client.post(f"/api/v1/rider/deliveries/{order_id}/accept", headers=rider_a["headers"])
    assert winner.status_code == 200, winner.text
    loser2 = client.post(f"/api/v1/rider/deliveries/{order_id}/accept", headers=rider_b["headers"])
    assert loser2.status_code in (404, 409), loser2.text
    admin_order = client.get(f"/api/v1/admin/orders/{order_id}", headers=admin["headers"])
    assert admin_order.json()["rider_name"] == "E2E riderA"

    # ---- 8. Unavailable product ----
    other_product = client.post("/api/v1/restaurant/products", headers=owner["headers"], json={
        "name": "E2E Unavailable Item", "price": "80.00", "is_available": True,
    }).json()
    pid = other_product["id"]
    assert client.post("/api/v1/customer/cart/items", headers=customer_a["headers"], json={"product_id": pid, "quantity": 1}).status_code == 201
    disable = client.patch(f"/api/v1/restaurant/products/{pid}", headers=owner["headers"], json={"is_available": False})
    assert disable.status_code == 200
    catalog = client.get(f"/api/v1/customer/restaurants/{restaurant_id}/products")
    assert not any(p["id"] == pid for p in catalog.json())
    preview = client.get("/api/v1/customer/checkout", headers=customer_a["headers"])
    assert len(preview.json()["removed_items"]) > 0

    # ---- 9. Closed restaurant ----
    assert client.post("/api/v1/customer/cart/items", headers=customer_a["headers"], json={"product_id": product_id, "quantity": 1}).status_code == 201
    close = client.patch("/api/v1/restaurant/status", headers=owner["headers"], json={"is_open": False})
    assert close.status_code == 200 and close.json()["is_open"] is False
    blocked_checkout = client.post("/api/v1/customer/orders/validate", headers=customer_a["headers"], json={"address_id": address_a})
    assert blocked_checkout.status_code == 200
    assert blocked_checkout.json()["valid"] is False
    assert any("closed" in issue.lower() for issue in blocked_checkout.json()["issues"])
    reopen = client.patch("/api/v1/restaurant/status", headers=owner["headers"], json={"is_open": True})
    assert reopen.status_code == 200 and reopen.json()["is_open"] is True

    # ---- 10. Expired authentication ----
    import jwt as pyjwt
    from datetime import UTC, datetime, timedelta
    from uuid import uuid4

    expired = pyjwt.encode(
        {"sub": customer_a["id"], "type": "access", "exp": datetime.now(UTC) - timedelta(minutes=1), "jti": str(uuid4())},
        app_settings.JWT_SECRET_KEY, algorithm=app_settings.JWT_ALGORITHM,
    )
    rejected = client.get("/api/v1/customer/orders", headers={"Authorization": f"Bearer {expired}"})
    assert rejected.status_code == 401
    still_works = client.get("/api/v1/customer/orders", headers=customer_a["headers"])
    assert still_works.status_code == 200

    # ---- 11. Unauthorized access ----
    final_order = _place_order(client, customer_a, product_id, address_a)
    final_id = final_order["id"]
    assert client.get(f"/api/v1/customer/orders/{final_id}", headers=customer_b["headers"]).status_code == 404
    assert client.get(f"/api/v1/rider/deliveries/{final_id}", headers=rider_b["headers"]).status_code == 404
    assert client.get("/api/v1/admin/dashboard", headers=customer_a["headers"]).status_code == 403
    assert client.get("/api/v1/customer/orders").status_code == 401
