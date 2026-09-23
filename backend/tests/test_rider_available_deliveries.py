"""Rider Portal — Phase 9: Available Delivery Requests."""

from decimal import Decimal

from app.core.security import create_access_token, hash_password
from app.models.user import User, UserRole


def _register_and_login_rider(client, email="rider-avail@example.com", phone="9800000010", name="Ravi Kumar"):
    client.post(
        "/api/v1/auth/register",
        json={"name": name, "email": email, "password": "secure-pass-123", "phone": phone, "role": "RIDER"},
    )
    login = client.post("/api/v1/auth/login", json={"email": email, "password": "secure-pass-123"})
    return login.json()["access_token"]


def _rider_id(client, token):
    return client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"}).json()["id"]


def _make_admin(client, email="admin-avail@example.com", phone="9800000099"):
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


def _seed_ready_order(db, city="Bengaluru", delivery_fee=Decimal("40.00")):
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
        latitude=Decimal("12.1000000"), longitude=Decimal("77.1000000"),
        minimum_order=Decimal("0.00"), delivery_fee=delivery_fee,
    )
    db.add(restaurant)
    db.commit()
    customer = User(name="Amit Sharma", email=f"cust-{suffix}@example.com", phone=f"96{suffix[:8]}", password_hash=hash_password("x"), role=UserRole.CUSTOMER)
    db.add(customer)
    db.commit()
    product = Product(restaurant_id=restaurant.id, name="Item", price=Decimal("100.00"))
    db.add(product)
    db.commit()
    cart = create_cart_for_user(db, customer.id)
    add_item(db, cart, product.id, 1)
    address = create_address(db, customer.id, {
        "label": "Home", "recipient_name": "Amit Sharma", "phone": "9999999999",
        "address_line": "42 Secret Lane, Apt 5B", "city": city, "state": "Karnataka", "postal_code": "560001",
        "landmark": "Near the old bakery",
    })
    order = create_order(db, customer, address.id)
    transition_order_status(db, order, OrderStatus.CONFIRMED)
    transition_order_status(db, order, OrderStatus.PREPARING)
    transition_order_status(db, order, OrderStatus.READY_FOR_PICKUP)
    return order, restaurant


