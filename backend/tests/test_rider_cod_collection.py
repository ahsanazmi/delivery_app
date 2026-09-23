"""Rider Portal — Phase 16: COD Collection."""

from decimal import Decimal

from app.core.security import create_access_token, hash_password
from app.models.user import User, UserRole


def _register_and_login_rider(client, email="rider-cod@example.com", phone="9950000010", name="Ravi Kumar"):
    client.post(
        "/api/v1/auth/register",
        json={"name": name, "email": email, "password": "secure-pass-123", "phone": phone, "role": "RIDER"},
    )
    login = client.post("/api/v1/auth/login", json={"email": email, "password": "secure-pass-123"})
    return login.json()["access_token"]


def _rider_id(client, token):
    return client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"}).json()["id"]


def _make_admin(client, email="admin-cod@example.com", phone="9950000099"):
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


def _seed_order(db, payment_method="cod"):
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
        latitude=Decimal("12.1"), longitude=Decimal("77.1"),
        minimum_order=Decimal("0.00"), delivery_fee=Decimal("40.00"),
    )
    db.add(restaurant)
    db.commit()
    customer = User(name="Cust", email=f"cust-{suffix}@example.com", phone=f"96{suffix[:8]}", password_hash=hash_password("x"), role=UserRole.CUSTOMER)
    db.add(customer)
    db.commit()
    product = Product(restaurant_id=restaurant.id, name="Item", price=Decimal("175.50"))
    db.add(product)
    db.commit()
    cart = create_cart_for_user(db, customer.id)
    add_item(db, cart, product.id, 1)
    address = create_address(db, customer.id, {
        "label": "Home", "recipient_name": "Cust", "phone": "9999999999",
        "address_line": "1 Road", "city": "Bengaluru", "state": "Karnataka", "postal_code": "560001",
    })
    order = create_order(db, customer, address.id, payment_method=payment_method)
    return order


def _advance_to_out_for_delivery(client, token, order_id):
    from uuid import UUID as _UUID

    from app.db.session import get_db
    from app.models.order import OrderStatus
    from app.services.orders import transition_order_status

    db_gen = client.app.dependency_overrides[get_db]()
    db = next(db_gen)
    from app.models.order import Order

    order_row = db.query(Order).filter(Order.id == _UUID(order_id)).first()
    transition_order_status(db, order_row, OrderStatus.CONFIRMED)
    transition_order_status(db, order_row, OrderStatus.PREPARING)
    transition_order_status(db, order_row, OrderStatus.READY_FOR_PICKUP)
    db.close()

    headers = {"Authorization": f"Bearer {token}"}
    accept = client.post(f"/api/v1/rider/deliveries/{order_id}/accept", headers=headers)
    assert accept.status_code == 200, accept.json()
    pickup = client.post(f"/api/v1/rider/deliveries/{order_id}/pickup", headers=headers)
    assert pickup.status_code == 200, pickup.json()
    start = client.post(f"/api/v1/rider/deliveries/{order_id}/start", headers=headers)
    assert start.status_code == 200, start.json()


