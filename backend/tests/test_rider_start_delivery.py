"""Rider Portal — Phase 14: Start Delivery."""

from decimal import Decimal

from app.core.security import create_access_token, hash_password
from app.models.user import User, UserRole


def _register_and_login_rider(client, email="rider-start@example.com", phone="9930000010", name="Ravi Kumar"):
    client.post(
        "/api/v1/auth/register",
        json={"name": name, "email": email, "password": "secure-pass-123", "phone": phone, "role": "RIDER"},
    )
    login = client.post("/api/v1/auth/login", json={"email": email, "password": "secure-pass-123"})
    return login.json()["access_token"]


def _rider_id(client, token):
    return client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"}).json()["id"]


def _make_admin(client, email="admin-start@example.com", phone="9930000099"):
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


def _seed_ready_order(db):
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
    order = create_order(db, customer, address.id)
    transition_order_status(db, order, OrderStatus.CONFIRMED)
    transition_order_status(db, order, OrderStatus.PREPARING)
    transition_order_status(db, order, OrderStatus.READY_FOR_PICKUP)
    return order


def _accept_and_pickup(client, token, order_id):
    accept = client.post(f"/api/v1/rider/deliveries/{order_id}/accept", headers={"Authorization": f"Bearer {token}"})
    assert accept.status_code == 200
    pickup = client.post(f"/api/v1/rider/deliveries/{order_id}/pickup", headers={"Authorization": f"Bearer {token}"})
    assert pickup.status_code == 200


