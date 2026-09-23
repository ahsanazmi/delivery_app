"""Admin Portal — Phase 10: Order Management."""

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from app.core.security import create_access_token, hash_password
from app.db.session import get_db
from app.models.admin_audit_log import AdminAuditLog
from app.models.delivery_partner import ApprovalStatus, DeliveryPartner
from app.models.order import Order, OrderItem, OrderStatus, OrderStatusHistory
from app.models.user import User, UserRole

ORDERS_URL = "/api/v1/admin/orders"


def _db(client):
    return next(client.app.dependency_overrides[get_db]())


def _make_user(db, *, name, email, phone, role):
    user = User(name=name, email=email, phone=phone, password_hash=hash_password("x"), role=role)
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _make_approved_rider(db, *, name, email, phone):
    """Rider Assignment Integration — admin's own assign-rider endpoint now
    requires an APPROVED DeliveryPartner record, same standing the
    self-service accept flow already required."""
    rider = _make_user(db, name=name, email=email, phone=phone, role=UserRole.RIDER)
    db.add(DeliveryPartner(user_id=rider.id, approval_status=ApprovalStatus.APPROVED))
    db.commit()
    return rider


def _admin_headers(db):
    admin = _make_user(db, name="Admin", email="admin-p10@example.com", phone="8900000001", role=UserRole.ADMIN)
    token = create_access_token(admin.id)
    return {"Authorization": f"Bearer {token}"}


def _admin_headers_with_admin(db):
    admin = _make_user(db, name="Admin", email=f"admin-p10-{uuid.uuid4().hex[:8]}@example.com", phone=f"89{uuid.uuid4().hex[:8]}", role=UserRole.ADMIN)
    token = create_access_token(admin.id)
    return admin, {"Authorization": f"Bearer {token}"}


def _make_order(
    db, *, customer_name="Cust", restaurant_name="Some Restaurant", rider_id=None,
    status=OrderStatus.PLACED, payment_method="cod", payment_status="pending",
    subtotal=Decimal("100.00"), delivery_fee=Decimal("30.00"), tax=Decimal("5.00"), discount=Decimal("0.00"),
    order_number=None,
):
    total = subtotal + delivery_fee + tax - discount
    order = Order(
        user_id=uuid.uuid4(), rider_id=rider_id, customer_name=customer_name, customer_email="cust@example.com",
        customer_phone="9999999999", restaurant_id="rest-1", restaurant_name=restaurant_name, restaurant_phone="9876500000",
        restaurant_address="Main Road", order_number=order_number or f"ORD-{uuid.uuid4().hex[:20]}",
        status=status, payment_method=payment_method, payment_status=payment_status,
        subtotal=subtotal, delivery_fee=delivery_fee, tax=tax, discount=discount, total=total,
        address_line="123 Main St", city="Testville", postal_code="123456",
    )
    db.add(order)
    db.commit()
    db.refresh(order)
    db.add(OrderItem(order_id=order.id, product_id="prod-1", restaurant_id="rest-1", product_name="Item", unit_price=subtotal, quantity=1))
    db.add(OrderStatusHistory(order_id=order.id, status=OrderStatus.PLACED, note="Order placed"))
    if status != OrderStatus.PLACED:
        db.add(OrderStatusHistory(order_id=order.id, status=status, note=f"Moved to {status.value}"))
    db.commit()
    return order


def test_list_orders_requires_admin(client):
    db = _db(client)
    customer = _make_user(db, name="Some Customer", email="some-cust-p10@example.com", phone="8900000010", role=UserRole.CUSTOMER)
    token = create_access_token(customer.id)
    assert client.get(ORDERS_URL, headers={"Authorization": f"Bearer {token}"}).status_code == 403
    assert client.get(ORDERS_URL).status_code == 401


def test_list_orders_returns_summary_with_rider_name(client):
    db = _db(client)
    headers = _admin_headers(db)
    rider = _make_user(db, name="Delivery Rider P10", email="rider-p10@example.com", phone="8900000020", role=UserRole.RIDER)
    order = _make_order(db, customer_name="Alice", restaurant_name="Chai House", rider_id=rider.id, status=OrderStatus.OUT_FOR_DELIVERY)

    response = client.get(ORDERS_URL, headers=headers)
    assert response.status_code == 200
    body = response.json()
    match = next(item for item in body["items"] if item["id"] == str(order.id))
    assert match["customer_name"] == "Alice"
    assert match["restaurant_name"] == "Chai House"
    assert match["rider_name"] == "Delivery Rider P10"
    assert match["status"] == "out_for_delivery"
    assert Decimal(match["total"]) == order.total


