"""Rider Portal — Phase 28: Concurrency & Failure Testing.

Difficult real-world cases, beyond the happy path every other test file
already covers:

  1. Two riders accept the same delivery (re-verified here; the live,
     genuinely multi-threaded proof against real Postgres lives outside
     the test suite — see the phase completion report).
  2. An order gets cancelled while a rider is already assigned to it, but
     before pickup — the rider must be notified and must not be able to
     continue. Scope note: neither the restaurant-owner portal nor the
     customer's own self-service endpoint can actually cancel an order
     once a rider is assigned in this system today (customer self-cancel
     is restricted to PLACED/CONFIRMED; there is no restaurant-facing
     cancel endpoint at all, only reject-before-accepting) — so both
     scenarios are exercised through the one mechanism that genuinely
     reaches that state, the admin status override, which is the same
     transition_order_status() choke point either a future restaurant- or
     customer-initiated cancel would also have to go through.
  3. A rider's app goes offline or is force-quit mid-delivery — recovery
     is proven by confirming a "cold" GET (no prior client state at all)
     fully reconstructs the correct in-progress state at every stage.
  4. An access token expires mid-delivery — refreshing it and continuing
     must resume exactly where the rider left off, with no state lost.
  5. Duplicate button presses / network retries must never duplicate a
     state transition or a financial side effect — the per-endpoint
     idempotent-retry behavior (accept/pickup/start/complete/cod-collect
     all returning their already-applied result rather than erroring on
     an exact repeat) is unit-tested in each endpoint's own test file;
     this file's contribution is one consolidated test driving the whole
     lifecycle with a retry interleaved after every single step, proving
     the final state and financial ledger come out correct regardless.
"""

from decimal import Decimal

from app.core.security import create_access_token, hash_password
from app.models.user import User, UserRole


def _register_and_login_rider(client, email="rider-fail@example.com", phone="9940000010", name="Ravi Kumar"):
    client.post(
        "/api/v1/auth/register",
        json={"name": name, "email": email, "password": "secure-pass-123", "phone": phone, "role": "RIDER"},
    )
    login = client.post("/api/v1/auth/login", json={"email": email, "password": "secure-pass-123"})
    return login.json()["access_token"], login.json()["refresh_token"]


def _rider_id(client, token):
    return client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"}).json()["id"]


def _make_admin(client, email="admin-fail@example.com", phone="9940000099"):
    from app.db.session import get_db

    db_gen = client.app.dependency_overrides[get_db]()
    db = next(db_gen)
    admin = User(name="Admin", email=email, phone=phone, password_hash=hash_password("x"), role=UserRole.ADMIN)
    db.add(admin)
    db.commit()
    token = create_access_token(admin.id)
    db.close()
    return token


def _make_rider_online(client, token, admin_token, rider_id):
    rider_headers = {"Authorization": f"Bearer {token}"}
    admin_headers = {"Authorization": f"Bearer {admin_token}"}
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


def _seed_ready_order(db, payment_method="online"):
    import uuid

    from app.models.order import OrderStatus
    from app.models.product import Product
    from app.models.restaurant import Restaurant
    from app.services.addresses import create_address
    from app.services.cart import add_item, create_cart_for_user
    from app.services.orders import create_order, transition_order_status

    suffix = uuid.uuid4().hex[:8]
    owner = User(name="Owner", email=f"owner-{suffix}@example.com", phone=f"97{suffix[:8]}", password_hash=hash_password("x"), role=UserRole.RESTAURANT_OWNER)
    db.add(owner)
    db.commit()
    restaurant = Restaurant(
        owner_id=owner.id, name="Diner", phone="9876500000", address="Main Road",
        latitude=Decimal("12.1"), longitude=Decimal("77.1"),
        minimum_order=Decimal("0.00"), delivery_fee=Decimal("40.00"),
    )
    db.add(restaurant)
    db.commit()
    customer = User(name="Cust", email=f"cust-{suffix}@example.com", phone=f"96{suffix[:8]}", password_hash=hash_password("x"), role=UserRole.CUSTOMER)
    db.add(customer)
    db.commit()
    product = Product(restaurant_id=restaurant.id, name="Item", price=Decimal("100.00"))
    db.add(product)
    db.commit()
    cart = create_cart_for_user(db, customer.id)
    add_item(db, cart, product.id, 1)
    address = create_address(db, customer.id, {
        "label": "Home", "recipient_name": "Cust", "phone": "9999999999",
        "address_line": "1 Road", "city": "Bengaluru", "state": "Karnataka", "postal_code": "560001",
    })
    order = create_order(db, customer, address.id, payment_method=payment_method)
    transition_order_status(db, order, OrderStatus.CONFIRMED)
    transition_order_status(db, order, OrderStatus.PREPARING)
    transition_order_status(db, order, OrderStatus.READY_FOR_PICKUP)
    return order