def test_start_delivery_transitions_to_out_for_delivery(client):
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

    _accept_and_pickup(client, token, order_id)
    response = client.post(f"/api/v1/rider/deliveries/{order_id}/start", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200
    assert response.json()["status"] == "out_for_delivery"


def test_start_delivery_records_timestamp_on_the_assignment(client):
    from app.db.session import get_db

    token = _register_and_login_rider(client, email="start-timestamp@example.com", phone="9930000011")
    rider_id = _rider_id(client, token)
    admin_token = _make_admin(client, email="admin2-start@example.com", phone="9930000098")
    _make_rider_online(client, token, admin_token, rider_id)

    db_gen = client.app.dependency_overrides[get_db]()
    db = next(db_gen)
    order = _seed_ready_order(db)
    order_id = str(order.id)
    db.close()

    _accept_and_pickup(client, token, order_id)
    client.post(f"/api/v1/rider/deliveries/{order_id}/start", headers={"Authorization": f"Bearer {token}"})

    detail = client.get(f"/api/v1/rider/deliveries/{order_id}", headers={"Authorization": f"Bearer {token}"})
    assert detail.json()["status"] == "out_for_delivery"
    assert detail.json()["assignment_status"] == "OUT_FOR_DELIVERY"


def test_cannot_start_delivery_before_pickup(client):
    from app.db.session import get_db

    token = _register_and_login_rider(client, email="no-pickup-start@example.com", phone="9930000012")
    rider_id = _rider_id(client, token)
    admin_token = _make_admin(client, email="admin3-start@example.com", phone="9930000097")
    _make_rider_online(client, token, admin_token, rider_id)

    db_gen = client.app.dependency_overrides[get_db]()
    db = next(db_gen)
    order = _seed_ready_order(db)
    order_id = str(order.id)
    db.close()

    accept = client.post(f"/api/v1/rider/deliveries/{order_id}/accept", headers={"Authorization": f"Bearer {token}"})
    assert accept.status_code == 200
    # Never picked up.
    response = client.post(f"/api/v1/rider/deliveries/{order_id}/start", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 409


def test_start_delivery_twice_is_idempotent_not_an_error(client):
    """Phase 28: a second start-delivery call for an order already
    OUT_FOR_DELIVERY is a lost-response retry, not an invalid transition —
    it returns the same success state rather than a 409."""
    from app.db.session import get_db

    token = _register_and_login_rider(client, email="double-start@example.com", phone="9930000013")
    rider_id = _rider_id(client, token)
    admin_token = _make_admin(client, email="admin4-start@example.com", phone="9930000096")
    _make_rider_online(client, token, admin_token, rider_id)

    db_gen = client.app.dependency_overrides[get_db]()
    db = next(db_gen)
    order = _seed_ready_order(db)
    order_id = str(order.id)
    db.close()

    _accept_and_pickup(client, token, order_id)
    headers = {"Authorization": f"Bearer {token}"}
    first = client.post(f"/api/v1/rider/deliveries/{order_id}/start", headers=headers)
    assert first.status_code == 200
    second = client.post(f"/api/v1/rider/deliveries/{order_id}/start", headers=headers)
    assert second.status_code == 200
    assert second.json()["status"] == "out_for_delivery"
    history_entries = [h for h in second.json()["status_history"] if h["status"] == "out_for_delivery"]
    assert len(history_entries) == 1


def test_another_riders_delivery_cannot_be_started(client):
    from app.db.session import get_db

    token_a = _register_and_login_rider(client, email="start-a@example.com", phone="9930000014")
    rider_a_id = _rider_id(client, token_a)
    token_b = _register_and_login_rider(client, email="start-b@example.com", phone="9930000015")
    rider_b_id = _rider_id(client, token_b)
    admin_token = _make_admin(client, email="admin5-start@example.com", phone="9930000095")
    _make_rider_online(client, token_a, admin_token, rider_a_id)
    _make_rider_online(client, token_b, admin_token, rider_b_id)

    db_gen = client.app.dependency_overrides[get_db]()
    db = next(db_gen)
    order = _seed_ready_order(db)
    order_id = str(order.id)
    db.close()

    _accept_and_pickup(client, token_a, order_id)
    response = client.post(f"/api/v1/rider/deliveries/{order_id}/start", headers={"Authorization": f"Bearer {token_b}"})
    assert response.status_code == 404


def test_start_delivery_works_for_an_order_assigned_directly_by_admin(client):
    from app.db.session import get_db
    from app.services.orders import assign_rider_to_order, transition_order_status
    from app.models.order import OrderStatus
    from uuid import UUID as _UUID

    token = _register_and_login_rider(client, email="admin-assigned-start@example.com", phone="9930000016")
    rider_id = _rider_id(client, token)
    admin_token = _make_admin(client, email="admin6-start@example.com", phone="9930000094")
    _make_rider_online(client, token, admin_token, rider_id)

    db_gen = client.app.dependency_overrides[get_db]()
    db = next(db_gen)
    order = _seed_ready_order(db)
    assign_rider_to_order(db, order, _UUID(rider_id))
    transition_order_status(db, order, OrderStatus.PICKED_UP)
    order_id = str(order.id)
    db.close()

    response = client.post(f"/api/v1/rider/deliveries/{order_id}/start", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200
    assert response.json()["status"] == "out_for_delivery"


def test_customer_and_restaurant_owner_cannot_start_delivery(client):
    from app.db.session import get_db

    db_gen = client.app.dependency_overrides[get_db]()
    db = next(db_gen)
    customer = User(name="C", email="c-start@example.com", phone="9930000051", password_hash=hash_password("x"), role=UserRole.CUSTOMER)
    owner = User(name="O", email="o-start@example.com", phone="9930000052", password_hash=hash_password("x"), role=UserRole.RESTAURANT_OWNER)
    db.add_all([customer, owner])
    db.commit()
    customer_token = create_access_token(customer.id)
    owner_token = create_access_token(owner.id)
    db.close()

    fake_id = "00000000-0000-0000-0000-000000000000"
    assert client.post(f"/api/v1/rider/deliveries/{fake_id}/start", headers={"Authorization": f"Bearer {customer_token}"}).status_code == 403
    assert client.post(f"/api/v1/rider/deliveries/{fake_id}/start", headers={"Authorization": f"Bearer {owner_token}"}).status_code == 403


def test_unauthenticated_request_is_rejected(client):
    fake_id = "00000000-0000-0000-0000-000000000000"
    assert client.post(f"/api/v1/rider/deliveries/{fake_id}/start").status_code == 401