def test_offline_rider_cannot_see_available_deliveries(client):
    token = _register_and_login_rider(client)
    response = client.get("/api/v1/rider/deliveries/available", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 403
    assert "online" in response.json()["detail"].lower()


def test_online_rider_with_no_ready_orders_sees_an_empty_list(client):
    token = _register_and_login_rider(client, email="empty-avail@example.com", phone="9800000011")
    rider_id = _rider_id(client, token)
    admin_token = _make_admin(client)
    _make_rider_online(client, token, admin_token, rider_id)

    response = client.get("/api/v1/rider/deliveries/available", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200
    assert response.json() == []


def test_online_rider_sees_a_ready_for_pickup_order(client):
    from app.db.session import get_db

    token = _register_and_login_rider(client, email="sees-avail@example.com", phone="9800000012")
    rider_id = _rider_id(client, token)
    admin_token = _make_admin(client, email="admin2-avail@example.com", phone="9800000098")
    _make_rider_online(client, token, admin_token, rider_id)

    db_gen = client.app.dependency_overrides[get_db]()
    db = next(db_gen)
    order, restaurant = _seed_ready_order(db)
    order_id = str(order.id)
    db.close()

    response = client.get("/api/v1/rider/deliveries/available", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    entry = body[0]
    assert entry["assignment_id"] == order_id
    assert entry["order_id"] == order_id
    assert entry["restaurant_name"] == "Diner"
    assert entry["customer_area"] == "Bengaluru"
    assert entry["estimated_earning"] == "40.00"


def test_response_never_exposes_customer_personal_information(client):
    from app.db.session import get_db

    token = _register_and_login_rider(client, email="privacy-avail@example.com", phone="9800000013")
    rider_id = _rider_id(client, token)
    admin_token = _make_admin(client, email="admin3-avail@example.com", phone="9800000097")
    _make_rider_online(client, token, admin_token, rider_id)

    db_gen = client.app.dependency_overrides[get_db]()
    db = next(db_gen)
    _seed_ready_order(db)
    db.close()

    response = client.get("/api/v1/rider/deliveries/available", headers={"Authorization": f"Bearer {token}"})
    raw_body = response.text
    # Nothing from the customer's real name, phone, exact address, or landmark
    # ever appears in the payload — only the coarse city.
    assert "Amit Sharma" not in raw_body
    assert "9999999999" not in raw_body
    assert "Secret Lane" not in raw_body
    assert "old bakery" not in raw_body
    entry = response.json()[0]
    assert set(entry.keys()) == {
        "assignment_id", "order_id", "restaurant_name", "restaurant_address",
        "restaurant_latitude", "restaurant_longitude", "customer_area",
        "estimated_distance_km", "estimated_earning", "ready_since",
    }


def test_estimated_distance_is_null_without_a_known_rider_location(client):
    from app.db.session import get_db

    token = _register_and_login_rider(client, email="no-location-avail@example.com", phone="9800000014")
    rider_id = _rider_id(client, token)
    admin_token = _make_admin(client, email="admin4-avail@example.com", phone="9800000096")
    _make_rider_online(client, token, admin_token, rider_id)

    db_gen = client.app.dependency_overrides[get_db]()
    db = next(db_gen)
    _seed_ready_order(db)
    db.close()

    response = client.get("/api/v1/rider/deliveries/available", headers={"Authorization": f"Bearer {token}"})
    assert response.json()[0]["estimated_distance_km"] is None


def test_estimated_distance_is_computed_once_rider_reports_a_location(client):
    from app.db.session import get_db

    token = _register_and_login_rider(client, email="located-avail@example.com", phone="9800000015")
    rider_id = _rider_id(client, token)
    admin_token = _make_admin(client, email="admin5-avail@example.com", phone="9800000095")
    _make_rider_online(client, token, admin_token, rider_id)

    client.patch(
        "/api/v1/rider/location", headers={"Authorization": f"Bearer {token}"},
        json={"latitude": "12.1000000", "longitude": "77.1000000"},
    )

    db_gen = client.app.dependency_overrides[get_db]()
    db = next(db_gen)
    _seed_ready_order(db)  # restaurant at the exact same coordinates
    db.close()

    response = client.get("/api/v1/rider/deliveries/available", headers={"Authorization": f"Bearer {token}"})
    assert response.json()[0]["estimated_distance_km"] == 0.0


def test_an_already_assigned_order_is_not_listed_as_available(client):
    from app.db.session import get_db
    from app.services.orders import assign_rider_to_order

    token = _register_and_login_rider(client, email="assigned-avail@example.com", phone="9800000016")
    rider_id = _rider_id(client, token)
    admin_token = _make_admin(client, email="admin6-avail@example.com", phone="9800000094")
    _make_rider_online(client, token, admin_token, rider_id)

    db_gen = client.app.dependency_overrides[get_db]()
    db = next(db_gen)
    order, _ = _seed_ready_order(db)
    import uuid as uuid_module

    other_rider = User(name="Other Rider", email="other-rider@example.com", phone="9800000017", password_hash=hash_password("x"), role=UserRole.RIDER)
    db.add(other_rider)
    db.commit()
    assign_rider_to_order(db, order, other_rider.id)
    db.close()

    response = client.get("/api/v1/rider/deliveries/available", headers={"Authorization": f"Bearer {token}"})
    assert response.json() == []


def test_a_delivered_order_is_not_listed_as_available(client):
    from app.db.session import get_db
    from app.models.order import OrderStatus
    from app.services.orders import assign_rider_to_order, transition_order_status

    token = _register_and_login_rider(client, email="delivered-avail@example.com", phone="9800000018")
    rider_id = _rider_id(client, token)
    admin_token = _make_admin(client, email="admin7-avail@example.com", phone="9800000093")
    _make_rider_online(client, token, admin_token, rider_id)

    db_gen = client.app.dependency_overrides[get_db]()
    db = next(db_gen)
    order, _ = _seed_ready_order(db)
    other_rider = User(name="Other Rider2", email="other-rider2@example.com", phone="9800000019", password_hash=hash_password("x"), role=UserRole.RIDER)
    db.add(other_rider)
    db.commit()
    assign_rider_to_order(db, order, other_rider.id)
    transition_order_status(db, order, OrderStatus.PICKED_UP)
    transition_order_status(db, order, OrderStatus.OUT_FOR_DELIVERY)
    transition_order_status(db, order, OrderStatus.DELIVERED)
    db.close()

    response = client.get("/api/v1/rider/deliveries/available", headers={"Authorization": f"Bearer {token}"})
    assert response.json() == []


def test_customer_and_restaurant_owner_cannot_access_available_deliveries(client):
    from app.db.session import get_db

    db_gen = client.app.dependency_overrides[get_db]()
    db = next(db_gen)
    customer = User(name="C", email="c-avail@example.com", phone="9800000051", password_hash=hash_password("x"), role=UserRole.CUSTOMER)
    owner = User(name="O", email="o-avail@example.com", phone="9800000052", password_hash=hash_password("x"), role=UserRole.RESTAURANT_OWNER)
    db.add_all([customer, owner])
    db.commit()
    customer_token = create_access_token(customer.id)
    owner_token = create_access_token(owner.id)
    db.close()

    assert client.get("/api/v1/rider/deliveries/available", headers={"Authorization": f"Bearer {customer_token}"}).status_code == 403
    assert client.get("/api/v1/rider/deliveries/available", headers={"Authorization": f"Bearer {owner_token}"}).status_code == 403


def test_unauthenticated_request_is_rejected(client):
    assert client.get("/api/v1/rider/deliveries/available").status_code == 401
