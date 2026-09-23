"""Rider Portal — Phase 18: Delivery History."""

from decimal import Decimal

from app.core.security import create_access_token, hash_password
from app.models.user import User, UserRole


def _register_and_login_rider(client, email="rider-history@example.com", phone="9970000010", name="Ravi Kumar"):
    client.post(
        "/api/v1/auth/register",
        json={"name": name, "email": email, "password": "secure-pass-123", "phone": phone, "role": "RIDER"},
    )
    login = client.post("/api/v1/auth/login", json={"email": email, "password": "secure-pass-123"})
    return login.json()["access_token"]


def _rider_id(client, token):
    return client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"}).json()["id"]


def _make_admin(client, email="admin-history@example.com", phone="9970000099"):
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
    product = Product(restaurant_id=restaurant.id, name="Item", price=Decimal("120.00"))
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


def _complete_full_delivery(client, token, order_id):
    from uuid import UUID as _UUID

    from app.db.session import get_db
    from app.models.order import Order, OrderStatus
    from app.services.orders import transition_order_status

    db_gen = client.app.dependency_overrides[get_db]()
    db = next(db_gen)
    order_row = db.query(Order).filter(Order.id == _UUID(order_id)).first()
    transition_order_status(db, order_row, OrderStatus.CONFIRMED)
    transition_order_status(db, order_row, OrderStatus.PREPARING)
    transition_order_status(db, order_row, OrderStatus.READY_FOR_PICKUP)
    db.close()

    headers = {"Authorization": f"Bearer {token}"}
    assert client.post(f"/api/v1/rider/deliveries/{order_id}/accept", headers=headers).status_code == 200
    assert client.post(f"/api/v1/rider/deliveries/{order_id}/pickup", headers=headers).status_code == 200
    assert client.post(f"/api/v1/rider/deliveries/{order_id}/start", headers=headers).status_code == 200
    complete = client.post(f"/api/v1/rider/deliveries/{order_id}/complete", headers=headers)
    assert complete.status_code == 200, complete.json()


def _cancel_after_assignment(client, token, order_id):
    from uuid import UUID as _UUID

    from app.db.session import get_db
    from app.models.order import Order, OrderStatus
    from app.services.orders import transition_order_status

    db_gen = client.app.dependency_overrides[get_db]()
    db = next(db_gen)
    order_row = db.query(Order).filter(Order.id == _UUID(order_id)).first()
    transition_order_status(db, order_row, OrderStatus.CONFIRMED)
    transition_order_status(db, order_row, OrderStatus.PREPARING)
    transition_order_status(db, order_row, OrderStatus.READY_FOR_PICKUP)
    db.close()

    headers = {"Authorization": f"Bearer {token}"}
    assert client.post(f"/api/v1/rider/deliveries/{order_id}/accept", headers=headers).status_code == 200

    db_gen2 = client.app.dependency_overrides[get_db]()
    db2 = next(db_gen2)
    order_row2 = db2.query(Order).filter(Order.id == _UUID(order_id)).first()
    transition_order_status(db2, order_row2, OrderStatus.CANCELLED)
    db2.close()


def test_completed_delivery_appears_in_history(client):
    from app.db.session import get_db

    token = _register_and_login_rider(client)
    rider_id = _rider_id(client, token)
    admin_token = _make_admin(client)
    _make_rider_online(client, token, admin_token, rider_id)

    db_gen = client.app.dependency_overrides[get_db]()
    db = next(db_gen)
    order = _seed_order(db, payment_method="online")
    order_id = str(order.id)
    db.close()

    _complete_full_delivery(client, token, order_id)

    headers = {"Authorization": f"Bearer {token}"}
    history = client.get("/api/v1/rider/history", headers=headers)
    assert history.status_code == 200
    items = history.json()
    assert len(items) == 1
    item = items[0]
    assert item["order_id"] == order_id
    assert item["status"] == "delivered"
    assert item["payment_method"] == "online"
    assert Decimal(item["earning"]) == order.delivery_fee
    assert item["restaurant_name"] == "Diner"