# --------------------------- 1. Two riders accept the same delivery ---------------------------


def test_two_riders_accept_same_delivery_only_one_succeeds(client):
    """Rider A -> ACCEPT succeeds; Rider B -> ACCEPT fails. Deterministic
    (non-threaded) confirmation of Phase 10's atomic-claim guarantee — the
    genuinely concurrent, multi-threaded proof against real Postgres lives
    outside this suite (SQLite's single-writer model can't meaningfully
    demonstrate a race)."""
    from app.db.session import get_db

    token_a, _ = _register_and_login_rider(client, email="two-riders-a@example.com", phone="9940000011")
    rider_a_id = _rider_id(client, token_a)
    token_b, _ = _register_and_login_rider(client, email="two-riders-b@example.com", phone="9940000012")
    rider_b_id = _rider_id(client, token_b)
    admin_token = _make_admin(client, email="admin2-fail@example.com", phone="9940000098")
    _make_rider_online(client, token_a, admin_token, rider_a_id)
    _make_rider_online(client, token_b, admin_token, rider_b_id)

    db_gen = client.app.dependency_overrides[get_db]()
    db = next(db_gen)
    order = _seed_ready_order(db)
    order_id = str(order.id)
    db.close()

    accept_a = client.post(f"/api/v1/rider/deliveries/{order_id}/accept", headers={"Authorization": f"Bearer {token_a}"})
    accept_b = client.post(f"/api/v1/rider/deliveries/{order_id}/accept", headers={"Authorization": f"Bearer {token_b}"})

    assert accept_a.status_code == 200
    assert accept_a.json()["rider_id"] == rider_a_id
    # Two genuinely simultaneous requests would race inside the atomic
    # UPDATE itself and the loser would get 409 ("already accepted by
    # another rider") — see accept_delivery()'s own docstring. Called
    # sequentially like this, Rider B's own pre-check independently sees
    # the order is no longer available before ever reaching that UPDATE,
    # so the observable outcome here is a 404 — still a hard, unambiguous
    # refusal, just via the earlier of the two guards.
    assert accept_b.status_code == 404


# --------------------------- 2. Cancellation while a rider is assigned ---------------------------


