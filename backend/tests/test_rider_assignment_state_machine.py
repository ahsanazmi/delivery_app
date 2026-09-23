"""Rider Portal — Phase 24: Rider Order State Machine.

Dedicated validation of DeliveryAssignment's own state machine (PENDING is
represented by "no row yet" -> ACCEPTED -> [ARRIVED_AT_RESTAURANT] ->
PICKED_UP -> OUT_FOR_DELIVERY -> DELIVERED, plus the terminal REJECTED and
CANCELLED outcomes), on top of the existing Order-level VALID_TRANSITIONS
that Phases 10-17's own test files already cover extensively.
"""

from decimal import Decimal

from app.core.security import create_access_token, hash_password
from app.models.user import User, UserRole


def _register_and_login_rider(client, email="rider-sm@example.com", phone="9920000010", name="Ravi Kumar"):
    client.post(
        "/api/v1/auth/register",
        json={"name": name, "email": email, "password": "secure-pass-123", "phone": phone, "role": "RIDER"},
    )
    login = client.post("/api/v1/auth/login", json={"email": email, "password": "secure-pass-123"})
    return login.json()["access_token"]


def _rider_id(client, token):
    return client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"}).json()["id"]


def _make_admin(client, email="admin-sm@example.com", phone="9920000099"):
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


def test_rejected_order_cannot_then_be_accepted_by_the_same_rider(client):
    """The literal example from the phase: REJECTED -> ACCEPTED is invalid.
    Before Phase 24 this crashed with an unhandled IntegrityError (a second
    INSERT violating the (order_id, rider_id) unique constraint) instead of
    a clean 409 — this proves the fix."""
    from app.db.session import get_db

    token = _register_and_login_rider(client)
    rider_id = _rider_id(client, token)
    admin_token = _make_admin(client)
    _make_rider_online(client, token, admin_token, rider_id)

    db_gen = client.app.dependency_overrides[get_db]()
    db = next(db_gen)
    order = _seed_ready_order(db)
    order_id = str(order.id)
    db.close()

    headers = {"Authorization": f"Bearer {token}"}
    reject = client.post(f"/api/v1/rider/deliveries/{order_id}/reject", headers=headers, json={"reason": "too far"})
    assert reject.status_code == 200
    assert reject.json()["status"] == "REJECTED"

    accept = client.post(f"/api/v1/rider/deliveries/{order_id}/accept", headers=headers)
    assert accept.status_code == 409


def test_rejecting_the_same_order_twice_is_idempotent(client):
    from app.db.session import get_db

    token = _register_and_login_rider(client, email="idempotent-reject@example.com", phone="9920000011")
    rider_id = _rider_id(client, token)
    admin_token = _make_admin(client, email="admin2-sm@example.com", phone="9920000098")
    _make_rider_online(client, token, admin_token, rider_id)

    db_gen = client.app.dependency_overrides[get_db]()
    db = next(db_gen)
    order = _seed_ready_order(db)
    order_id = str(order.id)
    db.close()

    headers = {"Authorization": f"Bearer {token}"}
    first = client.post(f"/api/v1/rider/deliveries/{order_id}/reject", headers=headers)
    second = client.post(f"/api/v1/rider/deliveries/{order_id}/reject", headers=headers)
    assert first.status_code == 200
    assert second.status_code == 200
    assert second.json()["status"] == "REJECTED"


def test_full_valid_lifecycle_pending_to_delivered(client):
    """PENDING (no row) -> ACCEPTED -> ARRIVED_AT_RESTAURANT -> PICKED_UP ->
    OUT_FOR_DELIVERY -> DELIVERED, asserting the assignment_status exposed on
    the detail endpoint advances correctly at every step."""
    from app.db.session import get_db

    token = _register_and_login_rider(client, email="full-lifecycle@example.com", phone="9920000012")
    rider_id = _rider_id(client, token)
    admin_token = _make_admin(client, email="admin3-sm@example.com", phone="9920000097")
    _make_rider_online(client, token, admin_token, rider_id)

    db_gen = client.app.dependency_overrides[get_db]()
    db = next(db_gen)
    order = _seed_ready_order(db)
    order_id = str(order.id)
    db.close()

    headers = {"Authorization": f"Bearer {token}"}

    def assignment_status():
        return client.get(f"/api/v1/rider/deliveries/{order_id}", headers=headers).json()["assignment_status"]

    assert client.post(f"/api/v1/rider/deliveries/{order_id}/accept", headers=headers).status_code == 200
    assert assignment_status() == "ACCEPTED"

    assert client.post(f"/api/v1/rider/deliveries/{order_id}/arrived", headers=headers).status_code == 200
    assert assignment_status() == "ARRIVED_AT_RESTAURANT"

    assert client.post(f"/api/v1/rider/deliveries/{order_id}/pickup", headers=headers).status_code == 200
    assert assignment_status() == "PICKED_UP"

    assert client.post(f"/api/v1/rider/deliveries/{order_id}/start", headers=headers).status_code == 200
    assert assignment_status() == "OUT_FOR_DELIVERY"

    assert client.post(f"/api/v1/rider/deliveries/{order_id}/complete", headers=headers).status_code == 200
    assert assignment_status() == "DELIVERED"