def test_active_delivery_does_not_appear_in_history(client):
    from app.db.session import get_db

    token = _register_and_login_rider(client, email="active-not-history@example.com", phone="9970000011")
    rider_id = _rider_id(client, token)
    admin_token = _make_admin(client, email="admin2-history@example.com", phone="9970000098")
    _make_rider_online(client, token, admin_token, rider_id)

    db_gen = client.app.dependency_overrides[get_db]()
    db = next(db_gen)
    order = _seed_order(db, payment_method="online")
    order_id = str(order.id)
    db.close()

    from uuid import UUID as _UUID
    from app.models.order import Order, OrderStatus
    from app.services.orders import transition_order_status

    db_gen2 = client.app.dependency_overrides[get_db]()
    db2 = next(db_gen2)
    order_row = db2.query(Order).filter(Order.id == _UUID(order_id)).first()
    transition_order_status(db2, order_row, OrderStatus.CONFIRMED)
    transition_order_status(db2, order_row, OrderStatus.PREPARING)
    transition_order_status(db2, order_row, OrderStatus.READY_FOR_PICKUP)
    db2.close()

    headers = {"Authorization": f"Bearer {token}"}
    client.post(f"/api/v1/rider/deliveries/{order_id}/accept", headers=headers)

    history = client.get("/api/v1/rider/history", headers=headers).json()
    assert history == []


def test_cancelled_delivery_appears_in_history(client):
    from app.db.session import get_db

    token = _register_and_login_rider(client, email="cancelled-history@example.com", phone="9970000012")
    rider_id = _rider_id(client, token)
    admin_token = _make_admin(client, email="admin3-history@example.com", phone="9970000097")
    _make_rider_online(client, token, admin_token, rider_id)

    db_gen = client.app.dependency_overrides[get_db]()
    db = next(db_gen)
    order = _seed_order(db, payment_method="online")
    order_id = str(order.id)
    db.close()

    _cancel_after_assignment(client, token, order_id)

    headers = {"Authorization": f"Bearer {token}"}
    history = client.get("/api/v1/rider/history", headers=headers).json()
    assert len(history) == 1
    assert history[0]["status"] == "cancelled"


def test_status_filter_narrows_history(client):
    from app.db.session import get_db

    token = _register_and_login_rider(client, email="status-filter-history@example.com", phone="9970000013")
    rider_id = _rider_id(client, token)
    admin_token = _make_admin(client, email="admin4-history@example.com", phone="9970000096")
    _make_rider_online(client, token, admin_token, rider_id)

    db_gen = client.app.dependency_overrides[get_db]()
    db = next(db_gen)
    delivered_order = _seed_order(db, payment_method="online")
    delivered_order_id = str(delivered_order.id)
    cancelled_order = _seed_order(db, payment_method="online")
    cancelled_order_id = str(cancelled_order.id)
    db.close()

    _complete_full_delivery(client, token, delivered_order_id)
    _cancel_after_assignment(client, token, cancelled_order_id)

    headers = {"Authorization": f"Bearer {token}"}
    delivered_only = client.get("/api/v1/rider/history?status=delivered", headers=headers).json()
    assert len(delivered_only) == 1
    assert delivered_only[0]["order_id"] == delivered_order_id

    cancelled_only = client.get("/api/v1/rider/history?status=cancelled", headers=headers).json()
    assert len(cancelled_only) == 1
    assert cancelled_only[0]["order_id"] == cancelled_order_id


def test_pagination_limits_and_pages_results(client):
    from app.db.session import get_db

    token = _register_and_login_rider(client, email="pagination-history@example.com", phone="9970000014")
    rider_id = _rider_id(client, token)
    admin_token = _make_admin(client, email="admin5-history@example.com", phone="9970000095")
    _make_rider_online(client, token, admin_token, rider_id)

    order_ids = []
    for _ in range(3):
        db_gen = client.app.dependency_overrides[get_db]()
        db = next(db_gen)
        order = _seed_order(db, payment_method="online")
        order_id = str(order.id)
        db.close()
        _complete_full_delivery(client, token, order_id)
        order_ids.append(order_id)

    headers = {"Authorization": f"Bearer {token}"}
    page1 = client.get("/api/v1/rider/history?page=1&limit=2", headers=headers).json()
    page2 = client.get("/api/v1/rider/history?page=2&limit=2", headers=headers).json()
    assert len(page1) == 2
    assert len(page2) == 1
    returned_ids = {item["order_id"] for item in page1 + page2}
    assert returned_ids == set(order_ids)


