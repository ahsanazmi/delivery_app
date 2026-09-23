"""Rider Portal — Phase 25: Rider Security Audit.

A dedicated, cross-cutting pass over every rider-facing surface built in
Phases 1-24: ownership isolation between riders, delivery/assignment
ownership, and a checklist of specific forbidden actions. Each individual
piece has already been covered incidentally by its own phase's test file —
this file exists to assert them all together, explicitly, as security
properties rather than incidental feature behavior, and to close two real
gaps found while writing it:

1. accept_delivery() could crash (IntegrityError) rather than cleanly
   refuse re-accepting a previously-rejected order — fixed in Phase 24.
2. mark_arrived_at_restaurant/pickup_delivery/start_delivery/
   collect_cod_payment/complete_delivery never checked rider approval
   status at all, meaning a rider suspended *after* accepting a delivery
   could freely continue performing it. Fixed in this phase
   (assert_rider_approved() added to all five), and the legacy dual-hop
   PATCH /rider/orders/{id}/pickup|deliver endpoints — dead code with no
   frontend caller, which bypassed COD-collection, earnings-crediting, and
   assignment-state-sync entirely — were removed rather than patched.
"""

from decimal import Decimal

from app.core.security import create_access_token, hash_password
from app.models.user import User, UserRole


def _register_and_login_rider(client, email="rider-audit@example.com", phone="9930000010", name="Ravi Kumar"):
    client.post(
        "/api/v1/auth/register",
        json={"name": name, "email": email, "password": "secure-pass-123", "phone": phone, "role": "RIDER"},
    )
    login = client.post("/api/v1/auth/login", json={"email": email, "password": "secure-pass-123"})
    return login.json()["access_token"]


def _rider_id(client, token):
    return client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"}).json()["id"]


def _make_admin(client, email="admin-audit@example.com", phone="9930000099"):
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


def _seed_ready_order(db, payment_method="online", delivery_fee=Decimal("40.00")):
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
    order = create_order(db, customer, address.id, payment_method=payment_method)
    transition_order_status(db, order, OrderStatus.CONFIRMED)
    transition_order_status(db, order, OrderStatus.PREPARING)
    transition_order_status(db, order, OrderStatus.READY_FOR_PICKUP)
    return order


def _two_riders(client):
    from app.db.session import get_db

    token_a = _register_and_login_rider(client, email="audit-a@example.com", phone="9930000011")
    rider_a_id = _rider_id(client, token_a)
    token_b = _register_and_login_rider(client, email="audit-b@example.com", phone="9930000012")
    rider_b_id = _rider_id(client, token_b)
    admin_token = _make_admin(client, email="admin2-audit@example.com", phone="9930000098")
    _make_rider_online(client, token_a, admin_token, rider_a_id)
    _make_rider_online(client, token_b, admin_token, rider_b_id)

    db_gen = client.app.dependency_overrides[get_db]()
    db = next(db_gen)
    order = _seed_ready_order(db)
    order_id = str(order.id)
    db.close()

    return token_a, rider_a_id, token_b, rider_b_id, order_id, admin_token


# --------------------------- Rider ownership isolation ---------------------------


def test_rider_a_cannot_see_rider_b_profile_fields(client):
    """No endpoint takes a rider_id parameter for profile — /rider/profile
    always resolves to whoever the bearer token belongs to."""
    token_a, rider_a_id, token_b, rider_b_id, _order_id, _admin = _two_riders(client)

    profile_a = client.get("/api/v1/rider/profile", headers={"Authorization": f"Bearer {token_a}"}).json()
    profile_b = client.get("/api/v1/rider/profile", headers={"Authorization": f"Bearer {token_b}"}).json()
    assert profile_a["id"] == rider_a_id
    assert profile_b["id"] == rider_b_id
    assert profile_a["id"] != profile_b["id"]