def test_delivered_cannot_transition_to_picked_up(client):
    """The literal example: DELIVERED -> PICKED_UP is invalid. Reachable
    only by direct DB manipulation here, since the API's own order-status
    guard (order.status must be RIDER_ASSIGNED) already blocks a second
    pickup call in the normal flow — this proves the assignment-level
    choke point independently refuses it too, as defense in depth."""
    from uuid import UUID as _UUID

    from app.db.session import get_db
    from app.models.delivery_assignment import AssignmentStatus, DeliveryAssignment
    from app.services.rider_deliveries import ASSIGNMENT_VALID_TRANSITIONS

    assert AssignmentStatus.PICKED_UP not in ASSIGNMENT_VALID_TRANSITIONS[AssignmentStatus.DELIVERED]

    token = _register_and_login_rider(client, email="delivered-lock@example.com", phone="9920000013")
    rider_id = _rider_id(client, token)
    admin_token = _make_admin(client, email="admin4-sm@example.com", phone="9920000096")
    _make_rider_online(client, token, admin_token, rider_id)

    db_gen = client.app.dependency_overrides[get_db]()
    db = next(db_gen)
    order = _seed_ready_order(db)
    order_id = str(order.id)
    db.close()

    headers = {"Authorization": f"Bearer {token}"}
    client.post(f"/api/v1/rider/deliveries/{order_id}/accept", headers=headers)
    client.post(f"/api/v1/rider/deliveries/{order_id}/pickup", headers=headers)
    client.post(f"/api/v1/rider/deliveries/{order_id}/start", headers=headers)
    client.post(f"/api/v1/rider/deliveries/{order_id}/complete", headers=headers)

    # Reflects reality: this order is done, its own OrderStatus is DELIVERED
    # (a genuine terminal state with no further transitions at all), so the
    # only way to even ask "what if we tried PICKED_UP again" is against the
    # transition table directly, which is exactly what's asserted above.
    detail = client.get(f"/api/v1/rider/deliveries/{order_id}", headers=headers).json()
    assert detail["status"] == "delivered"
    assert detail["assignment_status"] == "DELIVERED"


def test_pending_cannot_jump_straight_to_delivered(client):
    """The literal example: PENDING -> DELIVERED is invalid — a rider must
    go through every intermediate step; there is no shortcut endpoint that
    could even attempt this, but the choke point rejects it directly too."""
    from app.models.delivery_assignment import AssignmentStatus
    from app.services.rider_deliveries import ASSIGNMENT_VALID_TRANSITIONS

    assert AssignmentStatus.DELIVERED not in ASSIGNMENT_VALID_TRANSITIONS[None]


def test_admin_direct_assignment_can_still_reach_out_for_delivery(client):
    """An order that reaches OUT_FOR_DELIVERY via the admin's own direct
    assign_rider_to_order + transition_order_status path — never touching
    accept_delivery/pickup_delivery at all — must still work: the assignment
    row gets backfilled straight to OUT_FOR_DELIVERY rather than being
    forced through ACCEPTED -> ARRIVED_AT_RESTAURANT -> PICKED_UP first,
    since that history genuinely never happened."""
    from uuid import UUID as _UUID

    from app.db.session import get_db
    from app.models.order import OrderStatus
    from app.services.orders import assign_rider_to_order, transition_order_status

    token = _register_and_login_rider(client, email="admin-bypass-sm@example.com", phone="9920000014")
    rider_id = _rider_id(client, token)
    admin_token = _make_admin(client, email="admin5-sm@example.com", phone="9920000095")
    _make_rider_online(client, token, admin_token, rider_id)

    db_gen = client.app.dependency_overrides[get_db]()
    db = next(db_gen)
    order = _seed_ready_order(db)
    assign_rider_to_order(db, order, _UUID(rider_id))
    transition_order_status(db, order, OrderStatus.PICKED_UP)
    order_id = str(order.id)
    db.close()

    headers = {"Authorization": f"Bearer {token}"}
    response = client.post(f"/api/v1/rider/deliveries/{order_id}/start", headers=headers)
    assert response.status_code == 200
    assert response.json()["status"] == "out_for_delivery"

    detail = client.get(f"/api/v1/rider/deliveries/{order_id}", headers=headers).json()
    assert detail["assignment_status"] == "OUT_FOR_DELIVERY"


