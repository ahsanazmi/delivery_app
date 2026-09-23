"""Rider Portal — Phase 11: Delivery Details."""

from decimal import Decimal

from app.core.security import create_access_token, hash_password
from app.models.user import User, UserRole


def _register_and_login_rider(client, email="rider-detail@example.com", phone="9910000010", name="Ravi Kumar"):
    client.post(
        "/api/v1/auth/register",
        json={"name": name, "email": email, "password": "secure-pass-123", "phone": phone, "role": "RIDER"},
    )
    login = client.post("/api/v1/auth/login", json={"email": email, "password": "secure-pass-123"})
    return login.json()["access_token"]


def _rider_id(client, token):
    return client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"}).json()["id"]


def _make_admin(client, email="admin-detail@example.com", phone="9910000099"):
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


def _seed_ready_order(db, payment_method="cod", is_paid=False, delivery_fee=Decimal("40.00")):
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
    customer = User(name="Amit Sharma", email=f"cust-{suffix}@example.com", phone=f"96{suffix[:8]}", password_hash=hash_password("x"), role=UserRole.CUSTOMER)
    db.add(customer)
    db.commit()
    product = Product(restaurant_id=restaurant.id, name="Butter Chicken", price=Decimal("100.00"))
    db.add(product)
    db.commit()
    cart = create_cart_for_user(db, customer.id)
    add_item(db, cart, product.id, 2)
    address = create_address(db, customer.id, {
        "label": "Home", "recipient_name": "Amit Sharma", "phone": "9999999999",
        "address_line": "42 MG Road", "city": "Bengaluru", "state": "Karnataka", "postal_code": "560001",
        "landmark": "Near the mall",
    })
    order = create_order(db, customer, address.id)
    order.payment_method = payment_method
    order.is_paid = is_paid
    db.commit()
    transition_order_status(db, order, OrderStatus.CONFIRMED)
    transition_order_status(db, order, OrderStatus.PREPARING)
    transition_order_status(db, order, OrderStatus.READY_FOR_PICKUP)
    return order