def test_rider_a_cannot_see_rider_b_earnings(client):
    token_a, rider_a_id, token_b, rider_b_id, order_id, _admin = _two_riders(client)
    headers_a = {"Authorization": f"Bearer {token_a}"}
    headers_b = {"Authorization": f"Bearer {token_b}"}

    client.post(f"/api/v1/rider/deliveries/{order_id}/accept", headers=headers_a)
    client.post(f"/api/v1/rider/deliveries/{order_id}/pickup", headers=headers_a)
    client.post(f"/api/v1/rider/deliveries/{order_id}/start", headers=headers_a)
    client.post(f"/api/v1/rider/deliveries/{order_id}/complete", headers=headers_a)

    earnings_a = client.get("/api/v1/rider/earnings", headers=headers_a).json()
    earnings_b = client.get("/api/v1/rider/earnings", headers=headers_b).json()
    assert len(earnings_a) == 1
    assert earnings_b == []


def test_rider_a_cannot_see_rider_b_wallet(client):
    token_a, rider_a_id, token_b, rider_b_id, order_id, _admin = _two_riders(client)
    headers_a = {"Authorization": f"Bearer {token_a}"}
    headers_b = {"Authorization": f"Bearer {token_b}"}

    client.post(f"/api/v1/rider/deliveries/{order_id}/accept", headers=headers_a)
    client.post(f"/api/v1/rider/deliveries/{order_id}/pickup", headers=headers_a)
    client.post(f"/api/v1/rider/deliveries/{order_id}/start", headers=headers_a)
    client.post(f"/api/v1/rider/deliveries/{order_id}/complete", headers=headers_a)

    wallet_a = client.get("/api/v1/rider/wallet", headers=headers_a).json()
    wallet_b = client.get("/api/v1/rider/wallet", headers=headers_b).json()
    assert Decimal(wallet_a["total_earnings"]) == Decimal("40.00")
    assert Decimal(wallet_b["total_earnings"]) == Decimal("0.00")


def test_rider_a_cannot_read_update_or_delete_rider_bs_document(client):
    token_a, _rider_a_id, token_b, rider_b_id, _order_id, _admin = _two_riders(client)
    headers_b = {"Authorization": f"Bearer {token_b}"}
    headers_a = {"Authorization": f"Bearer {token_a}"}

    created = client.post(
        "/api/v1/rider/documents", headers=headers_b,
        json={"document_type": "BANK_DOCUMENT", "document_url": "https://example.com/bank.jpg"},
    ).json()
    document_id = created["id"]

    # Rider A's own list must not include Rider B's document.
    docs_a = client.get("/api/v1/rider/documents", headers=headers_a).json()
    assert all(d["id"] != document_id for d in docs_a)

    patch = client.patch(
        f"/api/v1/rider/documents/{document_id}", headers=headers_a, json={"document_url": "https://evil.example.com/x.jpg"}
    )
    assert patch.status_code == 404

    delete = client.delete(f"/api/v1/rider/documents/{document_id}", headers=headers_a)
    assert delete.status_code == 404

    # Rider B's document is untouched.
    still_there = client.get("/api/v1/rider/documents", headers=headers_b).json()
    assert any(d["id"] == document_id and d["document_url"] == "https://example.com/bank.jpg" for d in still_there)


def test_rider_a_cannot_affect_rider_bs_location(client):
    """There's no endpoint that takes a target rider_id for location at
    all — PATCH /rider/location always writes to whichever rider the
    bearer token belongs to, so there is no way for Rider A's request to
    even name Rider B as a target."""
    token_a, _rider_a_id, token_b, _rider_b_id, _order_id, _admin = _two_riders(client)

    client.patch(
        "/api/v1/rider/location", headers={"Authorization": f"Bearer {token_a}"},
        json={"latitude": "1.0000", "longitude": "1.0000"},
    )
    b_location = client.patch(
        "/api/v1/rider/location", headers={"Authorization": f"Bearer {token_b}"},
        json={"latitude": "2.0000", "longitude": "2.0000"},
    ).json()
    assert float(b_location["latitude"]) == 2.0