def test_order_cancelled_after_assignment_notifies_rider_and_blocks_continuation(client):
    """An order cancelled (here: by admin override — see module docstring)
    after a rider has accepted it, but before pickup, must (a) notify that
    rider, (b) flip their DeliveryAssignment to CANCELLED, and (c) refuse
    every further action they try to take on it."""
    from uuid import UUID as _UUID

    from app.db.session import get_db
    from app.models.delivery_assignment import DeliveryAssignment
    from app.models.order import Order, OrderStatus
    from app.services.orders import transition_order_status

    token, _ = _register_and_login_rider(client, email="cancel-notify@example.com", phone="9940000013")
    rider_id = _rider_id(client, token)
    admin_token = _make_admin(client, email="admin3-fail@example.com", phone="9940000097")
    _make_rider_online(client, token, admin_token, rider_id)

    db_gen = client.app.dependency_overrides[get_db]()
    db = next(db_gen)
    order = _seed_ready_order(db, payment_method="cod")  # so cod-collect below is a meaningful check, not a 400
    order_id = str(order.id)
    db.close()

    headers = {"Authorization": f"Bearer {token}"}
    assert client.post(f"/api/v1/rider/deliveries/{order_id}/accept", headers=headers).status_code == 200

    db_gen2 = client.app.dependency_overrides[get_db]()
    db2 = next(db_gen2)
    order_row = db2.query(Order).filter(Order.id == _UUID(order_id)).first()
    transition_order_status(db2, order_row, OrderStatus.CANCELLED)
    db2.close()

    # (a) Notified.
    notifications = client.get("/api/v1/rider/notifications", headers=headers).json()
    assert any(n["type"] == "delivery_cancelled" and n["order_id"] == order_id for n in notifications)

    # (b) Assignment reflects it.
    db_gen3 = client.app.dependency_overrides[get_db]()
    db3 = next(db_gen3)
    assignment = db3.query(DeliveryAssignment).filter(DeliveryAssignment.order_id == _UUID(order_id)).first()
    assert assignment.status.value == "CANCELLED"
    db3.close()

    # (c) Every further action is refused, not silently accepted.
    for action in ("arrived", "pickup", "start", "complete", "cod-collect"):
        response = client.post(f"/api/v1/rider/deliveries/{order_id}/{action}", headers=headers)
        assert response.status_code == 409, f"{action} should be refused once the order is cancelled"

    # The rider's own view is unambiguous about why.
    detail = client.get(f"/api/v1/rider/deliveries/{order_id}", headers=headers).json()
    assert detail["status"] == "cancelled"
    assert detail["assignment_status"] == "CANCELLED"


def test_order_cancelled_before_any_rider_assignment_never_reaches_a_rider(client):
    """The earlier-stage reading of "customer cancels before pickup": a
    customer's own real self-service cancel endpoint only works while an
    order is still PLACED/CONFIRMED — before any rider could possibly be
    involved. Confirms the cancelled order never appears as available, and
    a rider guessing its ID still can't act on it."""
    from app.db.session import get_db

    token, _ = _register_and_login_rider(client, email="cancel-early@example.com", phone="9940000014")
    rider_id = _rider_id(client, token)
    admin_token = _make_admin(client, email="admin4-fail@example.com", phone="9940000096")
    _make_rider_online(client, token, admin_token, rider_id)

    db_gen = client.app.dependency_overrides[get_db]()
    db = next(db_gen)
    import uuid

    from app.models.product import Product
    from app.models.restaurant import Restaurant
    from app.services.addresses import create_address
    from app.services.cart import add_item, create_cart_for_user
    from app.services.orders import create_order

    suffix = uuid.uuid4().hex[:8]
    owner = User(name="Owner", email=f"owner-{suffix}@example.com", phone=f"97{suffix[:8]}", password_hash=hash_password("x"), role=UserRole.RESTAURANT_OWNER)
    db.add(owner)
    db.commit()
    restaurant = Restaurant(
        owner_id=owner.id, name="Diner", phone="9876500000", address="Main Road",
        latitude=Decimal("12.1"), longitude=Decimal("77.1"), minimum_order=Decimal("0.00"), delivery_fee=Decimal("40.00"),
    )
    db.add(restaurant)
    db.commit()
    customer = User(name="Cust", email=f"cust-{suffix}@example.com", phone=f"96{suffix[:8]}", password_hash=hash_password("x"), role=UserRole.CUSTOMER)
    db.add(customer)
    db.commit()
    product = Product(restaurant_id=restaurant.id, name="Item", price=Decimal("100.00"))
    db.add(product)
    db.commit()
    cart = create_cart_for_user(db, customer.id)
    add_item(db, cart, product.id, 1)
    address = create_address(db, customer.id, {
        "label": "Home", "recipient_name": "Cust", "phone": "9999999999",
        "address_line": "1 Road", "city": "Bengaluru", "state": "Karnataka", "postal_code": "560001",
    })
    order = create_order(db, customer, address.id)
    order_id = str(order.id)
    customer_token = create_access_token(customer.id)
    db.close()

    cancel = client.post(
        f"/api/v1/customer/orders/{order_id}/cancel", headers={"Authorization": f"Bearer {customer_token}"}
    )
    assert cancel.status_code == 200
    assert cancel.json()["status"] == "cancelled"

    available = client.get("/api/v1/rider/deliveries/available", headers={"Authorization": f"Bearer {token}"}).json()
    assert all(d["order_id"] != order_id for d in available)

    accept_attempt = client.post(
        f"/api/v1/rider/deliveries/{order_id}/accept", headers={"Authorization": f"Bearer {token}"}
    )
    assert accept_attempt.status_code == 404


