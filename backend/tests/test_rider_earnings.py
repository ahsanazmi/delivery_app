"""Rider Portal — Phase 19: Rider Earnings."""

from decimal import Decimal

from app.core.security import create_access_token, hash_password
from app.models.user import User, UserRole


def _register_and_login_rider(client, email="rider-earnings@example.com", phone="9980000010", name="Ravi Kumar"):
    client.post(
        "/api/v1/auth/register",
        json={"name": name, "email": email, "password": "secure-pass-123", "phone": phone, "role": "RIDER"},
    )
    login = client.post("/api/v1/auth/login", json={"email": email, "password": "secure-pass-123"})
    return login.json()["access_token"]


def _rider_id(client, token):
    return client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"}).json()["id"]


def _make_admin(client, email="admin-earnings@example.com", phone="9980000099"):
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


def _seed_order(db, delivery_fee=Decimal("45.00")):
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
        minimum_order=Decimal("0.00"), delivery_fee=delivery_fee,
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
    order = create_order(db, customer, address.id, payment_method="online")
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


def test_completing_a_delivery_credits_a_delivery_fee_earning(client):
    from app.db.session import get_db

    token = _register_and_login_rider(client)
    rider_id = _rider_id(client, token)
    admin_token = _make_admin(client)
    _make_rider_online(client, token, admin_token, rider_id)

    db_gen = client.app.dependency_overrides[get_db]()
    db = next(db_gen)
    order = _seed_order(db, delivery_fee=Decimal("45.00"))
    order_id = str(order.id)
    db.close()

    _complete_full_delivery(client, token, order_id)

    headers = {"Authorization": f"Bearer {token}"}
    earnings = client.get("/api/v1/rider/earnings", headers=headers)
    assert earnings.status_code == 200
    rows = earnings.json()
    assert len(rows) == 1
    assert rows[0]["order_id"] == order_id
    assert rows[0]["earning_type"] == "DELIVERY_FEE"
    assert Decimal(rows[0]["amount"]) == Decimal("45.00")


def test_earnings_list_is_scoped_to_the_requesting_rider(client):
    from app.db.session import get_db

    token_a = _register_and_login_rider(client, email="earnings-a@example.com", phone="9980000011")
    rider_a_id = _rider_id(client, token_a)
    token_b = _register_and_login_rider(client, email="earnings-b@example.com", phone="9980000012")
    rider_b_id = _rider_id(client, token_b)
    admin_token = _make_admin(client, email="admin2-earnings@example.com", phone="9980000098")
    _make_rider_online(client, token_a, admin_token, rider_a_id)
    _make_rider_online(client, token_b, admin_token, rider_b_id)

    db_gen = client.app.dependency_overrides[get_db]()
    db = next(db_gen)
    order = _seed_order(db)
    order_id = str(order.id)
    db.close()

    _complete_full_delivery(client, token_a, order_id)

    b_earnings = client.get("/api/v1/rider/earnings", headers={"Authorization": f"Bearer {token_b}"}).json()
    assert b_earnings == []


def test_earnings_summary_reflects_completed_deliveries(client):
    from app.db.session import get_db

    token = _register_and_login_rider(client, email="summary-earnings@example.com", phone="9980000013")
    rider_id = _rider_id(client, token)
    admin_token = _make_admin(client, email="admin3-earnings@example.com", phone="9980000097")
    _make_rider_online(client, token, admin_token, rider_id)

    db_gen = client.app.dependency_overrides[get_db]()
    db = next(db_gen)
    order1 = _seed_order(db, delivery_fee=Decimal("30.00"))
    order1_id = str(order1.id)
    order2 = _seed_order(db, delivery_fee=Decimal("50.00"))
    order2_id = str(order2.id)
    db.close()

    _complete_full_delivery(client, token, order1_id)
    _complete_full_delivery(client, token, order2_id)

    headers = {"Authorization": f"Bearer {token}"}
    summary = client.get("/api/v1/rider/earnings/summary", headers=headers)
    assert summary.status_code == 200
    body = summary.json()

    assert Decimal(body["today"]["delivery_fee"]) == Decimal("80.00")
    assert Decimal(body["today"]["total"]) == Decimal("80.00")
    assert Decimal(body["week"]["total"]) == Decimal("80.00")
    assert Decimal(body["month"]["total"]) == Decimal("80.00")
    assert body["total_deliveries"] == 2
    assert Decimal(body["average_earning"]) == Decimal("40.00")
    # No incentive/bonus/adjustment activity has ever been recorded.
    assert Decimal(body["today"]["incentive"]) == Decimal("0.00")
    assert Decimal(body["today"]["bonus"]) == Decimal("0.00")
    assert Decimal(body["today"]["adjustment"]) == Decimal("0.00")


