"""Rider Portal — Phase 8: Rider Dashboard."""

from decimal import Decimal

from app.core.security import create_access_token, hash_password
from app.models.user import User, UserRole


def _register_and_login_rider(client, email="rider-dash@example.com", phone="9700000010", name="Ravi Kumar"):
    client.post(
        "/api/v1/auth/register",
        json={"name": name, "email": email, "password": "secure-pass-123", "phone": phone, "role": "RIDER"},
    )
    login = client.post("/api/v1/auth/login", json={"email": email, "password": "secure-pass-123"})
    return login.json()["access_token"]


def _rider_id(client, token):
    return client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"}).json()["id"]


def test_new_rider_dashboard_is_all_zero(client):
    token = _register_and_login_rider(client)
    response = client.get("/api/v1/rider/dashboard", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200
    body = response.json()
    assert body["is_online"] is False
    assert body["today_deliveries_count"] == 0
    assert body["completed_deliveries_count"] == 0
    assert body["pending_deliveries_count"] == 0
    assert body["today_earnings"] == "0.00"
    assert body["current_assignment"] is None


def test_dashboard_reflects_online_status(client):
    from app.db.session import get_db

    token = _register_and_login_rider(client, email="online-dash@example.com", phone="9700000011")
    rider_id = _rider_id(client, token)

    db_gen = client.app.dependency_overrides[get_db]()
    db = next(db_gen)
    admin = User(name="Admin", email="admin-dash@example.com", phone="9700000099", password_hash=hash_password("x"), role=UserRole.ADMIN)
    db.add(admin)
    db.commit()
    admin_token = create_access_token(admin.id)
    db.close()

    admin_headers = {"Authorization": f"Bearer {admin_token}"}
    rider_headers = {"Authorization": f"Bearer {token}"}
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
    client.patch("/api/v1/rider/status", headers=rider_headers, json={"is_online": True})

    response = client.get("/api/v1/rider/dashboard", headers=rider_headers)
    assert response.json()["is_online"] is True


def _seed_order_for_rider(db, rider, status_value):
    from app.models.order import Order, OrderStatus
    from app.models.product import Product
    from app.models.restaurant import Restaurant
    from app.services.addresses import create_address
    from app.services.cart import add_item, create_cart_for_user
    from app.services.orders import assign_rider_to_order, create_order, transition_order_status
    import uuid

    suffix = uuid.uuid4().hex[:8]
    owner = User(name="Owner", email=f"owner-{suffix}@example.com", phone=f"97{suffix[:8]}", password_hash=hash_password("x"), role=UserRole.RESTAURANT_OWNER)
    db.add(owner)
    db.commit()
    restaurant = Restaurant(
        owner_id=owner.id, name="Diner", phone="9876500000", address="Road",
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
    order = create_order(db, customer, address.id)
    transition_order_status(db, order, OrderStatus.CONFIRMED)
    transition_order_status(db, order, OrderStatus.PREPARING)
    transition_order_status(db, order, OrderStatus.READY_FOR_PICKUP)
    assign_rider_to_order(db, order, rider.id)
    if status_value != OrderStatus.RIDER_ASSIGNED:
        transition_order_status(db, order, OrderStatus.PICKED_UP)
        transition_order_status(db, order, OrderStatus.OUT_FOR_DELIVERY)
        if status_value == OrderStatus.DELIVERED:
            transition_order_status(db, order, OrderStatus.DELIVERED)
    return order


def test_dashboard_counts_pending_and_completed_deliveries_separately(client):
    from app.db.session import get_db
    from app.models.order import OrderStatus

    token = _register_and_login_rider(client, email="counts-dash@example.com", phone="9700000012")
    rider_id = _rider_id(client, token)

    db_gen = client.app.dependency_overrides[get_db]()
    db = next(db_gen)
    rider = db.get(User, __import__("uuid").UUID(rider_id))
    _seed_order_for_rider(db, rider, OrderStatus.DELIVERED)
    _seed_order_for_rider(db, rider, OrderStatus.RIDER_ASSIGNED)
    _seed_order_for_rider(db, rider, OrderStatus.OUT_FOR_DELIVERY)
    db.close()

    response = client.get("/api/v1/rider/dashboard", headers={"Authorization": f"Bearer {token}"})
    body = response.json()
    assert body["completed_deliveries_count"] == 1
    assert body["pending_deliveries_count"] == 2
    assert body["today_deliveries_count"] == 3  # all three had activity today


def test_dashboard_earnings_sum_delivery_fees_of_todays_deliveries(client):
    from app.db.session import get_db
    from app.models.order import OrderStatus

    token = _register_and_login_rider(client, email="earnings-dash@example.com", phone="9700000013")
    rider_id = _rider_id(client, token)

    db_gen = client.app.dependency_overrides[get_db]()
    db = next(db_gen)
    rider = db.get(User, __import__("uuid").UUID(rider_id))
    _seed_order_for_rider(db, rider, OrderStatus.DELIVERED)  # delivery_fee 40.00
    _seed_order_for_rider(db, rider, OrderStatus.DELIVERED)  # delivery_fee 40.00
    _seed_order_for_rider(db, rider, OrderStatus.RIDER_ASSIGNED)  # not delivered — excluded
    db.close()

    response = client.get("/api/v1/rider/dashboard", headers={"Authorization": f"Bearer {token}"})
    assert response.json()["today_earnings"] == "80.00"


def test_dashboard_shows_current_assignment(client):
    from app.db.session import get_db
    from app.models.order import OrderStatus

    token = _register_and_login_rider(client, email="assignment-dash@example.com", phone="9700000014")
    rider_id = _rider_id(client, token)

    db_gen = client.app.dependency_overrides[get_db]()
    db = next(db_gen)
    rider = db.get(User, __import__("uuid").UUID(rider_id))
    order = _seed_order_for_rider(db, rider, OrderStatus.OUT_FOR_DELIVERY)
    order_id = str(order.id)
    db.close()

    response = client.get("/api/v1/rider/dashboard", headers={"Authorization": f"Bearer {token}"})
    body = response.json()
    assert body["current_assignment"] is not None
    assert body["current_assignment"]["id"] == order_id
    assert body["current_assignment"]["status"] == "out_for_delivery"


def test_dashboard_current_assignment_is_null_once_delivered(client):
    from app.db.session import get_db
    from app.models.order import OrderStatus

    token = _register_and_login_rider(client, email="done-dash@example.com", phone="9700000015")
    rider_id = _rider_id(client, token)

    db_gen = client.app.dependency_overrides[get_db]()
    db = next(db_gen)
    rider = db.get(User, __import__("uuid").UUID(rider_id))
    _seed_order_for_rider(db, rider, OrderStatus.DELIVERED)
    db.close()

    response = client.get("/api/v1/rider/dashboard", headers={"Authorization": f"Bearer {token}"})
    assert response.json()["current_assignment"] is None


def test_customer_and_restaurant_owner_cannot_access_rider_dashboard(client):
    from app.db.session import get_db

    db_gen = client.app.dependency_overrides[get_db]()
    db = next(db_gen)
    customer = User(name="C", email="c-dash@example.com", phone="9700000051", password_hash=hash_password("x"), role=UserRole.CUSTOMER)
    owner = User(name="O", email="o-dash@example.com", phone="9700000052", password_hash=hash_password("x"), role=UserRole.RESTAURANT_OWNER)
    db.add_all([customer, owner])
    db.commit()
    customer_token = create_access_token(customer.id)
    owner_token = create_access_token(owner.id)
    db.close()

    assert client.get("/api/v1/rider/dashboard", headers={"Authorization": f"Bearer {customer_token}"}).status_code == 403
    assert client.get("/api/v1/rider/dashboard", headers={"Authorization": f"Bearer {owner_token}"}).status_code == 403


def test_unauthenticated_request_is_rejected(client):
    assert client.get("/api/v1/rider/dashboard").status_code == 401
