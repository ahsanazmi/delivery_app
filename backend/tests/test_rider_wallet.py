"""Rider Portal — Phase 20: Rider Wallet / Settlement."""

from decimal import Decimal

from app.core.security import create_access_token, hash_password
from app.models.user import User, UserRole


def _register_and_login_rider(client, email="rider-wallet@example.com", phone="9990000010", name="Ravi Kumar"):
    client.post(
        "/api/v1/auth/register",
        json={"name": name, "email": email, "password": "secure-pass-123", "phone": phone, "role": "RIDER"},
    )
    login = client.post("/api/v1/auth/login", json={"email": email, "password": "secure-pass-123"})
    return login.json()["access_token"]


def _rider_id(client, token):
    return client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"}).json()["id"]


def _make_admin(client, email="admin-wallet@example.com", phone="9990000099"):
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


def _seed_order(db, payment_method="online", delivery_fee=Decimal("40.00"), item_price=Decimal("100.00")):
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
    product = Product(restaurant_id=restaurant.id, name="Item", price=item_price)
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


def test_wallet_is_zero_for_a_new_rider(client):
    token = _register_and_login_rider(client)
    headers = {"Authorization": f"Bearer {token}"}
    wallet = client.get("/api/v1/rider/wallet", headers=headers)
    assert wallet.status_code == 200
    body = wallet.json()
    assert Decimal(body["total_earnings"]) == Decimal("0.00")
    assert Decimal(body["total_cod_collected"]) == Decimal("0.00")
    assert Decimal(body["total_settled"]) == Decimal("0.00")
    assert Decimal(body["wallet_balance"]) == Decimal("0.00")
    assert Decimal(body["settlement_due"]) == Decimal("0.00")


def test_online_order_only_credits_earnings_not_cod(client):
    """An online-paid order never touches COD collection at all — the
    wallet balance should equal earnings exactly."""
    from app.db.session import get_db

    token = _register_and_login_rider(client, email="online-wallet@example.com", phone="9990000011")
    rider_id = _rider_id(client, token)
    admin_token = _make_admin(client, email="admin2-wallet@example.com", phone="9990000098")
    _make_rider_online(client, token, admin_token, rider_id)

    db_gen = client.app.dependency_overrides[get_db]()
    db = next(db_gen)
    order = _seed_order(db, payment_method="online", delivery_fee=Decimal("40.00"))
    order_id = str(order.id)
    db.close()

    _advance_to_out_for_delivery(client, token, order_id)
    headers = {"Authorization": f"Bearer {token}"}
    assert client.post(f"/api/v1/rider/deliveries/{order_id}/complete", headers=headers).status_code == 200

    wallet = client.get("/api/v1/rider/wallet", headers=headers).json()
    assert Decimal(wallet["total_earnings"]) == Decimal("40.00")
    assert Decimal(wallet["total_cod_collected"]) == Decimal("0.00")
    assert Decimal(wallet["wallet_balance"]) == Decimal("40.00")


def test_cod_collected_is_not_treated_as_earnings(client):
    """The critical rule: COD cash collected must reduce the wallet
    balance, never add to it. A rider who delivers a 175.50 COD order (40
    delivery fee + 135.50 item cost) earns 40 but is now holding 175.50 of
    the platform's/restaurant's money — net wallet balance must reflect
    that debt, not double as extra income."""
    from app.db.session import get_db

    token = _register_and_login_rider(client, email="cod-wallet@example.com", phone="9990000012")
    rider_id = _rider_id(client, token)
    admin_token = _make_admin(client, email="admin3-wallet@example.com", phone="9990000097")
    _make_rider_online(client, token, admin_token, rider_id)

    db_gen = client.app.dependency_overrides[get_db]()
    db = next(db_gen)
    order = _seed_order(db, payment_method="cod", delivery_fee=Decimal("40.00"), item_price=Decimal("135.50"))
    order_id = str(order.id)
    expected_total = order.total
    db.close()

    _advance_to_out_for_delivery(client, token, order_id)
    headers = {"Authorization": f"Bearer {token}"}
    assert client.post(f"/api/v1/rider/deliveries/{order_id}/cod-collect", headers=headers).status_code == 200
    assert client.post(f"/api/v1/rider/deliveries/{order_id}/complete", headers=headers).status_code == 200

    wallet = client.get("/api/v1/rider/wallet", headers=headers).json()
    assert Decimal(wallet["total_earnings"]) == Decimal("40.00")
    assert Decimal(wallet["total_cod_collected"]) == expected_total
    # The rider is now net negative: they hold more of the platform's money
    # than they've earned, so they owe the difference back.
    assert Decimal(wallet["wallet_balance"]) == Decimal("40.00") - expected_total
    assert Decimal(wallet["settlement_due"]) == Decimal("40.00") - expected_total


