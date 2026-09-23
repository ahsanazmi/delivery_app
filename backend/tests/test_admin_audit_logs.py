"""Admin Portal — Phase 21: Audit Logs.

Read-only surface over the AdminAuditLog table Phase 11 introduced (order
cancel/reassign) and Phase 14 also writes to (COD settlement). This phase
adds no new writer of its own — it exposes what already gets recorded,
plus a new ip_address column captured going forward on every write.
"""

import uuid
from decimal import Decimal

from app.core.security import create_access_token, hash_password
from app.db.session import get_db
from app.models.admin_audit_log import AdminAuditLog
from app.models.order import Order, OrderStatus
from app.models.user import User, UserRole

AUDIT_LOGS_URL = "/api/v1/admin/audit-logs"
ORDERS_URL = "/api/v1/admin/orders"


def _db(client):
    return next(client.app.dependency_overrides[get_db]())


def _make_user(db, *, name, email, phone, role):
    user = User(name=name, email=email, phone=phone, password_hash=hash_password("x"), role=role)
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _admin_headers(db, suffix="p21"):
    admin = _make_user(db, name="Admin", email=f"admin-{suffix}-{uuid.uuid4().hex[:8]}@example.com", phone=f"73{uuid.uuid4().hex[:8]}", role=UserRole.ADMIN)
    return admin, {"Authorization": f"Bearer {create_access_token(admin.id)}"}


def _make_order(db, *, status=OrderStatus.PLACED):
    order = Order(
        user_id=uuid.uuid4(), customer_name="Cust", customer_email="cust@example.com",
        restaurant_id="rest-1", restaurant_name="Some Restaurant",
        order_number=f"ORD-{uuid.uuid4().hex[:20]}", status=status,
        subtotal=Decimal("100.00"), delivery_fee=Decimal("30.00"), total=Decimal("130.00"),
        payment_method="cod", address_line="123 Main St", city="Testville", postal_code="123456",
    )
    db.add(order)
    db.commit()
    db.refresh(order)
    return order


def test_audit_log_endpoints_require_admin(client):
    db = _db(client)
    customer = _make_user(db, name="Not Admin", email="not-admin-p21@example.com", phone="7300000001", role=UserRole.CUSTOMER)
    headers = {"Authorization": f"Bearer {create_access_token(customer.id)}"}

    assert client.get(AUDIT_LOGS_URL, headers=headers).status_code == 403
    assert client.get(AUDIT_LOGS_URL).status_code == 401
    assert client.get(f"{AUDIT_LOGS_URL}/{uuid.uuid4()}", headers=headers).status_code == 403
    assert client.get(f"{AUDIT_LOGS_URL}/{uuid.uuid4()}").status_code == 401


def test_no_mutation_routes_exist(client):
    db = _db(client)
    _, headers = _admin_headers(db)
    assert client.post(AUDIT_LOGS_URL, headers=headers, json={}).status_code == 405
    assert client.patch(f"{AUDIT_LOGS_URL}/{uuid.uuid4()}", headers=headers, json={}).status_code == 405
    assert client.delete(f"{AUDIT_LOGS_URL}/{uuid.uuid4()}", headers=headers).status_code == 405


def test_order_cancel_creates_a_listable_audit_log_entry_with_ip_address(client):
    db = _db(client)
    admin, headers = _admin_headers(db)
    order = _make_order(db)

    response = client.post(f"{ORDERS_URL}/{order.id}/cancel", headers=headers, json={"reason": "Customer requested via phone"})
    assert response.status_code == 200

    listed = client.get(AUDIT_LOGS_URL, headers=headers).json()
    assert listed["total"] == 1
    entry = listed["items"][0]
    assert entry["admin_id"] == str(admin.id)
    assert entry["admin_name"] == admin.name
    assert entry["action"] == "order.cancel"
    assert entry["entity_type"] == "order"
    assert entry["entity_id"] == str(order.id)
    assert entry["reason"] == "Customer requested via phone"
    assert entry["ip_address"]

    db_entry = db.query(AdminAuditLog).filter(AdminAuditLog.target_id == str(order.id)).one()
    detail = client.get(f"{AUDIT_LOGS_URL}/{db_entry.id}", headers=headers).json()
    assert detail["old_value"] == "placed"
    assert detail["new_value"] == "cancelled"
    assert detail["reason"] == "Customer requested via phone"


def test_detail_404_for_nonexistent_entry(client):
    db = _db(client)
    _, headers = _admin_headers(db)
    assert client.get(f"{AUDIT_LOGS_URL}/{uuid.uuid4()}", headers=headers).status_code == 404


def test_list_filters_by_admin_action_and_entity(client):
    db = _db(client)
    admin_a, headers_a = _admin_headers(db, "a")
    _, headers_b = _admin_headers(db, "b")

    order_a = _make_order(db)
    order_b = _make_order(db)
    client.post(f"{ORDERS_URL}/{order_a.id}/cancel", headers=headers_a, json={"reason": "By admin A"})
    client.post(f"{ORDERS_URL}/{order_b.id}/cancel", headers=headers_b, json={"reason": "By admin B"})

    by_admin = client.get(f"{AUDIT_LOGS_URL}?admin_id={admin_a.id}", headers=headers_a).json()
    assert by_admin["total"] == 1
    assert by_admin["items"][0]["reason"] == "By admin A"

    by_action = client.get(f"{AUDIT_LOGS_URL}?action=order.cancel", headers=headers_a).json()
    assert by_action["total"] == 2

    by_entity = client.get(f"{AUDIT_LOGS_URL}?entity_type=order&entity_id={order_b.id}", headers=headers_a).json()
    assert by_entity["total"] == 1
    assert by_entity["items"][0]["entity_id"] == str(order_b.id)


def test_no_sensitive_fields_ever_appear_in_the_response(client):
    """The audit log stores short status/id snapshots (order status values,
    rider ids, amounts) — never passwords, tokens, or full request bodies.
    This test proves the API response for a real entry never leaks the
    acting admin's password hash or any bearer token."""
    db = _db(client)
    admin, headers = _admin_headers(db)
    order = _make_order(db)
    client.post(f"{ORDERS_URL}/{order.id}/cancel", headers=headers, json={"reason": "x"})

    raw_text = client.get(AUDIT_LOGS_URL, headers=headers).text
    assert admin.password_hash not in raw_text
    assert "Bearer" not in raw_text