def test_list_orders_search_matches_order_number_customer_restaurant_and_rider(client):
    db = _db(client)
    headers = _admin_headers(db)
    rider = _make_user(db, name="Findable Rider Name", email="findable-rider-p10@example.com", phone="8900000030", role=UserRole.RIDER)
    target = _make_order(db, customer_name="Findable Customer", order_number="ORD-FINDME-001")
    _make_order(db, customer_name="Other Customer", restaurant_name="Other Place")
    by_rider = _make_order(db, rider_id=rider.id)

    r1 = client.get(ORDERS_URL, headers=headers, params={"search": "FINDME"})
    assert [i["id"] for i in r1.json()["items"]] == [str(target.id)]

    r2 = client.get(ORDERS_URL, headers=headers, params={"search": "Findable Customer"})
    assert [i["id"] for i in r2.json()["items"]] == [str(target.id)]

    r3 = client.get(ORDERS_URL, headers=headers, params={"search": "Findable Rider Name"})
    assert [i["id"] for i in r3.json()["items"]] == [str(by_rider.id)]


def test_list_orders_status_filter(client):
    db = _db(client)
    headers = _admin_headers(db)
    delivered = _make_order(db, status=OrderStatus.DELIVERED)
    _make_order(db, status=OrderStatus.PLACED)

    response = client.get(ORDERS_URL, headers=headers, params={"status": "delivered"})
    ids = [item["id"] for item in response.json()["items"]]
    assert ids == [str(delivered.id)]


def test_list_orders_payment_method_and_status_filters(client):
    db = _db(client)
    headers = _admin_headers(db)
    cod_pending = _make_order(db, payment_method="cod", payment_status="pending")
    _make_order(db, payment_method="razorpay", payment_status="paid")

    r1 = client.get(ORDERS_URL, headers=headers, params={"payment_method": "cod"})
    assert [i["id"] for i in r1.json()["items"]] == [str(cod_pending.id)]

    r2 = client.get(ORDERS_URL, headers=headers, params={"payment_status": "pending"})
    assert [i["id"] for i in r2.json()["items"]] == [str(cod_pending.id)]


def test_list_orders_date_range_filter(client):
    db = _db(client)
    headers = _admin_headers(db)
    old_order = _make_order(db)
    db.query(Order).filter(Order.id == old_order.id).update({Order.created_at: datetime.now(UTC) - timedelta(days=10)})
    db.commit()
    new_order = _make_order(db)

    cutoff = (datetime.now(UTC) - timedelta(days=1)).date().isoformat()
    response = client.get(ORDERS_URL, headers=headers, params={"date_from": cutoff})
    ids = [item["id"] for item in response.json()["items"]]
    assert str(new_order.id) in ids
    assert str(old_order.id) not in ids


def test_list_orders_pagination(client):
    db = _db(client)
    headers = _admin_headers(db)
    for _ in range(3):
        _make_order(db)

    response = client.get(ORDERS_URL, headers=headers, params={"page": 1, "limit": 2})
    body = response.json()
    assert body["total"] >= 3
    assert len(body["items"]) == 2
    assert body["page"] == 1
    assert body["limit"] == 2


def test_get_order_detail_includes_items_totals_and_timeline(client):
    db = _db(client)
    headers = _admin_headers(db)
    order = _make_order(
        db, customer_name="Detail Customer", status=OrderStatus.DELIVERED,
        subtotal=Decimal("100.00"), delivery_fee=Decimal("30.00"), tax=Decimal("5.00"), discount=Decimal("10.00"),
    )

    response = client.get(f"{ORDERS_URL}/{order.id}", headers=headers)
    assert response.status_code == 200
    body = response.json()
    assert body["customer_name"] == "Detail Customer"
    assert body["customer_email"] == "cust@example.com"
    assert Decimal(body["subtotal"]) == Decimal("100.00")
    assert Decimal(body["delivery_fee"]) == Decimal("30.00")
    assert Decimal(body["tax"]) == Decimal("5.00")
    assert Decimal(body["discount"]) == Decimal("10.00")
    assert Decimal(body["total"]) == Decimal("125.00")
    assert len(body["items"]) == 1
    assert len(body["status_history"]) == 2
    # Chronological — placed first, delivered second.
    assert body["status_history"][0]["status"] == "placed"
    assert body["status_history"][1]["status"] == "delivered"