def test_rider_a_cannot_see_rider_bs_assignment_in_history(client):
    token_a, _rider_a_id, token_b, _rider_b_id, order_id, _admin = _two_riders(client)
    headers_a = {"Authorization": f"Bearer {token_a}"}
    headers_b = {"Authorization": f"Bearer {token_b}"}

    client.post(f"/api/v1/rider/deliveries/{order_id}/accept", headers=headers_a)
    client.post(f"/api/v1/rider/deliveries/{order_id}/pickup", headers=headers_a)
    client.post(f"/api/v1/rider/deliveries/{order_id}/start", headers=headers_a)
    client.post(f"/api/v1/rider/deliveries/{order_id}/complete", headers=headers_a)

    history_b = client.get("/api/v1/rider/history", headers=headers_b).json()
    assert history_b == []
    assert client.get(f"/api/v1/rider/history/{order_id}", headers=headers_b).status_code == 404


# --------------------------- Delivery/assignment ownership ---------------------------


def test_rider_a_cannot_manipulate_rider_bs_assignment_by_guessing_the_order_id(client):
    """Every mutating action on a delivery is scoped to Order.rider_id ==
    the calling rider — knowing (or guessing) another rider's order_id
    grants no access at all, only a 404 identical to a nonexistent order."""
    token_a, _rider_a_id, token_b, _rider_b_id, order_id, _admin = _two_riders(client)
    headers_a = {"Authorization": f"Bearer {token_a}"}
    headers_b = {"Authorization": f"Bearer {token_b}"}

    assert client.post(f"/api/v1/rider/deliveries/{order_id}/accept", headers=headers_a).status_code == 200

    for action in ("arrived", "pickup", "start", "complete", "cod-collect"):
        response = client.post(f"/api/v1/rider/deliveries/{order_id}/{action}", headers=headers_b)
        assert response.status_code == 404, f"{action} leaked access to another rider's assignment"

    assert client.get(f"/api/v1/rider/deliveries/{order_id}", headers=headers_b).status_code == 404


def test_rider_can_only_manage_their_own_assignments_end_to_end(client):
    """Positive control for the above: the SAME sequence of calls succeeds
    end-to-end for the rider who actually owns the assignment."""
    token_a, _rider_a_id, _token_b, _rider_b_id, order_id, _admin = _two_riders(client)
    headers_a = {"Authorization": f"Bearer {token_a}"}

    assert client.post(f"/api/v1/rider/deliveries/{order_id}/accept", headers=headers_a).status_code == 200
    assert client.post(f"/api/v1/rider/deliveries/{order_id}/arrived", headers=headers_a).status_code == 200
    assert client.post(f"/api/v1/rider/deliveries/{order_id}/pickup", headers=headers_a).status_code == 200
    assert client.post(f"/api/v1/rider/deliveries/{order_id}/start", headers=headers_a).status_code == 200
    assert client.post(f"/api/v1/rider/deliveries/{order_id}/complete", headers=headers_a).status_code == 200


# --------------------------- Forbidden actions ---------------------------


def test_cannot_change_order_price_restaurant_or_customer_via_any_rider_endpoint(client):
    """No rider-facing request body anywhere accepts total/subtotal/
    delivery_fee/restaurant_id/customer_name-shaped fields that get
    applied — every response is server-computed from the DB, and every
    rider POST body that exists (accept/reject/pickup/start/complete/
    cod-collect) either takes no body or only a free-text reason."""
    token_a, _rider_a_id, _token_b, _rider_b_id, order_id, _admin = _two_riders(client)
    headers = {"Authorization": f"Bearer {token_a}"}

    original_total = client.get(f"/api/v1/rider/deliveries/available", headers=headers).json()
    matching = [d for d in original_total if d["order_id"] == order_id]
    assert matching
    original_earning = matching[0]["estimated_earning"]

    tampering_payload = {
        "total": "1.00",
        "subtotal": "1.00",
        "delivery_fee": "9999.00",
        "restaurant_id": "00000000-0000-0000-0000-000000000000",
        "restaurant_name": "Hacked Restaurant",
        "customer_name": "Hacked Customer",
        "customer_id": "00000000-0000-0000-0000-000000000000",
    }
    accept = client.post(f"/api/v1/rider/deliveries/{order_id}/accept", headers=headers, json=tampering_payload)
    assert accept.status_code == 200
    detail = client.get(f"/api/v1/rider/deliveries/{order_id}", headers=headers).json()
    assert detail["restaurant_name"] != "Hacked Restaurant"
    assert detail["customer_name"] != "Hacked Customer"
    assert str(detail["delivery_fee"]) == str(original_earning)


