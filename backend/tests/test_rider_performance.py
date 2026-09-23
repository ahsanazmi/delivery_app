"""Rider Portal — Phase 30: Rider Performance.

Correctness regression tests for the concrete fixes made during this
review: the available-deliveries N+1 fix (multiple different restaurants in
one response must still resolve correctly now that restaurants are batch-
fetched instead of looked up one at a time) and the new pagination added to
/rider/earnings and /rider/wallet/settlements (previously unbounded lists).
Index additions and the notifications cap are structural/scale changes with
no separate behavioral contract to test beyond "still returns the right
rows," which the existing test suites for those endpoints already cover.
"""

from decimal import Decimal

from app.core.security import create_access_token, hash_password
from app.models.user import User, UserRole


def _register_and_login_rider(client, email="rider-perf@example.com", phone="9950000210", name="Ravi Kumar"):
    client.post(
        "/api/v1/auth/register",
        json={"name": name, "email": email, "password": "secure-pass-123", "phone": phone, "role": "RIDER"},
    )
    login = client.post("/api/v1/auth/login", json={"email": email, "password": "secure-pass-123"})
    return login.json()["access_token"]


def _rider_id(client, token):
    return client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"}).json()["id"]


def _make_admin(client, email="admin-perf@example.com", phone="9950000299"):
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


def _seed_ready_order(db, restaurant_name, delivery_fee):
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
        owner_id=owner.id, name=restaurant_name, phone="9876500000", address=f"{restaurant_name} Road",
        latitude=Decimal("12.10"), longitude=Decimal("77.10"),
        minimum_order=Decimal("0.00"), delivery_fee=delivery_fee,
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
    order = create_order(db, customer, address.id, payment_method="online")
    transition_order_status(db, order, OrderStatus.CONFIRMED)
    transition_order_status(db, order, OrderStatus.PREPARING)
    transition_order_status(db, order, OrderStatus.READY_FOR_PICKUP)
    return order, restaurant