# --------------------------- 3. Offline / app closed -> recovery ---------------------------


def test_app_relaunch_recovers_exact_delivery_state_at_every_stage(client):
    """Simulates "rider loses internet / force-quits the app" by treating
    every GET below as a completely cold read with no prior client-side
    state carried over — the same GET calls a freshly (re)launched app
    would make. If these always reflect the true current stage, the app
    can always recover safely regardless of what it lost locally."""
    from app.db.session import get_db

    token, _ = _register_and_login_rider(client, email="recover-app@example.com", phone="9940000015")
    rider_id = _rider_id(client, token)
    admin_token = _make_admin(client, email="admin5-fail@example.com", phone="9940000095")
    _make_rider_online(client, token, admin_token, rider_id)

    db_gen = client.app.dependency_overrides[get_db]()
    db = next(db_gen)
    order = _seed_ready_order(db)
    order_id = str(order.id)
    db.close()

    headers = {"Authorization": f"Bearer {token}"}

    def cold_read():
        dashboard = client.get("/api/v1/rider/dashboard", headers=headers).json()
        detail = client.get(f"/api/v1/rider/deliveries/{order_id}", headers=headers).json()
        return dashboard, detail

    client.post(f"/api/v1/rider/deliveries/{order_id}/accept", headers=headers)
    dashboard, detail = cold_read()
    assert dashboard["current_assignment"]["id"] == order_id
    assert dashboard["current_assignment"]["status"] == "rider_assigned"
    assert detail["assignment_status"] == "ACCEPTED"

    client.post(f"/api/v1/rider/deliveries/{order_id}/pickup", headers=headers)
    dashboard, detail = cold_read()
    assert dashboard["current_assignment"]["status"] == "picked_up"
    assert detail["assignment_status"] == "PICKED_UP"

    client.post(f"/api/v1/rider/deliveries/{order_id}/start", headers=headers)
    dashboard, detail = cold_read()
    assert dashboard["current_assignment"]["status"] == "out_for_delivery"
    assert detail["assignment_status"] == "OUT_FOR_DELIVERY"

    client.post(f"/api/v1/rider/deliveries/{order_id}/complete", headers=headers)
    dashboard, detail = cold_read()
    assert dashboard["current_assignment"] is None  # nothing active anymore
    assert detail["status"] == "delivered"


# --------------------------- 4. Token expires mid-delivery ---------------------------