def test_settlements_move_the_wallet_balance_toward_zero(client):
    """Settlements aren't creatable via any endpoint yet (Phase 20 only asks
    to track them) — inserted directly here, the same pattern used for
    Phase 19's INCENTIVE/BONUS/ADJUSTMENT types."""
    from uuid import UUID as _UUID

    from app.db.session import get_db
    from app.models.rider_settlement import RiderSettlement, SettlementType

    token = _register_and_login_rider(client, email="settlement-wallet@example.com", phone="9990000013")
    rider_id = _rider_id(client, token)
    admin_token = _make_admin(client, email="admin4-wallet@example.com", phone="9990000096")
    _make_rider_online(client, token, admin_token, rider_id)

    db_gen = client.app.dependency_overrides[get_db]()
    db = next(db_gen)
    order = _seed_order(db, payment_method="cod", delivery_fee=Decimal("40.00"), item_price=Decimal("60.00"))
    order_id = str(order.id)
    db.close()

    _advance_to_out_for_delivery(client, token, order_id)
    headers = {"Authorization": f"Bearer {token}"}
    client.post(f"/api/v1/rider/deliveries/{order_id}/cod-collect", headers=headers)
    client.post(f"/api/v1/rider/deliveries/{order_id}/complete", headers=headers)

    before = client.get("/api/v1/rider/wallet", headers=headers).json()
    balance_before = Decimal(before["wallet_balance"])
    assert balance_before < Decimal("0.00")  # collected more (100) than earned (40)

    # The rider remits the excess COD cash back to the platform.
    db_gen2 = client.app.dependency_overrides[get_db]()
    db2 = next(db_gen2)
    db2.add(RiderSettlement(rider_id=_UUID(rider_id), settlement_type=SettlementType.REMITTANCE, amount=abs(balance_before)))
    db2.commit()
    db2.close()

    after = client.get("/api/v1/rider/wallet", headers=headers).json()
    assert Decimal(after["wallet_balance"]) == Decimal("0.00")
    assert Decimal(after["settlement_due"]) == Decimal("0.00")
    assert Decimal(after["total_settled"]) == abs(balance_before)

    settlements = client.get("/api/v1/rider/wallet/settlements", headers=headers).json()
    assert len(settlements) == 1
    assert settlements[0]["settlement_type"] == "REMITTANCE"


def test_payout_settlement_reduces_a_positive_balance(client):
    from uuid import UUID as _UUID

    from app.db.session import get_db
    from app.models.rider_settlement import RiderSettlement, SettlementType

    token = _register_and_login_rider(client, email="payout-wallet@example.com", phone="9990000014")
    rider_id = _rider_id(client, token)
    admin_token = _make_admin(client, email="admin5-wallet@example.com", phone="9990000095")
    _make_rider_online(client, token, admin_token, rider_id)

    db_gen = client.app.dependency_overrides[get_db]()
    db = next(db_gen)
    order = _seed_order(db, payment_method="online", delivery_fee=Decimal("50.00"))
    order_id = str(order.id)
    db.close()

    _advance_to_out_for_delivery(client, token, order_id)
    headers = {"Authorization": f"Bearer {token}"}
    client.post(f"/api/v1/rider/deliveries/{order_id}/complete", headers=headers)

    db_gen2 = client.app.dependency_overrides[get_db]()
    db2 = next(db_gen2)
    db2.add(RiderSettlement(rider_id=_UUID(rider_id), settlement_type=SettlementType.PAYOUT, amount=Decimal("50.00")))
    db2.commit()
    db2.close()

    wallet = client.get("/api/v1/rider/wallet", headers=headers).json()
    assert Decimal(wallet["wallet_balance"]) == Decimal("0.00")
    assert Decimal(wallet["total_settled"]) == Decimal("50.00")
    assert Decimal(wallet["total_earnings"]) == Decimal("50.00")


def test_wallet_is_scoped_to_the_requesting_rider(client):
    from app.db.session import get_db

    token_a = _register_and_login_rider(client, email="wallet-a@example.com", phone="9990000015")
    rider_a_id = _rider_id(client, token_a)
    token_b = _register_and_login_rider(client, email="wallet-b@example.com", phone="9990000016")
    rider_b_id = _rider_id(client, token_b)
    admin_token = _make_admin(client, email="admin6-wallet@example.com", phone="9990000094")
    _make_rider_online(client, token_a, admin_token, rider_a_id)
    _make_rider_online(client, token_b, admin_token, rider_b_id)

    db_gen = client.app.dependency_overrides[get_db]()
    db = next(db_gen)
    order = _seed_order(db, payment_method="online", delivery_fee=Decimal("40.00"))
    order_id = str(order.id)
    db.close()

    _advance_to_out_for_delivery(client, token_a, order_id)
    client.post(f"/api/v1/rider/deliveries/{order_id}/complete", headers={"Authorization": f"Bearer {token_a}"})

    wallet_b = client.get("/api/v1/rider/wallet", headers={"Authorization": f"Bearer {token_b}"}).json()
    assert Decimal(wallet_b["total_earnings"]) == Decimal("0.00")
    assert Decimal(wallet_b["wallet_balance"]) == Decimal("0.00")


def test_customer_and_restaurant_owner_cannot_access_rider_wallet(client):
    from app.db.session import get_db

    db_gen = client.app.dependency_overrides[get_db]()
    db = next(db_gen)
    customer = User(name="C", email="c-wallet@example.com", phone="9990000051", password_hash=hash_password("x"), role=UserRole.CUSTOMER)
    owner = User(name="O", email="o-wallet@example.com", phone="9990000052", password_hash=hash_password("x"), role=UserRole.RESTAURANT_OWNER)
    db.add_all([customer, owner])
    db.commit()
    customer_token = create_access_token(customer.id)
    owner_token = create_access_token(owner.id)
    db.close()

    for token in (customer_token, owner_token):
        assert client.get("/api/v1/rider/wallet", headers={"Authorization": f"Bearer {token}"}).status_code == 403
        assert client.get("/api/v1/rider/wallet/settlements", headers={"Authorization": f"Bearer {token}"}).status_code == 403


def test_unauthenticated_request_is_rejected(client):
    assert client.get("/api/v1/rider/wallet").status_code == 401
    assert client.get("/api/v1/rider/wallet/settlements").status_code == 401