def test_get_order_detail_404_for_missing(client):
    db = _db(client)
    headers = _admin_headers(db)
    response = client.get(f"{ORDERS_URL}/00000000-0000-0000-0000-000000000000", headers=headers)
    assert response.status_code == 404


def test_get_order_detail_shows_no_rider_when_unassigned(client):
    db = _db(client)
    headers = _admin_headers(db)
    order = _make_order(db)

    response = client.get(f"{ORDERS_URL}/{order.id}", headers=headers)
    assert response.json()["rider_name"] is None


def test_assign_rider_still_works_at_its_pre_existing_path(client):
    """Phase 10 moved this route's code without changing its path or
    validated-transition behavior — a direct proof it still works there."""
    db = _db(client)
    admin, headers = _admin_headers_with_admin(db)
    rider = _make_approved_rider(db, name="Legacy Route Rider", email="legacy-route-rider-p10@example.com", phone="8900000040")
    order = _make_order(db, status=OrderStatus.READY_FOR_PICKUP)

    assign = client.patch(f"{ORDERS_URL}/{order.id}/assign-rider", headers=headers, json={"rider_id": str(rider.id), "reason": "Nearest available rider"})
    assert assign.status_code == 200
    assert assign.json()["rider_id"] == str(rider.id)


def test_assign_rider_requires_a_reason(client):
    """Order State Rule — assign-rider is exclusively an admin action, so
    it must be explicit (a reason) and audited, same as cancel/reassign."""
    db = _db(client)
    _, headers = _admin_headers_with_admin(db)
    rider = _make_user(db, name="No Reason Rider", email="no-reason-rider-p10@example.com", phone="8900000041", role=UserRole.RIDER)
    order = _make_order(db, status=OrderStatus.READY_FOR_PICKUP)

    assert client.patch(f"{ORDERS_URL}/{order.id}/assign-rider", headers=headers, json={"rider_id": str(rider.id)}).status_code == 422
    assert client.patch(f"{ORDERS_URL}/{order.id}/assign-rider", headers=headers, json={"rider_id": str(rider.id), "reason": ""}).status_code == 422


def test_assign_rider_creates_an_audit_log_entry(client):
    db = _db(client)
    admin, headers = _admin_headers_with_admin(db)
    rider = _make_approved_rider(db, name="Audited Rider", email="audited-rider-p10@example.com", phone="8900000042")
    order = _make_order(db, status=OrderStatus.READY_FOR_PICKUP)

    response = client.patch(f"{ORDERS_URL}/{order.id}/assign-rider", headers=headers, json={"rider_id": str(rider.id), "reason": "Closest to restaurant"})
    assert response.status_code == 200

    entry = db.query(AdminAuditLog).filter(AdminAuditLog.target_id == str(order.id), AdminAuditLog.action == "order.assign_rider").one()
    assert entry.admin_id == admin.id
    assert entry.reason == "Closest to restaurant"
    assert entry.new_state == str(rider.id)


def test_assign_rider_invalid_from_a_non_ready_status_is_a_conflict_and_writes_no_audit_log(client):
    db = _db(client)
    _, headers = _admin_headers_with_admin(db)
    rider = _make_user(db, name="Blocked Rider", email="blocked-rider-p10@example.com", phone="8900000043", role=UserRole.RIDER)
    order = _make_order(db, status=OrderStatus.DELIVERED)

    response = client.patch(f"{ORDERS_URL}/{order.id}/assign-rider", headers=headers, json={"rider_id": str(rider.id), "reason": "test"})
    assert response.status_code == 409
    assert db.query(AdminAuditLog).filter(AdminAuditLog.target_id == str(order.id), AdminAuditLog.action == "order.assign_rider").count() == 0


def test_assign_rider_requires_admin(client):
    db = _db(client)
    customer = _make_user(db, name="Not Admin", email="not-admin-assign-p10@example.com", phone="8900000044", role=UserRole.CUSTOMER)
    rider = _make_user(db, name="Rider X", email="rider-x-assign-p10@example.com", phone="8900000045", role=UserRole.RIDER)
    order = _make_order(db, status=OrderStatus.READY_FOR_PICKUP)
    token = create_access_token(customer.id)

    response = client.patch(
        f"{ORDERS_URL}/{order.id}/assign-rider",
        headers={"Authorization": f"Bearer {token}"},
        json={"rider_id": str(rider.id), "reason": "test"},
    )
    assert response.status_code == 403