def test_earnings_summary_is_zero_for_a_rider_with_no_deliveries(client):
    token = _register_and_login_rider(client, email="no-deliveries-earnings@example.com", phone="9980000014")
    headers = {"Authorization": f"Bearer {token}"}
    summary = client.get("/api/v1/rider/earnings/summary", headers=headers).json()

    assert Decimal(summary["today"]["total"]) == Decimal("0.00")
    assert Decimal(summary["week"]["total"]) == Decimal("0.00")
    assert Decimal(summary["month"]["total"]) == Decimal("0.00")
    assert summary["total_deliveries"] == 0
    assert Decimal(summary["average_earning"]) == Decimal("0.00")


def test_incentive_bonus_and_adjustment_types_are_tracked_and_summed(client):
    """The ledger's shape supports all four earning types even though only
    DELIVERY_FEE is producible via the current app flows (Phase 19 only asks
    for the rider-facing read endpoints) — insert the other three directly
    to prove the summary correctly tracks and sums each category."""
    from app.db.session import get_db
    from app.models.rider_earning import EarningType, RiderEarning
    from uuid import UUID as _UUID

    token = _register_and_login_rider(client, email="ledger-types@example.com", phone="9980000015")
    rider_id = _rider_id(client, token)

    db_gen = client.app.dependency_overrides[get_db]()
    db = next(db_gen)
    db.add_all([
        RiderEarning(rider_id=_UUID(rider_id), earning_type=EarningType.INCENTIVE, amount=Decimal("15.00")),
        RiderEarning(rider_id=_UUID(rider_id), earning_type=EarningType.BONUS, amount=Decimal("25.00")),
        RiderEarning(rider_id=_UUID(rider_id), earning_type=EarningType.ADJUSTMENT, amount=Decimal("-5.00")),
    ])
    db.commit()
    db.close()

    headers = {"Authorization": f"Bearer {token}"}
    summary = client.get("/api/v1/rider/earnings/summary", headers=headers).json()
    assert Decimal(summary["today"]["incentive"]) == Decimal("15.00")
    assert Decimal(summary["today"]["bonus"]) == Decimal("25.00")
    assert Decimal(summary["today"]["adjustment"]) == Decimal("-5.00")
    assert Decimal(summary["today"]["total"]) == Decimal("35.00")

    earnings = client.get("/api/v1/rider/earnings", headers=headers).json()
    assert len(earnings) == 3
    assert {row["earning_type"] for row in earnings} == {"INCENTIVE", "BONUS", "ADJUSTMENT"}


def test_customer_and_restaurant_owner_cannot_access_rider_earnings(client):
    from app.db.session import get_db

    db_gen = client.app.dependency_overrides[get_db]()
    db = next(db_gen)
    customer = User(name="C", email="c-earnings@example.com", phone="9980000051", password_hash=hash_password("x"), role=UserRole.CUSTOMER)
    owner = User(name="O", email="o-earnings@example.com", phone="9980000052", password_hash=hash_password("x"), role=UserRole.RESTAURANT_OWNER)
    db.add_all([customer, owner])
    db.commit()
    customer_token = create_access_token(customer.id)
    owner_token = create_access_token(owner.id)
    db.close()

    for token in (customer_token, owner_token):
        assert client.get("/api/v1/rider/earnings", headers={"Authorization": f"Bearer {token}"}).status_code == 403
        assert client.get("/api/v1/rider/earnings/summary", headers={"Authorization": f"Bearer {token}"}).status_code == 403


def test_unauthenticated_request_is_rejected(client):
    assert client.get("/api/v1/rider/earnings").status_code == 401
    assert client.get("/api/v1/rider/earnings/summary").status_code == 401