def test_cannot_change_payment_amount_via_cod_collect(client):
    """Restates and re-verifies Phase 16's guarantee under this audit: the
    cod-collect endpoint takes no meaningful body — a spoofed amount is
    silently ignored, and the recorded figure is always order.total."""
    from app.db.session import get_db

    token = _register_and_login_rider(client, email="audit-cod@example.com", phone="9930000013")
    rider_id = _rider_id(client, token)
    admin_token = _make_admin(client, email="admin3-audit@example.com", phone="9930000097")
    _make_rider_online(client, token, admin_token, rider_id)

    db_gen = client.app.dependency_overrides[get_db]()
    db = next(db_gen)
    order = _seed_ready_order(db, payment_method="cod", delivery_fee=Decimal("50.00"))
    order_id = str(order.id)
    expected_total = order.total
    db.close()

    headers = {"Authorization": f"Bearer {token}"}
    client.post(f"/api/v1/rider/deliveries/{order_id}/accept", headers=headers)
    client.post(f"/api/v1/rider/deliveries/{order_id}/pickup", headers=headers)
    client.post(f"/api/v1/rider/deliveries/{order_id}/start", headers=headers)

    collect = client.post(
        f"/api/v1/rider/deliveries/{order_id}/cod-collect", headers=headers, json={"amount": "0.01"}
    )
    assert collect.status_code == 200
    assert Decimal(collect.json()["amount"]) == expected_total


def test_cannot_change_earning_amount_no_write_endpoint_exists(client):
    """The entire /rider/earnings surface is read-only — GET list and GET
    summary, nothing else. Verified by enumerating the actual registered
    routes rather than guessing at a URL, so this can't pass by accident."""
    from app.api.v1.rider import earnings as earnings_module

    methods_by_path: dict[str, set[str]] = {}
    for route in earnings_module.router.routes:
        methods_by_path.setdefault(route.path, set()).update(route.methods - {"HEAD", "OPTIONS"})
    assert methods_by_path == {"/earnings": {"GET"}, "/earnings/summary": {"GET"}}


