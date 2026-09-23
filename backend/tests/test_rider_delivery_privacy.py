"""Rider Portal — Phase 15: Customer Delivery Information & privacy controls.

Builds on Phase 11's GET /rider/deliveries/{id}: confirms the exact field
list the phase specifies is shown while a delivery is active, that no
unrelated customer information (email, account id, etc.) is ever present,
and that the customer's exact contact details (phone, address line,
landmark, coordinates, delivery notes) are hidden once the delivery is no
longer in progress — the rider has no further operational need for them.
"""

from decimal import Decimal

from app.core.security import create_access_token, hash_password
from app.models.user import User, UserRole


def _register_and_login_rider(client, email="rider-privacy@example.com", phone="9940000010", name="Ravi Kumar"):
    client.post(
        "/api/v1/auth/register",
        json={"name": name, "email": email, "password": "secure-pass-123", "phone": phone, "role": "RIDER"},
    )
    login = client.post("/api/v1/auth/login", json={"email": email, "password": "secure-pass-123"})
    return login.json()["access_token"]


def _rider_id(client, token):
    return client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"}).json()["id"]


def _make_admin(client, email="admin-privacy@example.com", phone="9940000099"):
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


def _seed_ready_order(db, payment_method="cod", is_paid=False):
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
    customer = User(
        name="Amit Sharma", email=f"cust-{suffix}@example.com", phone=f"96{suffix[:8]}",
        password_hash=hash_password("x"), role=UserRole.CUSTOMER,
    )
    db.add(customer)
    db.commit()
    product = Product(restaurant_id=restaurant.id, name="Item", price=Decimal("100.00"))
    db.add(product)
    db.commit()
    cart = create_cart_for_user(db, customer.id)
    add_item(db, cart, product.id, 1)
    address = create_address(db, customer.id, {
        "label": "Home", "recipient_name": "Amit Sharma", "phone": "9999999999",
        "address_line": "42 Secret Lane, Apt 5B", "city": "Bengaluru", "state": "Karnataka", "postal_code": "560001",
        "landmark": "Near the old bakery", "latitude": Decimal("12.9"), "longitude": Decimal("77.6"),
    })
    order = create_order(db, customer, address.id)
    order.payment_method = payment_method
    order.is_paid = is_paid
    db.commit()
    transition_order_status(db, order, OrderStatus.CONFIRMED)
    transition_order_status(db, order, OrderStatus.PREPARING)
    transition_order_status(db, order, OrderStatus.READY_FOR_PICKUP)
    return order, customer