def test_date_filtering_excludes_out_of_range_records(client):
    from datetime import UTC, datetime, timedelta

    from app.db.session import get_db

    token = _register_and_login_rider(client, email="date-filter-history@example.com", phone="9970000015")
    rider_id = _rider_id(client, token)
    admin_token = _make_admin(client, email="admin6-history@example.com", phone="9970000094")
    _make_rider_online(client, token, admin_token, rider_id)

    db_gen = client.app.dependency_overrides[get_db]()
    db = next(db_gen)
    order = _seed_order(db, payment_method="online")
    order_id = str(order.id)
    db.close()

    _complete_full_delivery(client, token, order_id)

    headers = {"Authorization": f"Bearer {token}"}
    future_start = (datetime.now(UTC) + timedelta(days=1)).isoformat()
    too_late = client.get("/api/v1/rider/history", headers=headers, params={"date_from": future_start}).json()
    assert too_late == []

    past_start = (datetime.now(UTC) - timedelta(days=1)).isoformat()
    in_range = client.get("/api/v1/rider/history", headers=headers, params={"date_from": past_start}).json()
    assert len(in_range) == 1


def test_history_detail_returns_full_record_scoped_to_rider(client):
    from app.db.session import get_db

    token = _register_and_login_rider(client, email="detail-history@example.com", phone="9970000016")
    rider_id = _rider_id(client, token)
    admin_token = _make_admin(client, email="admin7-history@example.com", phone="9970000093")
    _make_rider_online(client, token, admin_token, rider_id)

    db_gen = client.app.dependency_overrides[get_db]()
    db = next(db_gen)
    order = _seed_order(db, payment_method="online")
    order_id = str(order.id)
    db.close()

    _complete_full_delivery(client, token, order_id)

    headers = {"Authorization": f"Bearer {token}"}
    detail = client.get(f"/api/v1/rider/history/{order_id}", headers=headers)
    assert detail.status_code == 200
    body = detail.json()
    assert body["order_id"] == order_id
    assert body["status"] == "delivered"
    # Same Phase 15 privacy masking applies here — the delivery has concluded.
    assert body["customer_phone"] is None
    assert body["delivery_address_line"] == "Hidden after delivery"


def test_another_riders_history_item_is_not_accessible(client):
    from app.db.session import get_db

    token_a = _register_and_login_rider(client, email="history-a@example.com", phone="9970000017")
    rider_a_id = _rider_id(client, token_a)
    token_b = _register_and_login_rider(client, email="history-b@example.com", phone="9970000018")
    rider_b_id = _rider_id(client, token_b)
    admin_token = _make_admin(client, email="admin8-history@example.com", phone="9970000092")
    _make_rider_online(client, token_a, admin_token, rider_a_id)
    _make_rider_online(client, token_b, admin_token, rider_b_id)

    db_gen = client.app.dependency_overrides[get_db]()
    db = next(db_gen)
    order = _seed_order(db, payment_method="online")
    order_id = str(order.id)
    db.close()

    _complete_full_delivery(client, token_a, order_id)

    response = client.get(f"/api/v1/rider/history/{order_id}", headers={"Authorization": f"Bearer {token_b}"})
    assert response.status_code == 404

    # Rider B's own history list must not include rider A's delivery either.
    history_b = client.get("/api/v1/rider/history", headers={"Authorization": f"Bearer {token_b}"}).json()
    assert history_b == []


def test_customer_and_restaurant_owner_cannot_access_rider_history(client):
    from app.db.session import get_db

    db_gen = client.app.dependency_overrides[get_db]()
    db = next(db_gen)
    customer = User(name="C", email="c-history@example.com", phone="9970000051", password_hash=hash_password("x"), role=UserRole.CUSTOMER)
    owner = User(name="O", email="o-history@example.com", phone="9970000052", password_hash=hash_password("x"), role=UserRole.RESTAURANT_OWNER)
    db.add_all([customer, owner])
    db.commit()
    customer_token = create_access_token(customer.id)
    owner_token = create_access_token(owner.id)
    db.close()

    assert client.get("/api/v1/rider/history", headers={"Authorization": f"Bearer {customer_token}"}).status_code == 403
    assert client.get("/api/v1/rider/history", headers={"Authorization": f"Bearer {owner_token}"}).status_code == 403


def test_unauthenticated_request_is_rejected(client):
    assert client.get("/api/v1/rider/history").status_code == 401
    fake_id = "00000000-0000-0000-0000-000000000000"
    assert client.get(f"/api/v1/rider/history/{fake_id}").status_code == 401
