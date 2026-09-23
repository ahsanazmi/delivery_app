"""Rider Portal — Phase 21: Rider Notifications."""

from decimal import Decimal

from app.core.security import create_access_token, hash_password
from app.models.user import User, UserRole


def _register_and_login_rider(client, email="rider-notif@example.com", phone="9910000010", name="Ravi Kumar"):
    client.post(
        "/api/v1/auth/register",
        json={"name": name, "email": email, "password": "secure-pass-123", "phone": phone, "role": "RIDER"},
    )
    login = client.post("/api/v1/auth/login", json={"email": email, "password": "secure-pass-123"})
    return login.json()["access_token"]


def _rider_id(client, token):
    return client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"}).json()["id"]


def _make_admin(client, email="admin-notif@example.com", phone="9910000099"):
    from app.db.session import get_db

    db_gen = client.app.dependency_overrides[get_db]()
    db = next(db_gen)
    admin = User(name="Admin", email=email, phone=phone, password_hash=hash_password("x"), role=UserRole.ADMIN)
    db.add(admin)
    db.commit()
    token = create_access_token(admin.id)
    db.close()
    return token


def _approve_rider_only(client, admin_token, rider_id):
    admin_headers = {"Authorization": f"Bearer {admin_token}"}
    return client.patch(
        f"/api/v1/admin/riders/{rider_id}/verification", headers=admin_headers, json={"approval_status": "APPROVED"}
    )


def _make_rider_online(client, token, admin_token, rider_id):
    rider_headers = {"Authorization": f"Bearer {token}"}
    admin_headers = {"Authorization": f"Bearer {admin_token}"}
    _approve_rider_only(client, admin_token, rider_id)
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


def _seed_order(db):
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
    return order


def test_going_ready_for_pickup_notifies_online_eligible_riders(client):
    from app.db.session import get_db
    from app.models.order import Order, OrderStatus
    from app.services.orders import transition_order_status

    token = _register_and_login_rider(client)
    rider_id = _rider_id(client, token)
    admin_token = _make_admin(client)
    _make_rider_online(client, token, admin_token, rider_id)

    # A second rider who is NOT online must not be notified.
    offline_token = _register_and_login_rider(client, email="offline-notif@example.com", phone="9910000011")
    offline_rider_id = _rider_id(client, offline_token)
    _approve_rider_only(client, admin_token, offline_rider_id)

    db_gen = client.app.dependency_overrides[get_db]()
    db = next(db_gen)
    order = _seed_order(db)
    order_row = db.query(Order).filter(Order.id == order.id).first()
    transition_order_status(db, order_row, OrderStatus.CONFIRMED)
    transition_order_status(db, order_row, OrderStatus.PREPARING)
    transition_order_status(db, order_row, OrderStatus.READY_FOR_PICKUP)
    order_id = str(order.id)
    db.close()

    online_notifications = client.get("/api/v1/rider/notifications", headers={"Authorization": f"Bearer {token}"}).json()
    matching = [n for n in online_notifications if n["type"] == "new_delivery" and n["order_id"] == order_id]
    assert len(matching) == 1
    assert matching[0]["is_read"] is False

    offline_notifications = client.get(
        "/api/v1/rider/notifications", headers={"Authorization": f"Bearer {offline_token}"}
    ).json()
    assert all(n["order_id"] != order_id for n in offline_notifications)


def test_cancelling_an_assigned_delivery_notifies_the_rider(client):
    from uuid import UUID as _UUID

    from app.db.session import get_db
    from app.models.order import Order, OrderStatus
    from app.services.orders import transition_order_status

    token = _register_and_login_rider(client, email="cancel-notif@example.com", phone="9910000012")
    rider_id = _rider_id(client, token)
    admin_token = _make_admin(client, email="admin2-notif@example.com", phone="9910000098")
    _make_rider_online(client, token, admin_token, rider_id)

    db_gen = client.app.dependency_overrides[get_db]()
    db = next(db_gen)
    order = _seed_order(db)
    order_row = db.query(Order).filter(Order.id == order.id).first()
    transition_order_status(db, order_row, OrderStatus.CONFIRMED)
    transition_order_status(db, order_row, OrderStatus.PREPARING)
    transition_order_status(db, order_row, OrderStatus.READY_FOR_PICKUP)
    order_id = str(order.id)
    db.close()

    headers = {"Authorization": f"Bearer {token}"}
    assert client.post(f"/api/v1/rider/deliveries/{order_id}/accept", headers=headers).status_code == 200

    db_gen2 = client.app.dependency_overrides[get_db]()
    db2 = next(db_gen2)
    order_row2 = db2.query(Order).filter(Order.id == _UUID(order_id)).first()
    transition_order_status(db2, order_row2, OrderStatus.CANCELLED)
    db2.close()

    notifications = client.get("/api/v1/rider/notifications", headers=headers).json()
    matching = [n for n in notifications if n["type"] == "delivery_cancelled" and n["order_id"] == order_id]
    assert len(matching) == 1


def test_approval_and_suspension_notify_the_rider(client):
    token = _register_and_login_rider(client, email="approve-notif@example.com", phone="9910000013")
    rider_id = _rider_id(client, token)
    admin_token = _make_admin(client, email="admin3-notif@example.com", phone="9910000097")
    admin_headers = {"Authorization": f"Bearer {admin_token}"}
    headers = {"Authorization": f"Bearer {token}"}

    client.patch(f"/api/v1/admin/riders/{rider_id}/verification", headers=admin_headers, json={"approval_status": "APPROVED"})
    notifications = client.get("/api/v1/rider/notifications", headers=headers).json()
    assert any(n["type"] == "account_approved" for n in notifications)

    client.patch(f"/api/v1/admin/riders/{rider_id}/verification", headers=admin_headers, json={"approval_status": "SUSPENDED"})
    notifications = client.get("/api/v1/rider/notifications", headers=headers).json()
    assert any(n["type"] == "account_suspended" for n in notifications)


