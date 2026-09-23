"""Rider Portal — Phase 17: Complete Delivery."""

from decimal import Decimal

from app.core.security import create_access_token, hash_password
from app.models.user import User, UserRole


def _register_and_login_rider(client, email="rider-complete@example.com", phone="9960000010", name="Ravi Kumar"):
    client.post(
        "/api/v1/auth/register",
        json={"name": name, "email": email, "password": "secure-pass-123", "phone": phone, "role": "RIDER"},
    )
    login = client.post("/api/v1/auth/login", json={"email": email, "password": "secure-pass-123"})
    return login.json()["access_token"]


def _rider_id(client, token):
    return client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"}).json()["id"]


def _make_admin(client, email="admin-complete@example.com", phone="9960000099"):
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


def _advance_to_out_for_delivery(client, token, order_id):
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


def test_completes_a_prepaid_online_order(client):
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

    _advance_to_out_for_delivery(client, token, order_id)
    response = client.post(f"/api/v1/rider/deliveries/{order_id}/complete", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200, response.json()
    assert response.json()["status"] == "delivered"


def test_cod_order_cannot_be_completed_before_cash_is_collected(client):
    from app.db.session import get_db

    token = _register_and_login_rider(client, email="cod-not-collected@example.com", phone="9960000011")
    rider_id = _rider_id(client, token)
    admin_token = _make_admin(client, email="admin2-complete@example.com", phone="9960000098")
    _make_rider_online(client, token, admin_token, rider_id)

    db_gen = client.app.dependency_overrides[get_db]()
    db = next(db_gen)
    order = _seed_order(db)
    order_id = str(order.id)
    db.close()

    _advance_to_out_for_delivery(client, token, order_id)
    # Cash never collected via cod-collect.
    response = client.post(f"/api/v1/rider/deliveries/{order_id}/complete", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 409


def test_cod_order_can_be_completed_after_cash_is_collected(client):
    from app.db.session import get_db

    token = _register_and_login_rider(client, email="cod-then-complete@example.com", phone="9960000012")
    rider_id = _rider_id(client, token)
    admin_token = _make_admin(client, email="admin3-complete@example.com", phone="9960000097")
    _make_rider_online(client, token, admin_token, rider_id)

    db_gen = client.app.dependency_overrides[get_db]()
    db = next(db_gen)
    order = _seed_order(db)
    order_id = str(order.id)
    db.close()

    _advance_to_out_for_delivery(client, token, order_id)
    headers = {"Authorization": f"Bearer {token}"}
    collect = client.post(f"/api/v1/rider/deliveries/{order_id}/cod-collect", headers=headers)
    assert collect.status_code == 200

    complete = client.post(f"/api/v1/rider/deliveries/{order_id}/complete", headers=headers)
    assert complete.status_code == 200
    assert complete.json()["status"] == "delivered"


def test_cannot_complete_before_out_for_delivery(client):
    from app.db.session import get_db
    from app.models.order import Order, OrderStatus
    from app.services.orders import transition_order_status

    token = _register_and_login_rider(client, email="too-early-complete@example.com", phone="9960000013")
    rider_id = _rider_id(client, token)
    admin_token = _make_admin(client, email="admin4-complete@example.com", phone="9960000096")
    _make_rider_online(client, token, admin_token, rider_id)

    db_gen = client.app.dependency_overrides[get_db]()
    db = next(db_gen)
    order = _seed_order(db, payment_method="online")
    order_id = str(order.id)
    order_row = db.get(Order, order.id)
    transition_order_status(db, order_row, OrderStatus.CONFIRMED)
    transition_order_status(db, order_row, OrderStatus.PREPARING)
    transition_order_status(db, order_row, OrderStatus.READY_FOR_PICKUP)
    db.close()

    headers = {"Authorization": f"Bearer {token}"}
    client.post(f"/api/v1/rider/deliveries/{order_id}/accept", headers=headers)
    # Not picked up / started yet.
    response = client.post(f"/api/v1/rider/deliveries/{order_id}/complete", headers=headers)
    assert response.status_code == 409


def test_complete_twice_is_idempotent_and_does_not_double_credit_earnings(client):
    """Phase 28: a second completion call for an order already DELIVERED is
    a lost-response retry, not an invalid transition — it returns the same
    success state rather than a 409, and critically must not credit the
    rider's earnings ledger a second time."""
    from app.db.session import get_db

    token = _register_and_login_rider(client, email="double-complete@example.com", phone="9960000014")
    rider_id = _rider_id(client, token)
    admin_token = _make_admin(client, email="admin5-complete@example.com", phone="9960000095")
    _make_rider_online(client, token, admin_token, rider_id)

    db_gen = client.app.dependency_overrides[get_db]()
    db = next(db_gen)
    order = _seed_order(db, payment_method="online")
    order_id = str(order.id)
    db.close()

    _advance_to_out_for_delivery(client, token, order_id)
    headers = {"Authorization": f"Bearer {token}"}
    first = client.post(f"/api/v1/rider/deliveries/{order_id}/complete", headers=headers)
    assert first.status_code == 200
    second = client.post(f"/api/v1/rider/deliveries/{order_id}/complete", headers=headers)
    assert second.status_code == 200
    assert second.json()["status"] == "delivered"
    history_entries = [h for h in second.json()["status_history"] if h["status"] == "delivered"]
    assert len(history_entries) == 1

    earnings = client.get("/api/v1/rider/earnings", headers=headers).json()
    matching = [e for e in earnings if e["order_id"] == order_id]
    assert len(matching) == 1  # not credited twice


def test_another_riders_delivery_cannot_be_completed(client):
    from app.db.session import get_db

    token_a = _register_and_login_rider(client, email="complete-a@example.com", phone="9960000015")
    rider_a_id = _rider_id(client, token_a)
    token_b = _register_and_login_rider(client, email="complete-b@example.com", phone="9960000016")
    rider_b_id = _rider_id(client, token_b)
    admin_token = _make_admin(client, email="admin6-complete@example.com", phone="9960000094")
    _make_rider_online(client, token_a, admin_token, rider_a_id)
    _make_rider_online(client, token_b, admin_token, rider_b_id)

    db_gen = client.app.dependency_overrides[get_db]()
    db = next(db_gen)
    order = _seed_order(db, payment_method="online")
    order_id = str(order.id)
    db.close()

    _advance_to_out_for_delivery(client, token_a, order_id)
    response = client.post(
        f"/api/v1/rider/deliveries/{order_id}/complete", headers={"Authorization": f"Bearer {token_b}"}
    )
    assert response.status_code == 404


def test_completed_delivery_reflects_in_detail_view(client):
    from app.db.session import get_db

    token = _register_and_login_rider(client, email="complete-detail@example.com", phone="9960000017")
    rider_id = _rider_id(client, token)
    admin_token = _make_admin(client, email="admin7-complete@example.com", phone="9960000093")
    _make_rider_online(client, token, admin_token, rider_id)

    db_gen = client.app.dependency_overrides[get_db]()
    db = next(db_gen)
    order = _seed_order(db, payment_method="online")
    order_id = str(order.id)
    db.close()

    _advance_to_out_for_delivery(client, token, order_id)
    headers = {"Authorization": f"Bearer {token}"}
    client.post(f"/api/v1/rider/deliveries/{order_id}/complete", headers=headers)

    detail = client.get(f"/api/v1/rider/deliveries/{order_id}", headers=headers).json()
    assert detail["status"] == "delivered"
    assert detail["assignment_status"] == "DELIVERED"


def test_customer_and_restaurant_owner_cannot_complete_delivery(client):
    from app.db.session import get_db

    db_gen = client.app.dependency_overrides[get_db]()
    db = next(db_gen)
    customer = User(name="C", email="c-complete@example.com", phone="9960000051", password_hash=hash_password("x"), role=UserRole.CUSTOMER)
    owner = User(name="O", email="o-complete@example.com", phone="9960000052", password_hash=hash_password("x"), role=UserRole.RESTAURANT_OWNER)
    db.add_all([customer, owner])
    db.commit()
    customer_token = create_access_token(customer.id)
    owner_token = create_access_token(owner.id)
    db.close()

    fake_id = "00000000-0000-0000-0000-000000000000"
    assert client.post(f"/api/v1/rider/deliveries/{fake_id}/complete", headers={"Authorization": f"Bearer {customer_token}"}).status_code == 403
    assert client.post(f"/api/v1/rider/deliveries/{fake_id}/complete", headers={"Authorization": f"Bearer {owner_token}"}).status_code == 403


def test_unauthenticated_request_is_rejected(client):
    fake_id = "00000000-0000-0000-0000-000000000000"
    assert client.post(f"/api/v1/rider/deliveries/{fake_id}/complete").status_code == 401


def test_admin_assigned_order_can_still_be_completed(client):
    """An order that reached OUT_FOR_DELIVERY via the admin's direct
    assign_rider_to_order (never touching accept_delivery / DeliveryAssignment)
    should still be completable — the lazy _get_or_create_assignment fallback
    covers this, same as pickup/start."""
    from uuid import UUID as _UUID

    from app.db.session import get_db
    from app.models.order import OrderStatus
    from app.services.orders import assign_rider_to_order, transition_order_status

    token = _register_and_login_rider(client, email="admin-assigned-complete@example.com", phone="9960000018")
    rider_id = _rider_id(client, token)
    admin_token = _make_admin(client, email="admin8-complete@example.com", phone="9960000092")
    _make_rider_online(client, token, admin_token, rider_id)

    db_gen = client.app.dependency_overrides[get_db]()
    db = next(db_gen)
    order = _seed_order(db, payment_method="online")
    transition_order_status(db, order, OrderStatus.CONFIRMED)
    transition_order_status(db, order, OrderStatus.PREPARING)
    transition_order_status(db, order, OrderStatus.READY_FOR_PICKUP)
    assign_rider_to_order(db, order, _UUID(rider_id))
    transition_order_status(db, order, OrderStatus.PICKED_UP)
    transition_order_status(db, order, OrderStatus.OUT_FOR_DELIVERY)
    order_id = str(order.id)
    db.close()

    response = client.post(f"/api/v1/rider/deliveries/{order_id}/complete", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200
    assert response.json()["status"] == "delivered"


def test_smuggled_financial_and_identity_fields_in_the_request_body_are_ignored(client):
    """Integration Phase 9 — pickup/start/complete/cod-collect all take no
    request body at all (see their route signatures in
    app/api/v1/rider/deliveries.py): there is no field a rider could send
    to alter the order's price, restaurant, customer, payment amount, or
    the earning that gets credited. Sending one anyway must have zero
    effect — everything on the resulting order and earning ledger must
    still match the real, server-side values."""
    from app.db.session import get_db
    from app.models.rider_earning import RiderEarning

    token = _register_and_login_rider(client, email="smuggle-rider@example.com", phone="9960000020")
    rider_id = _rider_id(client, token)
    admin_token = _make_admin(client, email="admin-smuggle@example.com", phone="9960000091")
    _make_rider_online(client, token, admin_token, rider_id)

    db_gen = client.app.dependency_overrides[get_db]()
    db = next(db_gen)
    order = _seed_order(db, payment_method="cod")
    order_uuid = order.id
    order_id = str(order.id)
    real_total = str(order.total)
    real_delivery_fee = str(order.delivery_fee)
    real_restaurant_name = order.restaurant_name
    real_customer_name = order.customer_name
    real_user_id = str(order.user_id)
    db.close()

    from app.models.order import Order, OrderStatus
    from app.services.orders import transition_order_status

    db_gen2 = client.app.dependency_overrides[get_db]()
    db2 = next(db_gen2)
    order_row = db2.query(Order).filter(Order.id == order_uuid).first()
    transition_order_status(db2, order_row, OrderStatus.CONFIRMED)
    transition_order_status(db2, order_row, OrderStatus.PREPARING)
    transition_order_status(db2, order_row, OrderStatus.READY_FOR_PICKUP)
    db2.close()

    headers = {"Authorization": f"Bearer {token}"}
    tampered_body = {
        "total": "1.00",
        "subtotal": "1.00",
        "delivery_fee": "999.00",
        "amount": "999999.00",
        "earnings": "999999.00",
        "restaurant_name": "Hacked Restaurant",
        "restaurant_id": "00000000-0000-0000-0000-000000000000",
        "customer_name": "Hacked Customer",
        "user_id": "00000000-0000-0000-0000-000000000000",
        "payment_status": "paid",
        "is_paid": True,
        "status": "delivered",
    }

    assert client.post(f"/api/v1/rider/deliveries/{order_id}/accept", headers=headers, json=tampered_body).status_code == 200
    assert client.post(f"/api/v1/rider/deliveries/{order_id}/pickup", headers=headers, json=tampered_body).status_code == 200
    assert client.post(f"/api/v1/rider/deliveries/{order_id}/start", headers=headers, json=tampered_body).status_code == 200
    collect = client.post(f"/api/v1/rider/deliveries/{order_id}/cod-collect", headers=headers, json=tampered_body)
    assert collect.status_code == 200
    assert collect.json()["amount"] == real_total
    complete = client.post(f"/api/v1/rider/deliveries/{order_id}/complete", headers=headers, json=tampered_body)
    assert complete.status_code == 200

    body = complete.json()
    assert body["total"] == real_total
    assert body["delivery_fee"] == real_delivery_fee
    assert body["restaurant_name"] == real_restaurant_name
    assert body["customer_name"] == real_customer_name
    assert body["user_id"] == real_user_id
    assert body["rider_id"] == rider_id

    db_gen3 = client.app.dependency_overrides[get_db]()
    db3 = next(db_gen3)
    earning = db3.query(RiderEarning).filter(RiderEarning.order_id == order_uuid).one()
    assert str(earning.amount) == real_delivery_fee
    assert str(earning.rider_id) == rider_id
    db3.close()
