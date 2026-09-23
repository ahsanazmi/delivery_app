"""Admin Portal — Phase 3: Customer Management."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from app.core.security import create_access_token, hash_password
from app.db.session import get_db
from app.models.admin_audit_log import AdminAuditLog
from app.models.order import Order, OrderStatus
from app.models.user import User, UserRole

CUSTOMERS_URL = "/api/v1/admin/customers"


def _db(client):
    return next(client.app.dependency_overrides[get_db]())


def _make_user(db, *, name, email, phone, role=UserRole.CUSTOMER, is_active=True):
    user = User(name=name, email=email, phone=phone, password_hash=hash_password("x"), role=role, is_active=is_active)
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _admin_headers(db):
    admin = _make_user(db, name="Admin", email="admin-p3@example.com", phone="9500000001", role=UserRole.ADMIN)
    token = create_access_token(admin.id)
    return {"Authorization": f"Bearer {token}"}


def _admin_headers_with_admin(db):
    admin = _make_user(db, name="Admin", email="admin-p23@example.com", phone="9500000002", role=UserRole.ADMIN)
    token = create_access_token(admin.id)
    return admin, {"Authorization": f"Bearer {token}"}


def _make_order(db, *, user_id, status, total, order_number):
    order = Order(
        user_id=user_id,
        customer_name="Some Customer",
        customer_email="customer@example.com",
        restaurant_id="rest-1",
        restaurant_name="Test Restaurant",
        order_number=order_number,
        status=status,
        subtotal=total,
        delivery_fee=Decimal("0.00"),
        total=total,
        payment_method="cod",
        address_line="123 Main St",
        city="Testville",
        state="TS",
        postal_code="123456",
        latitude=Decimal("12.9716"),
        longitude=Decimal("77.5946"),
    )
    db.add(order)
    db.commit()
    db.refresh(order)
    return order


def test_list_customers_requires_admin(client):
    db = _db(client)
    customer = _make_user(db, name="Someone", email="someone-p3@example.com", phone="9500000010")
    token = create_access_token(customer.id)
    response = client.get(CUSTOMERS_URL, headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 403

    response = client.get(CUSTOMERS_URL)
    assert response.status_code == 401


def test_list_customers_returns_order_stats_and_pagination(client):
    db = _db(client)
    headers = _admin_headers(db)

    active = _make_user(db, name="Active Cust", email="active-p3@example.com", phone="9500000020")
    _make_user(db, name="Suspended Cust", email="suspended-p3@example.com", phone="9500000021", is_active=False)

    _make_order(db, user_id=active.id, status=OrderStatus.DELIVERED, total=Decimal("100.00"), order_number="ORD-P3-1")
    _make_order(db, user_id=active.id, status=OrderStatus.DELIVERED, total=Decimal("50.00"), order_number="ORD-P3-2")
    _make_order(db, user_id=active.id, status=OrderStatus.CANCELLED, total=Decimal("999.00"), order_number="ORD-P3-3")

    response = client.get(CUSTOMERS_URL, headers=headers, params={"page": 1, "limit": 20})
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 2
    assert body["page"] == 1
    assert body["limit"] == 20

    by_email = {item["email"]: item for item in body["items"]}
    assert by_email["active-p3@example.com"]["status"] == "ACTIVE"
    assert by_email["active-p3@example.com"]["order_count"] == 3
    assert Decimal(by_email["active-p3@example.com"]["total_spending"]) == Decimal("150.00")
    assert by_email["suspended-p3@example.com"]["status"] == "SUSPENDED"
    assert by_email["suspended-p3@example.com"]["order_count"] == 0
    assert Decimal(by_email["suspended-p3@example.com"]["total_spending"]) == Decimal("0.00")


def test_list_customers_search_filters_by_name_email_phone(client):
    db = _db(client)
    headers = _admin_headers(db)
    _make_user(db, name="Findable Fred", email="fred-p3@example.com", phone="9500000030")
    _make_user(db, name="Other Person", email="other-p3@example.com", phone="9500000031")

    response = client.get(CUSTOMERS_URL, headers=headers, params={"search": "Fred"})
    assert response.status_code == 200
    items = response.json()["items"]
    assert len(items) == 1
    assert items[0]["name"] == "Findable Fred"

    response = client.get(CUSTOMERS_URL, headers=headers, params={"search": "9500000031"})
    assert response.json()["items"][0]["name"] == "Other Person"


def test_list_customers_status_filter(client):
    db = _db(client)
    headers = _admin_headers(db)
    _make_user(db, name="Active One", email="active-filter-p3@example.com", phone="9500000040", is_active=True)
    _make_user(db, name="Suspended One", email="suspended-filter-p3@example.com", phone="9500000041", is_active=False)

    response = client.get(CUSTOMERS_URL, headers=headers, params={"status": "SUSPENDED"})
    items = response.json()["items"]
    assert len(items) == 1
    assert items[0]["name"] == "Suspended One"


def test_list_customers_date_filter(client):
    db = _db(client)
    headers = _admin_headers(db)
    old_customer = _make_user(db, name="Old Cust", email="old-p3@example.com", phone="9500000050")
    db.query(User).filter(User.id == old_customer.id).update(
        {User.created_at: datetime.now(UTC) - timedelta(days=10)}
    )
    db.commit()
    _make_user(db, name="New Cust", email="new-p3@example.com", phone="9500000051")

    cutoff = (datetime.now(UTC) - timedelta(days=1)).date().isoformat()
    response = client.get(CUSTOMERS_URL, headers=headers, params={"registered_after": cutoff})
    names = [item["name"] for item in response.json()["items"]]
    assert "New Cust" in names
    assert "Old Cust" not in names


def test_list_customers_excludes_non_customer_roles(client):
    db = _db(client)
    headers = _admin_headers(db)
    _make_user(db, name="Rider Person", email="rider-p3@example.com", phone="9500000060", role=UserRole.RIDER)
    _make_user(db, name="Owner Person", email="owner-p3@example.com", phone="9500000061", role=UserRole.RESTAURANT_OWNER)

    response = client.get(CUSTOMERS_URL, headers=headers)
    names = [item["name"] for item in response.json()["items"]]
    assert "Rider Person" not in names
    assert "Owner Person" not in names


def test_get_customer_detail_includes_recent_orders(client):
    db = _db(client)
    headers = _admin_headers(db)
    customer = _make_user(db, name="Detail Cust", email="detail-p3@example.com", phone="9500000070")
    order = _make_order(db, user_id=customer.id, status=OrderStatus.DELIVERED, total=Decimal("75.00"), order_number="ORD-P3-DETAIL")

    response = client.get(f"{CUSTOMERS_URL}/{customer.id}", headers=headers)
    assert response.status_code == 200
    body = response.json()
    assert body["name"] == "Detail Cust"
    assert body["order_count"] == 1
    assert Decimal(body["total_spending"]) == Decimal("75.00")
    assert len(body["recent_orders"]) == 1
    assert body["recent_orders"][0]["id"] == str(order.id)


def test_get_customer_detail_404_for_missing_or_wrong_role(client):
    db = _db(client)
    headers = _admin_headers(db)
    rider = _make_user(db, name="Rider Not Customer", email="rider-404-p3@example.com", phone="9500000080", role=UserRole.RIDER)

    response = client.get(f"{CUSTOMERS_URL}/{rider.id}", headers=headers)
    assert response.status_code == 404

    response = client.get(f"{CUSTOMERS_URL}/00000000-0000-0000-0000-000000000000", headers=headers)
    assert response.status_code == 404


def test_admin_can_suspend_and_reactivate_customer(client):
    db = _db(client)
    admin, headers = _admin_headers_with_admin(db)
    customer = _make_user(db, name="Togglable Cust", email="toggle-p3@example.com", phone="9500000090")

    suspend = client.post(f"{CUSTOMERS_URL}/{customer.id}/suspend", headers=headers, json={"reason": "Fraudulent orders"})
    assert suspend.status_code == 200
    assert suspend.json()["status"] == "SUSPENDED"

    db.refresh(customer)
    assert customer.is_active is False

    # Validates current state — suspending an already-suspended customer is a 409.
    assert client.post(f"{CUSTOMERS_URL}/{customer.id}/suspend", headers=headers, json={"reason": "again"}).status_code == 409

    reactivate = client.post(f"{CUSTOMERS_URL}/{customer.id}/activate", headers=headers, json={"reason": "Appeal accepted"})
    assert reactivate.status_code == 200
    assert reactivate.json()["status"] == "ACTIVE"

    entries = db.query(AdminAuditLog).filter(AdminAuditLog.target_id == str(customer.id)).order_by(AdminAuditLog.created_at).all()
    assert [e.action for e in entries] == ["customer.suspend", "customer.activate"]
    assert entries[0].admin_id == admin.id
    assert entries[0].reason == "Fraudulent orders"


def test_suspend_requires_a_reason(client):
    db = _db(client)
    _, headers = _admin_headers_with_admin(db)
    customer = _make_user(db, name="No Reason Cust", email="noreason-p3@example.com", phone="9500000094")

    assert client.post(f"{CUSTOMERS_URL}/{customer.id}/suspend", headers=headers, json={}).status_code == 422
    assert client.post(f"{CUSTOMERS_URL}/{customer.id}/suspend", headers=headers, json={"reason": ""}).status_code == 422


def test_old_generic_patch_route_no_longer_exists(client):
    db = _db(client)
    _, headers = _admin_headers_with_admin(db)
    customer = _make_user(db, name="Legacy Cust", email="legacy-p3@example.com", phone="9500000095")

    response = client.patch(f"{CUSTOMERS_URL}/{customer.id}", headers=headers, json={"status": "SUSPENDED"})
    assert response.status_code == 405


def test_suspended_customer_is_locked_out_immediately(client):
    db = _db(client)
    _, headers = _admin_headers_with_admin(db)
    customer = _make_user(db, name="Locked Cust", email="locked-p3@example.com", phone="9500000091")
    customer_token = create_access_token(customer.id)
    customer_headers = {"Authorization": f"Bearer {customer_token}"}

    assert client.get("/api/v1/auth/me", headers=customer_headers).status_code == 200

    client.post(f"{CUSTOMERS_URL}/{customer.id}/suspend", headers=headers, json={"reason": "Locked out test"})

    response = client.get("/api/v1/auth/me", headers=customer_headers)
    assert response.status_code in (401, 403)


def test_non_admin_cannot_update_customer_status(client):
    db = _db(client)
    customer = _make_user(db, name="Victim Cust", email="victim-p3@example.com", phone="9500000092")
    other_customer = _make_user(db, name="Attacker Cust", email="attacker-p3@example.com", phone="9500000093")
    attacker_token = create_access_token(other_customer.id)

    response = client.post(
        f"{CUSTOMERS_URL}/{customer.id}/suspend",
        headers={"Authorization": f"Bearer {attacker_token}"},
        json={"reason": "attack"},
    )
    assert response.status_code == 403