def _accept_fresh_order(client, token, order_id):
    response = client.post(f"/api/v1/rider/deliveries/{order_id}/accept", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200, response.json()


# --------------------------- Active delivery: full info shown ---------------------------


def test_shows_exactly_the_specified_fields_while_delivery_is_active(client):
    from app.db.session import get_db

    token = _register_and_login_rider(client)
    rider_id = _rider_id(client, token)
    admin_token = _make_admin(client)
    _make_rider_online(client, token, admin_token, rider_id)

    db_gen = client.app.dependency_overrides[get_db]()
    db = next(db_gen)
    order, customer = _seed_ready_order(db)
    order_id = str(order.id)
    customer_phone = customer.phone
    db.close()

    _accept_fresh_order(client, token, order_id)
    response = client.get(f"/api/v1/rider/deliveries/{order_id}", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200
    body = response.json()

    assert body["customer_name"] == "Amit Sharma"
    assert body["customer_phone"] == customer_phone
    assert body["delivery_address_line"] == "42 Secret Lane, Apt 5B"
    assert body["delivery_landmark"] == "Near the old bakery"
    assert body["delivery_latitude"] is not None
    assert body["delivery_longitude"] is not None
    assert body["cod_amount"] == body["total"]


def test_no_unrelated_customer_information_is_ever_present(client):
    """Regardless of delivery status, fields like the customer's email or
    account id must never appear anywhere in the response."""
    from app.db.session import get_db

    token = _register_and_login_rider(client, email="no-leak@example.com", phone="9940000011")
    rider_id = _rider_id(client, token)
    admin_token = _make_admin(client, email="admin2-privacy@example.com", phone="9940000098")
    _make_rider_online(client, token, admin_token, rider_id)

    db_gen = client.app.dependency_overrides[get_db]()
    db = next(db_gen)
    order, customer = _seed_ready_order(db)
    order_id = str(order.id)
    customer_email = customer.email
    customer_user_id = str(customer.id)
    db.close()

    _accept_fresh_order(client, token, order_id)
    response = client.get(f"/api/v1/rider/deliveries/{order_id}", headers={"Authorization": f"Bearer {token}"})
    raw_body = response.text
    assert customer_email not in raw_body
    assert customer_user_id not in raw_body

    body = response.json()
    expected_keys = {
        "order_id", "order_number", "status", "assignment_status",
        "restaurant_name", "restaurant_phone", "restaurant_address", "restaurant_latitude", "restaurant_longitude",
        "customer_name", "customer_phone",
        "delivery_address_line", "delivery_city", "delivery_state", "delivery_postal_code",
        "delivery_landmark", "delivery_latitude", "delivery_longitude", "delivery_instructions",
        "items", "subtotal", "delivery_fee", "total", "payment_method", "is_paid", "cod_amount", "created_at",
    }
    assert set(body.keys()) == expected_keys


# --------------------------- After delivery: contact details hidden ---------------------------


def test_exact_contact_details_are_hidden_once_delivered(client):
    from app.db.session import get_db
    from app.models.order import OrderStatus
    from app.services.orders import transition_order_status

    token = _register_and_login_rider(client, email="delivered-privacy@example.com", phone="9940000012")
    rider_id = _rider_id(client, token)
    admin_token = _make_admin(client, email="admin3-privacy@example.com", phone="9940000097")
    _make_rider_online(client, token, admin_token, rider_id)

    db_gen = client.app.dependency_overrides[get_db]()
    db = next(db_gen)
    order, _customer = _seed_ready_order(db)
    order_id = str(order.id)
    db.close()

    _accept_fresh_order(client, token, order_id)
    client.post(f"/api/v1/rider/deliveries/{order_id}/pickup", headers={"Authorization": f"Bearer {token}"})
    client.post(f"/api/v1/rider/deliveries/{order_id}/start", headers={"Authorization": f"Bearer {token}"})

    db_gen2 = client.app.dependency_overrides[get_db]()
    db2 = next(db_gen2)
    order_row = db2.get(type(order), order.id)
    transition_order_status(db2, order_row, OrderStatus.DELIVERED)
    db2.close()

    response = client.get(f"/api/v1/rider/deliveries/{order_id}", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200
    body = response.json()

    assert body["status"] == "delivered"
    assert body["customer_phone"] is None
    assert body["delivery_address_line"] != "42 Secret Lane, Apt 5B"
    assert body["delivery_landmark"] is None
    assert body["delivery_latitude"] is None
    assert body["delivery_longitude"] is None
    assert body["delivery_instructions"] is None

    # Name and general area stay visible — neither is a way to re-contact or
    # re-locate the customer, and the rider legitimately wants their own record.
    assert body["customer_name"] == "Amit Sharma"
    assert body["delivery_city"] == "Bengaluru"
    assert body["delivery_state"] == "Karnataka"
    assert body["delivery_postal_code"] == "560001"


def test_exact_contact_details_are_hidden_once_cancelled(client):
    from app.db.session import get_db
    from app.models.order import OrderStatus
    from app.services.orders import transition_order_status

    token = _register_and_login_rider(client, email="cancelled-privacy@example.com", phone="9940000013")
    rider_id = _rider_id(client, token)
    admin_token = _make_admin(client, email="admin4-privacy@example.com", phone="9940000096")
    _make_rider_online(client, token, admin_token, rider_id)

    db_gen = client.app.dependency_overrides[get_db]()
    db = next(db_gen)
    order, _customer = _seed_ready_order(db)
    order_id = str(order.id)
    db.close()

    _accept_fresh_order(client, token, order_id)

    db_gen2 = client.app.dependency_overrides[get_db]()
    db2 = next(db_gen2)
    order_row = db2.get(type(order), order.id)
    transition_order_status(db2, order_row, OrderStatus.CANCELLED)
    db2.close()

    response = client.get(f"/api/v1/rider/deliveries/{order_id}", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "cancelled"
    assert body["customer_phone"] is None
    assert body["delivery_landmark"] is None


def test_cod_amount_still_shown_after_cancellation_since_its_not_customer_pii(client):
    """A cancelled COD order is never auto-marked paid (only DELIVERED does
    that) — the amount itself isn't personal information, just a figure, so
    it isn't part of the privacy masking."""
    from app.db.session import get_db
    from app.models.order import OrderStatus
    from app.services.orders import transition_order_status

    token = _register_and_login_rider(client, email="cod-after-cancel@example.com", phone="9940000014")
    rider_id = _rider_id(client, token)
    admin_token = _make_admin(client, email="admin5-privacy@example.com", phone="9940000095")
    _make_rider_online(client, token, admin_token, rider_id)

    db_gen = client.app.dependency_overrides[get_db]()
    db = next(db_gen)
    order, _customer = _seed_ready_order(db, payment_method="cod", is_paid=False)
    order_id = str(order.id)
    db.close()

    _accept_fresh_order(client, token, order_id)

    db_gen2 = client.app.dependency_overrides[get_db]()
    db2 = next(db_gen2)
    order_row = db2.get(type(order), order.id)
    transition_order_status(db2, order_row, OrderStatus.CANCELLED)
    db2.close()

    response = client.get(f"/api/v1/rider/deliveries/{order_id}", headers={"Authorization": f"Bearer {token}"})
    body = response.json()
    assert body["cod_amount"] == body["total"]


def test_active_statuses_all_show_full_contact_details(client):
    """RIDER_ASSIGNED, PICKED_UP, and OUT_FOR_DELIVERY are all "in progress" —
    none of them should trigger masking."""
    from app.db.session import get_db

    token = _register_and_login_rider(client, email="active-window@example.com", phone="9940000015")
    rider_id = _rider_id(client, token)
    admin_token = _make_admin(client, email="admin6-privacy@example.com", phone="9940000094")
    _make_rider_online(client, token, admin_token, rider_id)

    db_gen = client.app.dependency_overrides[get_db]()
    db = next(db_gen)
    order, customer = _seed_ready_order(db)
    order_id = str(order.id)
    customer_phone = customer.phone
    db.close()

    _accept_fresh_order(client, token, order_id)
    headers = {"Authorization": f"Bearer {token}"}

    assigned = client.get(f"/api/v1/rider/deliveries/{order_id}", headers=headers).json()
    assert assigned["customer_phone"] == customer_phone

    client.post(f"/api/v1/rider/deliveries/{order_id}/pickup", headers=headers)
    picked_up = client.get(f"/api/v1/rider/deliveries/{order_id}", headers=headers).json()
    assert picked_up["customer_phone"] == customer_phone

    client.post(f"/api/v1/rider/deliveries/{order_id}/start", headers=headers)
    out_for_delivery = client.get(f"/api/v1/rider/deliveries/{order_id}", headers=headers).json()
    assert out_for_delivery["customer_phone"] == customer_phone