def test_cod_collect_records_amount_status_timestamp_rider_and_order(client):
    from app.db.session import get_db

    token = _register_and_login_rider(client)
    rider_id = _rider_id(client, token)
    admin_token = _make_admin(client)
    _make_rider_online(client, token, admin_token, rider_id)

    db_gen = client.app.dependency_overrides[get_db]()
    db = next(db_gen)
    order = _seed_order(db)
    order_id = str(order.id)
    expected_total = order.total
    db.close()

    _advance_to_out_for_delivery(client, token, order_id)

    response = client.post(f"/api/v1/rider/deliveries/{order_id}/cod-collect", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200, response.json()
    body = response.json()

    assert body["order_id"] == order_id
    assert body["payment_id"]
    assert Decimal(body["amount"]) == expected_total
    assert body["payment_status"] == "paid"
    assert body["collected_by_rider_id"] == rider_id
    assert body["collected_at"] is not None


def test_cod_collect_marks_order_paid(client):
    from app.db.session import get_db

    token = _register_and_login_rider(client, email="cod-marks-paid@example.com", phone="9950000011")
    rider_id = _rider_id(client, token)
    admin_token = _make_admin(client, email="admin2-cod@example.com", phone="9950000098")
    _make_rider_online(client, token, admin_token, rider_id)

    db_gen = client.app.dependency_overrides[get_db]()
    db = next(db_gen)
    order = _seed_order(db)
    order_id = str(order.id)
    db.close()

    _advance_to_out_for_delivery(client, token, order_id)
    client.post(f"/api/v1/rider/deliveries/{order_id}/cod-collect", headers={"Authorization": f"Bearer {token}"})

    detail = client.get(f"/api/v1/rider/deliveries/{order_id}", headers={"Authorization": f"Bearer {token}"}).json()
    assert detail["is_paid"] is True
    assert detail["cod_amount"] is None  # no longer outstanding once collected


def test_collecting_cod_twice_by_the_same_rider_is_idempotent(client):
    """Phase 28: a second cod-collect call by the SAME rider who already
    collected is a lost-response retry, not a double-collection attempt —
    it returns the original collection record (same amount, same
    timestamp) as success rather than a 409."""
    from app.db.session import get_db

    token = _register_and_login_rider(client, email="cod-twice@example.com", phone="9950000012")
    rider_id = _rider_id(client, token)
    admin_token = _make_admin(client, email="admin3-cod@example.com", phone="9950000097")
    _make_rider_online(client, token, admin_token, rider_id)

    db_gen = client.app.dependency_overrides[get_db]()
    db = next(db_gen)
    order = _seed_order(db)
    order_id = str(order.id)
    db.close()

    _advance_to_out_for_delivery(client, token, order_id)
    headers = {"Authorization": f"Bearer {token}"}
    first = client.post(f"/api/v1/rider/deliveries/{order_id}/cod-collect", headers=headers)
    assert first.status_code == 200
    second = client.post(f"/api/v1/rider/deliveries/{order_id}/cod-collect", headers=headers)
    assert second.status_code == 200
    assert second.json()["payment_id"] == first.json()["payment_id"]
    assert second.json()["amount"] == first.json()["amount"]
    # Not compared for exact string equality — SQLite (this fast test
    # suite's engine) doesn't round-trip the UTC "Z" suffix the way Postgres
    # does, so the two representations can differ in format even though
    # they're the same instant. The identical payment_id above is what
    # actually proves this was a returned record, not a freshly re-collected one.
    assert second.json()["collected_at"] is not None


def test_collecting_cod_already_settled_by_someone_else_is_still_a_conflict(client):
    """If is_paid became true for a reason OTHER than this rider having
    collected it (e.g. the legacy admin fallback path, with no rider
    attribution at all), that's a genuine conflict, not a safe retry."""
    from uuid import UUID as _UUID

    from app.db.session import get_db
    from app.models.order import OrderStatus
    from app.services.orders import transition_order_status

    token = _register_and_login_rider(client, email="cod-settled-elsewhere@example.com", phone="9950000018")
    rider_id = _rider_id(client, token)
    admin_token = _make_admin(client, email="admin8-cod@example.com", phone="9950000091")
    _make_rider_online(client, token, admin_token, rider_id)

    db_gen = client.app.dependency_overrides[get_db]()
    db = next(db_gen)
    order = _seed_order(db)
    order_id = str(order.id)
    db.close()

    _advance_to_out_for_delivery(client, token, order_id)

    # Simulate the order being settled by some other means (not this
    # rider's own cod-collect call) — e.g. an admin override.
    db_gen2 = client.app.dependency_overrides[get_db]()
    db2 = next(db_gen2)
    from app.models.order import Order

    order_row = db2.query(Order).filter(Order.id == _UUID(order_id)).first()
    order_row.is_paid = True
    order_row.payment_status = "paid"
    db2.commit()
    db2.close()

    response = client.post(
        f"/api/v1/rider/deliveries/{order_id}/cod-collect", headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 409


def test_cannot_collect_cod_before_out_for_delivery(client):
    from app.db.session import get_db
    from app.models.order import Order, OrderStatus
    from app.services.orders import transition_order_status

    token = _register_and_login_rider(client, email="cod-too-early@example.com", phone="9950000013")
    rider_id = _rider_id(client, token)
    admin_token = _make_admin(client, email="admin4-cod@example.com", phone="9950000096")
    _make_rider_online(client, token, admin_token, rider_id)

    db_gen = client.app.dependency_overrides[get_db]()
    db = next(db_gen)
    order = _seed_order(db)
    order_id = str(order.id)
    order_row = db.get(Order, order.id)
    transition_order_status(db, order_row, OrderStatus.CONFIRMED)
    transition_order_status(db, order_row, OrderStatus.PREPARING)
    transition_order_status(db, order_row, OrderStatus.READY_FOR_PICKUP)
    db.close()

    headers = {"Authorization": f"Bearer {token}"}
    client.post(f"/api/v1/rider/deliveries/{order_id}/accept", headers=headers)
    # Not picked up / started yet.
    response = client.post(f"/api/v1/rider/deliveries/{order_id}/cod-collect", headers=headers)
    assert response.status_code == 409


def test_cannot_collect_cod_for_a_non_cod_order(client):
    from app.db.session import get_db

    token = _register_and_login_rider(client, email="cod-not-cod@example.com", phone="9950000014")
    rider_id = _rider_id(client, token)
    admin_token = _make_admin(client, email="admin5-cod@example.com", phone="9950000095")
    _make_rider_online(client, token, admin_token, rider_id)

    db_gen = client.app.dependency_overrides[get_db]()
    db = next(db_gen)
    order = _seed_order(db, payment_method="online")
    order_id = str(order.id)
    db.close()

    _advance_to_out_for_delivery(client, token, order_id)
    response = client.post(f"/api/v1/rider/deliveries/{order_id}/cod-collect", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 400


def test_amount_field_in_request_body_is_ignored(client):
    """A rider must not be able to change the collected amount. Even if a
    body is sent with an 'amount' field, the endpoint takes no body at all —
    it's silently ignored by FastAPI, and the recorded amount is always
    order.total."""
    from app.db.session import get_db

    token = _register_and_login_rider(client, email="cod-tamper@example.com", phone="9950000015")
    rider_id = _rider_id(client, token)
    admin_token = _make_admin(client, email="admin6-cod@example.com", phone="9950000094")
    _make_rider_online(client, token, admin_token, rider_id)

    db_gen = client.app.dependency_overrides[get_db]()
    db = next(db_gen)
    order = _seed_order(db)
    order_id = str(order.id)
    expected_total = order.total
    db.close()

    _advance_to_out_for_delivery(client, token, order_id)
    response = client.post(
        f"/api/v1/rider/deliveries/{order_id}/cod-collect",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        json={"amount": "1.00", "payment_status": "paid"},
    )
    assert response.status_code == 200
    assert Decimal(response.json()["amount"]) == expected_total


def test_another_riders_order_cannot_have_cod_collected(client):
    from app.db.session import get_db

    token_a = _register_and_login_rider(client, email="cod-a@example.com", phone="9950000016")
    rider_a_id = _rider_id(client, token_a)
    token_b = _register_and_login_rider(client, email="cod-b@example.com", phone="9950000017")
    rider_b_id = _rider_id(client, token_b)
    admin_token = _make_admin(client, email="admin7-cod@example.com", phone="9950000093")
    _make_rider_online(client, token_a, admin_token, rider_a_id)
    _make_rider_online(client, token_b, admin_token, rider_b_id)

    db_gen = client.app.dependency_overrides[get_db]()
    db = next(db_gen)
    order = _seed_order(db)
    order_id = str(order.id)
    db.close()

    _advance_to_out_for_delivery(client, token_a, order_id)
    response = client.post(
        f"/api/v1/rider/deliveries/{order_id}/cod-collect", headers={"Authorization": f"Bearer {token_b}"}
    )
    assert response.status_code == 404


def test_customer_and_restaurant_owner_cannot_collect_cod(client):
    from app.db.session import get_db

    db_gen = client.app.dependency_overrides[get_db]()
    db = next(db_gen)
    customer = User(name="C", email="c-cod@example.com", phone="9950000051", password_hash=hash_password("x"), role=UserRole.CUSTOMER)
    owner = User(name="O", email="o-cod@example.com", phone="9950000052", password_hash=hash_password("x"), role=UserRole.RESTAURANT_OWNER)
    db.add_all([customer, owner])
    db.commit()
    customer_token = create_access_token(customer.id)
    owner_token = create_access_token(owner.id)
    db.close()

    fake_id = "00000000-0000-0000-0000-000000000000"
    assert client.post(f"/api/v1/rider/deliveries/{fake_id}/cod-collect", headers={"Authorization": f"Bearer {customer_token}"}).status_code == 403
    assert client.post(f"/api/v1/rider/deliveries/{fake_id}/cod-collect", headers={"Authorization": f"Bearer {owner_token}"}).status_code == 403


def test_unauthenticated_request_is_rejected(client):
    fake_id = "00000000-0000-0000-0000-000000000000"
    assert client.post(f"/api/v1/rider/deliveries/{fake_id}/cod-collect").status_code == 401