def test_assigned_rider_sees_full_delivery_details(client):
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

    accept = client.post(f"/api/v1/rider/deliveries/{order_id}/accept", headers={"Authorization": f"Bearer {token}"})
    assert accept.status_code == 200

    response = client.get(f"/api/v1/rider/deliveries/{order_id}", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200
    body = response.json()
    assert body["order_id"] == order_id
    assert body["order_number"] == accept.json()["order_number"]
    assert body["restaurant_name"] == "Diner"
    assert body["restaurant_latitude"] == "12.1000000"
    assert body["customer_name"] == "Amit Sharma"
    assert body["delivery_address_line"] == "42 MG Road"
    assert body["delivery_landmark"] == "Near the mall"
    assert len(body["items"]) == 1
    assert body["items"][0]["product_name"] == "Butter Chicken"
    assert body["items"][0]["quantity"] == 2
    assert body["total"] == "240.00"  # 2*100 + 40 delivery fee


def test_cod_amount_shown_for_unpaid_cod_order(client):
    from app.db.session import get_db

    token = _register_and_login_rider(client, email="cod-detail@example.com", phone="9910000011")
    rider_id = _rider_id(client, token)
    admin_token = _make_admin(client, email="admin2-detail@example.com", phone="9910000098")
    _make_rider_online(client, token, admin_token, rider_id)

    db_gen = client.app.dependency_overrides[get_db]()
    db = next(db_gen)
    order = _seed_ready_order(db, payment_method="cod", is_paid=False)
    order_id = str(order.id)
    db.close()

    client.post(f"/api/v1/rider/deliveries/{order_id}/accept", headers={"Authorization": f"Bearer {token}"})
    response = client.get(f"/api/v1/rider/deliveries/{order_id}", headers={"Authorization": f"Bearer {token}"})
    body = response.json()
    assert body["payment_method"] == "cod"
    assert body["is_paid"] is False
    assert body["cod_amount"] == body["total"]


def test_cod_amount_is_null_for_a_prepaid_order(client):
    from app.db.session import get_db

    token = _register_and_login_rider(client, email="prepaid-detail@example.com", phone="9910000012")
    rider_id = _rider_id(client, token)
    admin_token = _make_admin(client, email="admin3-detail@example.com", phone="9910000097")
    _make_rider_online(client, token, admin_token, rider_id)

    db_gen = client.app.dependency_overrides[get_db]()
    db = next(db_gen)
    order = _seed_ready_order(db, payment_method="razorpay", is_paid=True)
    order_id = str(order.id)
    db.close()

    client.post(f"/api/v1/rider/deliveries/{order_id}/accept", headers={"Authorization": f"Bearer {token}"})
    response = client.get(f"/api/v1/rider/deliveries/{order_id}", headers={"Authorization": f"Bearer {token}"})
    body = response.json()
    assert body["cod_amount"] is None


def test_unassigned_order_is_not_visible_via_delivery_detail(client):
    from app.db.session import get_db

    token = _register_and_login_rider(client, email="unassigned-detail@example.com", phone="9910000013")
    rider_id = _rider_id(client, token)
    admin_token = _make_admin(client, email="admin4-detail@example.com", phone="9910000096")
    _make_rider_online(client, token, admin_token, rider_id)

    db_gen = client.app.dependency_overrides[get_db]()
    db = next(db_gen)
    order = _seed_ready_order(db)  # never accepted
    order_id = str(order.id)
    db.close()

    response = client.get(f"/api/v1/rider/deliveries/{order_id}", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 404


def test_another_riders_delivery_is_not_visible(client):
    from app.db.session import get_db

    token_a = _register_and_login_rider(client, email="detail-a@example.com", phone="9910000014")
    rider_a_id = _rider_id(client, token_a)
    token_b = _register_and_login_rider(client, email="detail-b@example.com", phone="9910000015")
    rider_b_id = _rider_id(client, token_b)
    admin_token = _make_admin(client, email="admin5-detail@example.com", phone="9910000095")
    _make_rider_online(client, token_a, admin_token, rider_a_id)
    _make_rider_online(client, token_b, admin_token, rider_b_id)

    db_gen = client.app.dependency_overrides[get_db]()
    db = next(db_gen)
    order = _seed_ready_order(db)
    order_id = str(order.id)
    db.close()

    client.post(f"/api/v1/rider/deliveries/{order_id}/accept", headers={"Authorization": f"Bearer {token_a}"})

    response = client.get(f"/api/v1/rider/deliveries/{order_id}", headers={"Authorization": f"Bearer {token_b}"})
    assert response.status_code == 404

    own_view = client.get(f"/api/v1/rider/deliveries/{order_id}", headers={"Authorization": f"Bearer {token_a}"})
    assert own_view.status_code == 200


def test_nonexistent_delivery_is_404(client):
    token = _register_and_login_rider(client, email="fake-detail@example.com", phone="9910000016")
    fake_id = "00000000-0000-0000-0000-000000000000"
    response = client.get(f"/api/v1/rider/deliveries/{fake_id}", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 404


def test_customer_and_restaurant_owner_cannot_access_delivery_details(client):
    from app.db.session import get_db

    db_gen = client.app.dependency_overrides[get_db]()
    db = next(db_gen)
    customer = User(name="C", email="c-detail@example.com", phone="9910000051", password_hash=hash_password("x"), role=UserRole.CUSTOMER)
    owner = User(name="O", email="o-detail@example.com", phone="9910000052", password_hash=hash_password("x"), role=UserRole.RESTAURANT_OWNER)
    db.add_all([customer, owner])
    db.commit()
    customer_token = create_access_token(customer.id)
    owner_token = create_access_token(owner.id)
    db.close()

    fake_id = "00000000-0000-0000-0000-000000000000"
    assert client.get(f"/api/v1/rider/deliveries/{fake_id}", headers={"Authorization": f"Bearer {customer_token}"}).status_code == 403
    assert client.get(f"/api/v1/rider/deliveries/{fake_id}", headers={"Authorization": f"Bearer {owner_token}"}).status_code == 403


def test_unauthenticated_request_is_rejected(client):
    fake_id = "00000000-0000-0000-0000-000000000000"
    assert client.get(f"/api/v1/rider/deliveries/{fake_id}").status_code == 401


def test_available_deliveries_route_still_resolves_correctly(client):
    """Regression guard for the routing-order hazard: /deliveries/available
    must never be swallowed by the /deliveries/{order_id} pattern."""
    token = _register_and_login_rider(client, email="routing-guard@example.com", phone="9910000017")
    response = client.get("/api/v1/rider/deliveries/available", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code in (200, 403)  # never 422 (which would mean it was mis-routed as a UUID)