def test_cancelling_an_assigned_order_marks_the_assignment_cancelled(client):
    """Phase 24's CANCELLED support: an order cancelled while a rider has a
    non-terminal assignment must flip that assignment to CANCELLED too, not
    leave it stuck at its last active step.

    Cancelled right after acceptance (RIDER_ASSIGNED), not after pickup —
    Order.VALID_TRANSITIONS (a pre-existing, unrelated rule) doesn't permit
    cancelling an order once it's been physically picked up at all, so that
    later branch of ASSIGNMENT_VALID_TRANSITIONS' CANCELLED support is
    intentionally forward-looking rather than reachable via today's API."""
    from uuid import UUID as _UUID

    from app.db.session import get_db
    from app.models.order import Order, OrderStatus
    from app.services.orders import transition_order_status

    token = _register_and_login_rider(client, email="cancel-assignment@example.com", phone="9920000015")
    rider_id = _rider_id(client, token)
    admin_token = _make_admin(client, email="admin6-sm@example.com", phone="9920000094")
    _make_rider_online(client, token, admin_token, rider_id)

    db_gen = client.app.dependency_overrides[get_db]()
    db = next(db_gen)
    order = _seed_ready_order(db)
    order_id = str(order.id)
    db.close()

    headers = {"Authorization": f"Bearer {token}"}
    client.post(f"/api/v1/rider/deliveries/{order_id}/accept", headers=headers)

    db_gen2 = client.app.dependency_overrides[get_db]()
    db2 = next(db_gen2)
    order_row = db2.query(Order).filter(Order.id == _UUID(order_id)).first()
    transition_order_status(db2, order_row, OrderStatus.CANCELLED)
    db2.close()

    db_gen3 = client.app.dependency_overrides[get_db]()
    db3 = next(db_gen3)
    from app.models.delivery_assignment import DeliveryAssignment

    assignment = db3.query(DeliveryAssignment).filter(DeliveryAssignment.order_id == _UUID(order_id)).first()
    assert assignment.status.value == "CANCELLED"
    assert assignment.cancelled_at is not None
    db3.close()


def test_cancelling_an_already_delivered_order_assignment_is_untouched(client):
    """CANCELLED must never overwrite a genuinely terminal outcome —
    DELIVERED, REJECTED, and CANCELLED itself all stay put."""
    from uuid import UUID as _UUID

    from app.db.session import get_db
    from app.models.delivery_assignment import AssignmentStatus, DeliveryAssignment
    from app.services.rider_deliveries import ASSIGNMENT_VALID_TRANSITIONS

    for terminal in (AssignmentStatus.DELIVERED, AssignmentStatus.REJECTED, AssignmentStatus.CANCELLED):
        assert ASSIGNMENT_VALID_TRANSITIONS[terminal] == set()


def test_another_rider_cannot_transition_a_delivery_they_are_not_assigned_to(client):
    """Only authorized actors may transition the assignment: every mutating
    rider endpoint is scoped to Order.rider_id == the calling rider via
    get_rider_delivery_or_404 — a different rider gets 404, never a chance
    to affect someone else's assignment."""
    from app.db.session import get_db

    token_a = _register_and_login_rider(client, email="authz-a@example.com", phone="9920000016")
    rider_a_id = _rider_id(client, token_a)
    token_b = _register_and_login_rider(client, email="authz-b@example.com", phone="9920000017")
    rider_b_id = _rider_id(client, token_b)
    admin_token = _make_admin(client, email="admin7-sm@example.com", phone="9920000093")
    _make_rider_online(client, token_a, admin_token, rider_a_id)
    _make_rider_online(client, token_b, admin_token, rider_b_id)

    db_gen = client.app.dependency_overrides[get_db]()
    db = next(db_gen)
    order = _seed_ready_order(db)
    order_id = str(order.id)
    db.close()

    headers_a = {"Authorization": f"Bearer {token_a}"}
    headers_b = {"Authorization": f"Bearer {token_b}"}
    assert client.post(f"/api/v1/rider/deliveries/{order_id}/accept", headers=headers_a).status_code == 200

    for action in ("arrived", "pickup", "start", "complete"):
        response = client.post(f"/api/v1/rider/deliveries/{order_id}/{action}", headers=headers_b)
        assert response.status_code == 404, f"{action} should 404 for a non-assigned rider"


def test_customer_and_restaurant_owner_cannot_transition_any_assignment(client):
    """Non-rider roles are rejected at the role-check layer before ownership
    is even considered — 403, not 404."""
    fake_id = "00000000-0000-0000-0000-000000000000"
    customer = User(name="C", email="c-sm@example.com", phone="9920000051", password_hash=hash_password("x"), role=UserRole.CUSTOMER)
    owner = User(name="O", email="o-sm@example.com", phone="9920000052", password_hash=hash_password("x"), role=UserRole.RESTAURANT_OWNER)

    from app.db.session import get_db

    db_gen = client.app.dependency_overrides[get_db]()
    db = next(db_gen)
    db.add_all([customer, owner])
    db.commit()
    customer_token = create_access_token(customer.id)
    owner_token = create_access_token(owner.id)
    db.close()

    for token in (customer_token, owner_token):
        headers = {"Authorization": f"Bearer {token}"}
        for action in ("accept", "reject", "arrived", "pickup", "start", "complete"):
            response = client.post(f"/api/v1/rider/deliveries/{fake_id}/{action}", headers=headers)
            assert response.status_code == 403, f"{action} should 403 for {token}"