def test_expired_access_token_is_rejected_then_refresh_resumes_the_same_delivery(client):
    """A rider's access token expiring mid-delivery must not lose their
    place — refreshing it and continuing must pick up exactly where they
    left off, with the delivery's own state untouched by the expiry."""
    import jwt

    from app.core.config import settings
    from app.db.session import get_db

    token, refresh_token = _register_and_login_rider(client, email="token-expiry@example.com", phone="9940000016")
    rider_id = _rider_id(client, token)
    admin_token = _make_admin(client, email="admin6-fail@example.com", phone="9940000094")
    _make_rider_online(client, token, admin_token, rider_id)

    db_gen = client.app.dependency_overrides[get_db]()
    db = next(db_gen)
    order = _seed_ready_order(db)
    order_id = str(order.id)
    db.close()

    headers = {"Authorization": f"Bearer {token}"}
    assert client.post(f"/api/v1/rider/deliveries/{order_id}/accept", headers=headers).status_code == 200
    assert client.post(f"/api/v1/rider/deliveries/{order_id}/pickup", headers=headers).status_code == 200

    # Craft a genuinely expired access token for this same rider (same
    # signing key/algorithm, just with exp in the past) rather than waiting
    # out ACCESS_TOKEN_EXPIRE_MINUTES for real.
    from datetime import datetime, timedelta, timezone
    from uuid import uuid4

    expired_token = jwt.encode(
        {
            "sub": rider_id, "type": "access",
            "exp": datetime.now(timezone.utc) - timedelta(minutes=1),
            "jti": str(uuid4()),
        },
        settings.JWT_SECRET_KEY,
        algorithm=settings.JWT_ALGORITHM,
    )
    expired_headers = {"Authorization": f"Bearer {expired_token}"}
    rejected = client.post(f"/api/v1/rider/deliveries/{order_id}/start", headers=expired_headers)
    assert rejected.status_code == 401

    refresh = client.post("/api/v1/auth/refresh", json={"refresh_token": refresh_token})
    assert refresh.status_code == 200
    new_token = refresh.json()["access_token"]
    new_headers = {"Authorization": f"Bearer {new_token}"}

    resumed = client.post(f"/api/v1/rider/deliveries/{order_id}/start", headers=new_headers)
    assert resumed.status_code == 200
    assert resumed.json()["status"] == "out_for_delivery"

    detail = client.get(f"/api/v1/rider/deliveries/{order_id}", headers=new_headers).json()
    assert detail["assignment_status"] == "OUT_FOR_DELIVERY"


# --------------------------- 5. Retries interleaved through the whole flow ---------------------------


def test_network_retries_at_every_step_never_duplicate_state_or_ledger_entries(client):
    """The consolidated scenario: imagine every single call in the flow got
    retried once (client didn't see the response, so it tried again). The
    final state and the rider's financial ledger must come out exactly as
    if each step had been called only once."""
    from app.db.session import get_db

    token, _ = _register_and_login_rider(client, email="retry-everywhere@example.com", phone="9940000017")
    rider_id = _rider_id(client, token)
    admin_token = _make_admin(client, email="admin7-fail@example.com", phone="9940000093")
    _make_rider_online(client, token, admin_token, rider_id)

    db_gen = client.app.dependency_overrides[get_db]()
    db = next(db_gen)
    order = _seed_ready_order(db, payment_method="cod")
    order_id = str(order.id)
    expected_total = order.total
    db.close()

    headers = {"Authorization": f"Bearer {token}"}

    def call_twice(path):
        first = client.post(f"/api/v1/rider/deliveries/{order_id}/{path}", headers=headers)
        second = client.post(f"/api/v1/rider/deliveries/{order_id}/{path}", headers=headers)
        assert first.status_code == 200, f"{path} first call failed: {first.json()}"
        assert second.status_code == 200, f"{path} retried call was rejected instead of replayed: {second.json()}"
        return first, second

    call_twice("accept")
    call_twice("pickup")
    call_twice("start")
    call_twice("cod-collect")
    call_twice("complete")

    final = client.get(f"/api/v1/rider/deliveries/{order_id}", headers=headers).json()
    assert final["status"] == "delivered"
    history_counts = {}
    for entry in client.get("/api/v1/rider/history", headers=headers).json():
        history_counts[entry["order_id"]] = history_counts.get(entry["order_id"], 0) + 1
    assert history_counts.get(order_id, 0) == 1  # not duplicated in history either

    earnings = client.get("/api/v1/rider/earnings", headers=headers).json()
    matching_earnings = [e for e in earnings if e["order_id"] == order_id]
    assert len(matching_earnings) == 1
    assert matching_earnings[0]["amount"] == "40.00"

    wallet = client.get("/api/v1/rider/wallet", headers=headers).json()
    assert Decimal(wallet["total_earnings"]) == Decimal("40.00")
    assert Decimal(wallet["total_cod_collected"]) == Decimal(expected_total)


# --------------------------- 6. Rider suspended after PICKED_UP: no recovery path exists ---------------------------