def test_mark_notification_read_and_read_all(client):
    token = _register_and_login_rider(client, email="mark-read-notif@example.com", phone="9910000014")
    rider_id = _rider_id(client, token)
    admin_token = _make_admin(client, email="admin4-notif@example.com", phone="9910000096")
    admin_headers = {"Authorization": f"Bearer {admin_token}"}
    headers = {"Authorization": f"Bearer {token}"}

    client.patch(f"/api/v1/admin/riders/{rider_id}/verification", headers=admin_headers, json={"approval_status": "APPROVED"})
    client.patch(f"/api/v1/admin/riders/{rider_id}/verification", headers=admin_headers, json={"approval_status": "SUSPENDED"})

    notifications = client.get("/api/v1/rider/notifications", headers=headers).json()
    assert len(notifications) == 2
    assert all(n["is_read"] is False for n in notifications)

    first_id = notifications[0]["id"]
    marked = client.post(f"/api/v1/rider/notifications/{first_id}/read", headers=headers)
    assert marked.status_code == 200
    assert marked.json()["is_read"] is True

    mark_all = client.post("/api/v1/rider/notifications/read-all", headers=headers)
    assert mark_all.status_code == 200
    assert mark_all.json()["updated"] == 1  # the other, still-unread one

    notifications = client.get("/api/v1/rider/notifications", headers=headers).json()
    assert all(n["is_read"] is True for n in notifications)


def test_cannot_mark_another_riders_notification_read(client):
    token_a = _register_and_login_rider(client, email="notif-a@example.com", phone="9910000015")
    rider_a_id = _rider_id(client, token_a)
    token_b = _register_and_login_rider(client, email="notif-b@example.com", phone="9910000016")
    admin_token = _make_admin(client, email="admin5-notif@example.com", phone="9910000095")
    admin_headers = {"Authorization": f"Bearer {admin_token}"}

    client.patch(f"/api/v1/admin/riders/{rider_a_id}/verification", headers=admin_headers, json={"approval_status": "APPROVED"})
    notification_id = client.get(
        "/api/v1/rider/notifications", headers={"Authorization": f"Bearer {token_a}"}
    ).json()[0]["id"]

    response = client.post(
        f"/api/v1/rider/notifications/{notification_id}/read", headers={"Authorization": f"Bearer {token_b}"}
    )
    assert response.status_code == 404


def test_all_eight_notification_types_are_valid_and_round_trip(client):
    """DELIVERY_UPDATED, PAYMENT_UPDATE, and EARNING_UPDATE have no automatic
    producer yet (Phase 21 only wires NEW_DELIVERY, DELIVERY_CANCELLED, and
    ACCOUNT_APPROVED/SUSPENDED into real lifecycle events) — inserted
    directly here, the same pattern used for Phase 19/20's not-yet-producible
    ledger entry types, to prove every type in the spec is a valid, working
    value end-to-end."""
    from uuid import UUID as _UUID

    from app.db.session import get_db
    from app.models.notification import Notification, NotificationType

    token = _register_and_login_rider(client, email="all-types-notif@example.com", phone="9910000017")
    rider_id = _rider_id(client, token)

    db_gen = client.app.dependency_overrides[get_db]()
    db = next(db_gen)
    for notification_type in (
        NotificationType.DELIVERY_UPDATED,
        NotificationType.PAYMENT_UPDATE,
        NotificationType.EARNING_UPDATE,
        NotificationType.SYSTEM,
    ):
        db.add(
            Notification(
                user_id=_UUID(rider_id), type=notification_type, title=notification_type.value, body="test"
            )
        )
    db.commit()
    db.close()

    notifications = client.get("/api/v1/rider/notifications", headers={"Authorization": f"Bearer {token}"}).json()
    types = {n["type"] for n in notifications}
    assert types == {"delivery_updated", "payment_update", "earning_update", "system"}


def test_customer_and_restaurant_owner_cannot_access_rider_notifications(client):
    from app.db.session import get_db

    db_gen = client.app.dependency_overrides[get_db]()
    db = next(db_gen)
    customer = User(name="C", email="c-notif@example.com", phone="9910000051", password_hash=hash_password("x"), role=UserRole.CUSTOMER)
    owner = User(name="O", email="o-notif@example.com", phone="9910000052", password_hash=hash_password("x"), role=UserRole.RESTAURANT_OWNER)
    db.add_all([customer, owner])
    db.commit()
    customer_token = create_access_token(customer.id)
    owner_token = create_access_token(owner.id)
    db.close()

    for token in (customer_token, owner_token):
        assert client.get("/api/v1/rider/notifications", headers={"Authorization": f"Bearer {token}"}).status_code == 403
        assert client.post("/api/v1/rider/notifications/read-all", headers={"Authorization": f"Bearer {token}"}).status_code == 403


def test_unauthenticated_request_is_rejected(client):
    fake_id = "00000000-0000-0000-0000-000000000000"
    assert client.get("/api/v1/rider/notifications").status_code == 401
    assert client.post(f"/api/v1/rider/notifications/{fake_id}/read").status_code == 401
    assert client.post("/api/v1/rider/notifications/read-all").status_code == 401