def test_available_deliveries_from_multiple_restaurants_resolve_correctly(client):
    """Regression test for the N+1 fix: batch-fetching restaurants must
    produce identical per-order results to the old one-at-a-time lookup —
    each order's own restaurant details, not mixed up with another's."""
    from app.db.session import get_db

    token = _register_and_login_rider(client)
    rider_id = _rider_id(client, token)
    admin_token = _make_admin(client)
    _make_rider_online(client, token, admin_token, rider_id)

    db_gen = client.app.dependency_overrides[get_db]()
    db = next(db_gen)
    order_a, _ = _seed_ready_order(db, "Alpha Diner", Decimal("30.00"))
    order_b, _ = _seed_ready_order(db, "Beta Diner", Decimal("45.00"))
    order_c, _ = _seed_ready_order(db, "Gamma Diner", Decimal("60.00"))
    order_a_id, order_b_id, order_c_id = str(order_a.id), str(order_b.id), str(order_c.id)
    db.close()

    response = client.get("/api/v1/rider/deliveries/available", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200
    by_order_id = {item["order_id"]: item for item in response.json()}

    assert by_order_id[order_a_id]["restaurant_name"] == "Alpha Diner"
    assert Decimal(by_order_id[order_a_id]["estimated_earning"]) == Decimal("30.00")
    assert by_order_id[order_b_id]["restaurant_name"] == "Beta Diner"
    assert Decimal(by_order_id[order_b_id]["estimated_earning"]) == Decimal("45.00")
    assert by_order_id[order_c_id]["restaurant_name"] == "Gamma Diner"
    assert Decimal(by_order_id[order_c_id]["estimated_earning"]) == Decimal("60.00")


def test_available_deliveries_query_count_does_not_scale_with_order_count(client):
    """The concrete N+1 claim, verified directly: listing N available
    orders from N distinct restaurants must issue a fixed, small number of
    queries — not one additional query per order."""
    from sqlalchemy import event

    from app.db.session import get_db

    token = _register_and_login_rider(client, email="perf-queries@example.com", phone="9950000211")
    rider_id = _rider_id(client, token)
    admin_token = _make_admin(client, email="admin2-perf@example.com", phone="9950000298")
    _make_rider_online(client, token, admin_token, rider_id)

    db_gen = client.app.dependency_overrides[get_db]()
    db = next(db_gen)
    for i in range(8):
        _seed_ready_order(db, f"Restaurant {i}", Decimal("30.00"))

    queries = []
    engine = db.get_bind()
    listener = lambda *args: queries.append(args)  # noqa: E731
    event.listen(engine, "before_cursor_execute", listener)
    try:
        from app.services.rider_deliveries import list_available_deliveries

        rider = db.query(User).filter(User.email == "perf-queries@example.com").first()
        results = list_available_deliveries(db, rider)
        assert len(results) == 8
    finally:
        event.remove(engine, "before_cursor_execute", listener)
        db.close()

    # A handful of fixed queries (partner lookup, rejected-ids subselect
    # folded into the main query, the orders query, one batched restaurant
    # query) — nowhere near the 8 extra one-per-restaurant queries the old
    # N+1 code would have issued on top of that.
    assert len(queries) <= 6, f"Expected a small fixed query count, got {len(queries)}"


def test_earnings_endpoint_is_paginated(client):
    from app.db.session import get_db

    token = _register_and_login_rider(client, email="earnings-page@example.com", phone="9950000212")
    rider_id = _rider_id(client, token)
    admin_token = _make_admin(client, email="admin3-perf@example.com", phone="9950000297")
    _make_rider_online(client, token, admin_token, rider_id)

    headers = {"Authorization": f"Bearer {token}"}
    for i in range(3):
        db_gen = client.app.dependency_overrides[get_db]()
        db = next(db_gen)
        order, _restaurant = _seed_ready_order(db, f"Diner {i}", Decimal("40.00"))
        order_id = str(order.id)
        db.close()

        client.post(f"/api/v1/rider/deliveries/{order_id}/accept", headers=headers)
        client.post(f"/api/v1/rider/deliveries/{order_id}/pickup", headers=headers)
        client.post(f"/api/v1/rider/deliveries/{order_id}/start", headers=headers)
        client.post(f"/api/v1/rider/deliveries/{order_id}/complete", headers=headers)

    page1 = client.get("/api/v1/rider/earnings?page=1&limit=2", headers=headers).json()
    page2 = client.get("/api/v1/rider/earnings?page=2&limit=2", headers=headers).json()
    assert len(page1) == 2
    assert len(page2) == 1
    assert {e["id"] for e in page1}.isdisjoint({e["id"] for e in page2})


def test_settlements_endpoint_is_paginated(client):
    from uuid import UUID as _UUID

    from app.db.session import get_db
    from app.models.rider_settlement import RiderSettlement, SettlementType

    token = _register_and_login_rider(client, email="settlements-page@example.com", phone="9950000213")
    rider_id = _rider_id(client, token)

    db_gen = client.app.dependency_overrides[get_db]()
    db = next(db_gen)
    for i in range(3):
        db.add(RiderSettlement(rider_id=_UUID(rider_id), settlement_type=SettlementType.PAYOUT, amount=Decimal(f"{10 + i}.00")))
    db.commit()
    db.close()

    headers = {"Authorization": f"Bearer {token}"}
    page1 = client.get("/api/v1/rider/wallet/settlements?page=1&limit=2", headers=headers).json()
    page2 = client.get("/api/v1/rider/wallet/settlements?page=2&limit=2", headers=headers).json()
    assert len(page1) == 2
    assert len(page2) == 1


def test_legacy_rider_orders_list_does_not_issue_a_query_per_order(client):
    """Performance Baseline (Phase 25) — GET /rider/orders (still called by
    rider-mobile's own listRiderOrders()) uses the same OrderRead schema as
    the customer order list, serializing .items/.status_history for every
    row. It also had no cap at all — every order this rider had ever been
    assigned, all-time. Verified the same way this file's own Phase 30 N+1
    test already does: query count must stay fixed regardless of how many
    orders (and items/history entries per order) exist."""
    from sqlalchemy import event

    from app.db.session import get_db
    from app.services.orders import list_rider_orders

    token = _register_and_login_rider(client, email="legacy-orders-perf@example.com", phone="9950000220")
    rider_id = _rider_id(client, token)
    admin_token = _make_admin(client, email="admin4-perf@example.com", phone="9950000296")
    _make_rider_online(client, token, admin_token, rider_id)
    headers = {"Authorization": f"Bearer {token}"}

    for i in range(4):
        db_gen = client.app.dependency_overrides[get_db]()
        db = next(db_gen)
        order, _restaurant = _seed_ready_order(db, f"Legacy Diner {i}", Decimal("35.00"))
        order_id = str(order.id)
        db.close()
        client.post(f"/api/v1/rider/deliveries/{order_id}/accept", headers=headers)

    db_gen = client.app.dependency_overrides[get_db]()
    db = next(db_gen)
    from uuid import UUID as _UUID

    rider_uuid = _UUID(rider_id)

    queries = []
    engine = db.get_bind()
    listener = lambda *args: queries.append(args)  # noqa: E731
    event.listen(engine, "before_cursor_execute", listener)
    try:
        results = list_rider_orders(db, rider_uuid)
        assert len(results) == 4
        for order in results:
            assert order.items is not None
            assert order.status_history is not None
    finally:
        event.remove(engine, "before_cursor_execute", listener)
        db.close()

    assert len(queries) <= 3, f"Expected a small fixed query count, got {len(queries)}"


def test_notifications_list_is_capped(client):
    """Verifies the hard cap directly against the service, without needing
    to actually insert >100 rows through the slower HTTP layer."""
    from uuid import UUID as _UUID

    from app.db.session import get_db
    from app.models.notification import Notification, NotificationType
    from app.services.notifications import _MAX_NOTIFICATIONS_RETURNED, list_notifications

    token = _register_and_login_rider(client, email="notif-cap@example.com", phone="9950000214")
    rider_id = _rider_id(client, token)

    db_gen = client.app.dependency_overrides[get_db]()
    db = next(db_gen)
    for i in range(_MAX_NOTIFICATIONS_RETURNED + 10):
        db.add(Notification(user_id=_UUID(rider_id), type=NotificationType.SYSTEM, title=f"Update {i}", body="x"))
    db.commit()

    results = list_notifications(db, _UUID(rider_id))
    assert len(results) == _MAX_NOTIFICATIONS_RETURNED
    db.close()