def test_rider_suspended_after_pickup_leaves_the_order_stuck_with_no_admin_recovery(client):
    """Integration Phase 15 — a documented gap, not a fix: once an order
    reaches PICKED_UP, VALID_TRANSITIONS only allows PICKED_UP -> OUT_FOR_DELIVERY
    -> DELIVERED, and ADMIN_CANCELLABLE_STATUSES / ADMIN_REASSIGNABLE_STATUSES
    both exclude PICKED_UP and OUT_FOR_DELIVERY (see app/services/orders.py).
    If the one rider holding the order is suspended (or otherwise made
    unable to continue) after physically picking it up, no one — not that
    rider, not another rider via reassignment, not an admin via cancel —
    can move the order to any other state through any existing endpoint.
    This test pins down that the order is left in exactly this stuck state
    today, as a basis for a product decision on whether a recovery action
    (force-cancel, force-reassign, or force-complete from PICKED_UP/
    OUT_FOR_DELIVERY) should be built."""
    from app.db.session import get_db

    token, _ = _register_and_login_rider(client, email="stuck-order-rider@example.com", phone="9940000030")
    rider_id = _rider_id(client, token)
    admin_token = _make_admin(client, email="admin-stuck@example.com", phone="9940000031")
    _make_rider_online(client, token, admin_token, rider_id)

    db_gen = client.app.dependency_overrides[get_db]()
    db = next(db_gen)
    order = _seed_ready_order(db)
    order_id = str(order.id)
    db.close()

    headers = {"Authorization": f"Bearer {token}"}
    admin_headers = {"Authorization": f"Bearer {admin_token}"}
    assert client.post(f"/api/v1/rider/deliveries/{order_id}/accept", headers=headers).status_code == 200
    assert client.post(f"/api/v1/rider/deliveries/{order_id}/pickup", headers=headers).status_code == 200

    # The rider is suspended mid-delivery (e.g. a safety report comes in).
    suspend = client.patch(
        f"/api/v1/admin/riders/{rider_id}/verification", headers=admin_headers, json={"approval_status": "SUSPENDED"}
    )
    assert suspend.status_code == 200

    # The suspended rider can no longer advance their own delivery.
    blocked = client.post(f"/api/v1/rider/deliveries/{order_id}/start", headers=headers)
    assert blocked.status_code == 403

    # Admin cannot reassign it either — PICKED_UP is outside ADMIN_REASSIGNABLE_STATUSES.
    other_rider_token = _register_and_login_rider(client, email="rescue-rider@example.com", phone="9940000032")[0]
    other_rider_id = _rider_id(client, other_rider_token)
    reassign = client.post(
        f"/api/v1/admin/orders/{order_id}/reassign-rider", headers=admin_headers,
        json={"new_rider_id": other_rider_id, "reason": "Original rider suspended mid-delivery"},
    )
    assert reassign.status_code == 409

    # Admin cannot cancel it either — PICKED_UP is outside ADMIN_CANCELLABLE_STATUSES.
    cancel = client.post(
        f"/api/v1/admin/orders/{order_id}/cancel", headers=admin_headers, json={"reason": "Rider suspended, order stuck"}
    )
    assert cancel.status_code == 409

    # The order is left exactly here — no orphaned *rows* (rider_id, status,
    # and the DeliveryAssignment are all internally consistent), but the
    # order itself is permanently unprogressable through any endpoint today.
    stuck = client.get(f"/api/v1/admin/orders/{order_id}", headers=admin_headers).json()
    assert stuck["status"] == "picked_up"


# --------------------------- 7. Two truly concurrent "complete delivery" calls never double-pay ---------------------------