def test_cannot_assign_self_to_an_order_that_is_not_ready_for_pickup(client):
    from app.db.session import get_db

    token = _register_and_login_rider(client, email="audit-notready@example.com", phone="9930000014")
    rider_id = _rider_id(client, token)
    admin_token = _make_admin(client, email="admin4-audit@example.com", phone="9930000096")
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
    order = create_order(db, customer, address.id)  # still PLACED, nowhere near READY_FOR_PICKUP
    order_id = str(order.id)
    db.close()

    response = client.post(f"/api/v1/rider/deliveries/{order_id}/accept", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 404


def test_cannot_assign_self_to_an_order_already_taken_by_another_rider(client):
    token_a, _rider_a_id, token_b, _rider_b_id, order_id, _admin = _two_riders(client)
    headers_a = {"Authorization": f"Bearer {token_a}"}
    headers_b = {"Authorization": f"Bearer {token_b}"}

    assert client.post(f"/api/v1/rider/deliveries/{order_id}/accept", headers=headers_a).status_code == 200
    second_accept = client.post(f"/api/v1/rider/deliveries/{order_id}/accept", headers=headers_b)
    assert second_accept.status_code in (404, 409)


def test_cannot_mark_own_order_delivered_before_out_for_delivery(client):
    token_a, _rider_a_id, _token_b, _rider_b_id, order_id, _admin = _two_riders(client)
    headers_a = {"Authorization": f"Bearer {token_a}"}

    client.post(f"/api/v1/rider/deliveries/{order_id}/accept", headers=headers_a)
    too_early = client.post(f"/api/v1/rider/deliveries/{order_id}/complete", headers=headers_a)
    assert too_early.status_code == 409


def test_cannot_mark_an_unassigned_order_delivered(client):
    from app.db.session import get_db

    token = _register_and_login_rider(client, email="audit-unassigned@example.com", phone="9930000015")
    rider_id = _rider_id(client, token)
    admin_token = _make_admin(client, email="admin5-audit@example.com", phone="9930000095")
    _make_rider_online(client, token, admin_token, rider_id)

    db_gen = client.app.dependency_overrides[get_db]()
    db = next(db_gen)
    order = _seed_ready_order(db)
    order_id = str(order.id)  # never accepted by anyone
    db.close()

    response = client.post(
        f"/api/v1/rider/deliveries/{order_id}/complete", headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 404


def test_cannot_change_another_riders_online_status(client):
    """PATCH /rider/status takes no rider_id — it can only ever act on the
    caller's own DeliveryPartner row. Approval/suspension status (the other
    kind of rider "status") is admin-only and rejects a rider token."""
    token_a, rider_a_id, token_b, rider_b_id, _order_id, admin_token = _two_riders(client)

    # Rider A going online/offline only ever affects Rider A.
    client.patch("/api/v1/rider/status", headers={"Authorization": f"Bearer {token_a}"}, json={"is_online": False})
    status_b = client.get("/api/v1/rider/status", headers={"Authorization": f"Bearer {token_b}"}).json()
    assert status_b["is_online"] is True

    # The admin verification endpoint (the other rider "status") flatly
    # rejects a rider's own token regardless of whose id is in the path.
    forbidden = client.patch(
        f"/api/v1/admin/riders/{rider_b_id}/verification",
        headers={"Authorization": f"Bearer {token_a}"},
        json={"approval_status": "SUSPENDED"},
    )
    assert forbidden.status_code == 403


def test_rider_cannot_access_admin_apis(client):
    token_a, rider_a_id, _token_b, rider_b_id, order_id, _admin = _two_riders(client)
    headers = {"Authorization": f"Bearer {token_a}"}

    assert client.get("/api/v1/admin/dashboard", headers=headers).status_code == 403
    assert client.get("/api/v1/admin/customers", headers=headers).status_code == 403
    assert client.get("/api/v1/admin/restaurants", headers=headers).status_code == 403
    assert client.get("/api/v1/admin/orders", headers=headers).status_code == 403
    assert client.get("/api/v1/admin/riders", headers=headers).status_code == 403
    assert client.patch(
        f"/api/v1/admin/riders/{rider_b_id}/verification", headers=headers, json={"approval_status": "APPROVED"}
    ).status_code == 403
    assert client.patch(
        f"/api/v1/admin/orders/{order_id}/assign-rider", headers=headers, params={"rider_id": rider_a_id}
    ).status_code == 403
    # PATCH .../status was removed in Admin Portal Phase 11 ("do NOT allow
    # arbitrary direct status modification"); its replacement — the
    # explicit, audited cancel action — is checked here instead, so this
    # audit still proves a rider token can't reach admin order mutation.
    assert client.post(
        f"/api/v1/admin/orders/{order_id}/cancel", headers=headers, json={"reason": "x"}
    ).status_code == 403
    assert client.post(
        "/api/v1/admin/notifications/broadcast", headers=headers, json={"title": "x", "body": "y"}
    ).status_code == 403


def test_rider_cannot_access_restaurant_owner_apis(client):
    token_a, _rider_a_id, _token_b, _rider_b_id, order_id, _admin = _two_riders(client)
    headers = {"Authorization": f"Bearer {token_a}"}

    assert client.get("/api/v1/restaurant/dashboard", headers=headers).status_code == 403
    assert client.get("/api/v1/restaurant/orders", headers=headers).status_code == 403
    assert client.get("/api/v1/restaurant/products", headers=headers).status_code == 403
    assert client.get("/api/v1/restaurant/categories", headers=headers).status_code == 403
    assert client.get("/api/v1/restaurant/profile", headers=headers).status_code == 403
    assert client.get("/api/v1/restaurant/status", headers=headers).status_code == 403
    assert client.post(
        f"/api/v1/restaurant/orders/{order_id}/accept", headers=headers
    ).status_code == 403
    assert client.post(
        "/api/v1/restaurant/products", headers=headers,
        json={"name": "x", "price": "1.00", "category_id": "00000000-0000-0000-0000-000000000000"},
    ).status_code == 403


def test_suspended_rider_cannot_continue_an_already_accepted_delivery(client):
    """The gap this phase found and fixed: a rider suspended mid-delivery
    must lose the ability to progress it, not just the ability to accept
    new ones."""
    from app.db.session import get_db

    token = _register_and_login_rider(client, email="audit-suspend-midway@example.com", phone="9930000016")
    rider_id = _rider_id(client, token)
    admin_token = _make_admin(client, email="admin6-audit@example.com", phone="9930000094")
    _make_rider_online(client, token, admin_token, rider_id)

    db_gen = client.app.dependency_overrides[get_db]()
    db = next(db_gen)
    order = _seed_ready_order(db)
    order_id = str(order.id)
    db.close()

    headers = {"Authorization": f"Bearer {token}"}
    admin_headers = {"Authorization": f"Bearer {admin_token}"}
    assert client.post(f"/api/v1/rider/deliveries/{order_id}/accept", headers=headers).status_code == 200

    suspend = client.patch(
        f"/api/v1/admin/riders/{rider_id}/verification", headers=admin_headers, json={"approval_status": "SUSPENDED"}
    )
    assert suspend.status_code == 200

    for action in ("arrived", "pickup", "start", "complete"):
        response = client.post(f"/api/v1/rider/deliveries/{order_id}/{action}", headers=headers)
        assert response.status_code == 403, f"{action} should be blocked for a suspended rider"


def test_legacy_dual_hop_endpoints_no_longer_exist(client):
    """The removed endpoints are gone entirely, not just newly forbidden —
    confirms the fix was a real removal, not a route left registered but
    guarded (which would have kept the same dead-code risk alive)."""
    fake_id = "00000000-0000-0000-0000-000000000000"
    token = _register_and_login_rider(client, email="audit-legacy-gone@example.com", phone="9930000017")
    headers = {"Authorization": f"Bearer {token}"}

    assert client.patch(f"/api/v1/rider/orders/{fake_id}/pickup", headers=headers).status_code in (404, 405)
    assert client.patch(f"/api/v1/rider/orders/{fake_id}/deliver", headers=headers).status_code in (404, 405)


def test_unauthenticated_requests_rejected_across_the_whole_rider_surface(client):
    fake_id = "00000000-0000-0000-0000-000000000000"
    for path, method in [
        ("/api/v1/rider/profile", "get"),
        ("/api/v1/rider/earnings", "get"),
        ("/api/v1/rider/earnings/summary", "get"),
        ("/api/v1/rider/wallet", "get"),
        ("/api/v1/rider/wallet/settlements", "get"),
        ("/api/v1/rider/documents", "get"),
        ("/api/v1/rider/history", "get"),
        (f"/api/v1/rider/history/{fake_id}", "get"),
        (f"/api/v1/rider/deliveries/{fake_id}", "get"),
        (f"/api/v1/rider/deliveries/{fake_id}/accept", "post"),
        (f"/api/v1/rider/deliveries/{fake_id}/complete", "post"),
        ("/api/v1/rider/location", "patch"),
        ("/api/v1/rider/status", "get"),
    ]:
        response = getattr(client, method)(path)
        assert response.status_code == 401, f"{method.upper()} {path} should require authentication"