def test_two_concurrent_complete_delivery_calls_never_double_credit_the_rider(client):
    """Database Transaction Testing (Phase 24) — live-proved (5/5 threaded
    trials against real Postgres, see this phase's completion report) that
    transition_order_status() used to do a plain `order.status = new_status`
    attribute assignment: two genuinely concurrent complete_delivery() calls
    (e.g. two devices, or a request racing its own lost-response retry)
    could both read OUT_FOR_DELIVERY before either committed, both pass the
    transition check, and both run every DELIVERED side effect — including
    record_delivery_fee_earning(), which has no existence check — crediting
    the rider twice for one delivery. Fixed with the same atomic conditional-
    UPDATE guard accept_delivery() already uses for its rider claim.

    SQLite's single-writer model can't demonstrate genuine concurrency (see
    test_two_riders_accept_same_delivery_only_one_succeeds's own note above),
    so this reproduces the race deterministically: drive the order to
    DELIVERED once (as the "winning" concurrent request would), then force
    the in-memory Order object back to OUT_FOR_DELIVERY — exactly what a
    second request's own earlier, now-stale read would still show — and
    confirm transition_order_status rejects it instead of silently
    re-applying every side effect a second time."""
    from app.db.session import get_db
    from app.models.order import OrderStatus
    from app.services.orders import transition_order_status

    token, _ = _register_and_login_rider(client, email="race-complete@example.com", phone="9940000040")
    rider_id = _rider_id(client, token)
    admin_token = _make_admin(client, email="admin8-fail@example.com", phone="9940000094")
    _make_rider_online(client, token, admin_token, rider_id)

    db_gen = client.app.dependency_overrides[get_db]()
    db = next(db_gen)
    order = _seed_ready_order(db, payment_method="online")
    order_id = str(order.id)
    headers = {"Authorization": f"Bearer {token}"}
    db.close()

    assert client.post(f"/api/v1/rider/deliveries/{order_id}/accept", headers=headers).status_code == 200
    assert client.post(f"/api/v1/rider/deliveries/{order_id}/pickup", headers=headers).status_code == 200
    assert client.post(f"/api/v1/rider/deliveries/{order_id}/start", headers=headers).status_code == 200

    db_gen2 = client.app.dependency_overrides[get_db]()
    db2 = next(db_gen2)
    order_obj = db2.get(type(order), order.id)

    # The "winning" concurrent request: completes normally.
    transition_order_status(db2, order_obj, OrderStatus.DELIVERED, "Delivered by rider")
    assert order_obj.status == OrderStatus.DELIVERED

    # The "losing" concurrent request's own earlier read — still OUT_FOR_DELIVERY,
    # because it read the order before the winner above had committed. Set
    # under no_autoflush: a plain attribute assignment would otherwise get
    # flushed to the database by the very next query (SQLAlchemy's default
    # autoflush), actually reverting the committed row instead of leaving
    # this Python object merely stale like a genuine second request's own
    # earlier read would be.
    with db2.no_autoflush:
        order_obj.status = OrderStatus.OUT_FOR_DELIVERY

        try:
            transition_order_status(db2, order_obj, OrderStatus.DELIVERED, "Delivered by rider (loser)")
            assert False, "the losing concurrent transition should have been rejected"
        except ValueError as exc:
            assert "already changed" in str(exc)
    db2.close()


# --------------------------- 8. Assignment conflicts are logged ---------------------------


def test_reject_then_accept_the_same_order_is_logged_as_an_assignment_conflict(client, caplog):
    """Logging & Error Handling (Phase 26) — REJECTED -> ACCEPTED for the
    same rider/order is a deterministic, sequential assignment conflict
    (see test_rider_assignment_state_machine.py's own equivalent test for
    why this exact scenario, rather than a genuine race, is what SQLite can
    prove here) and must reach a server-side log."""
    import logging

    from app.db.session import get_db

    token, _ = _register_and_login_rider(client, email="p26-assign-conflict@example.com", phone="9940000053")
    rider_id = _rider_id(client, token)
    admin_token = _make_admin(client, email="p26-assign-admin@example.com", phone="9940000054")
    _make_rider_online(client, token, admin_token, rider_id)

    db_gen = client.app.dependency_overrides[get_db]()
    db = next(db_gen)
    order = _seed_ready_order(db)
    order_id = str(order.id)
    db.close()

    headers = {"Authorization": f"Bearer {token}"}
    reject = client.post(f"/api/v1/rider/deliveries/{order_id}/reject", headers=headers, json={"reason": "too far"})
    assert reject.status_code == 200

    with caplog.at_level(logging.WARNING):
        accept = client.post(f"/api/v1/rider/deliveries/{order_id}/accept", headers=headers)
    assert accept.status_code == 409
    assert any("Assignment conflict" in r.message for r in caplog.records)
