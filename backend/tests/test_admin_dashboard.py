"""Admin Portal — Phase 2: Admin Dashboard.

Seeds known data directly against the DB (bypassing self-registration
where a role isn't self-registerable) so every summary figure, list, and
alert can be asserted against an exact expected value rather than just
"the endpoint returns 200" — plus the admin-only authorization boundary.
"""

import uuid
from decimal import Decimal

from app.core.security import create_access_token, hash_password
from app.db.session import get_db
from app.models.delivery_partner import ApprovalStatus, DeliveryPartner
from app.models.order import Order, OrderStatus
from app.models.payment import Payment, PaymentProvider, PaymentStatus
from app.models.restaurant import Restaurant
from app.models.rider_settlement import RiderSettlement, SettlementType
from app.models.user import User, UserRole

ADMIN_URL = "/api/v1/admin/dashboard"


def _db(client):
    return next(client.app.dependency_overrides[get_db]())


def _make_user(db, *, name, email, phone, role, password="secure-pass-123"):
    user = User(name=name, email=email, phone=phone, password_hash=hash_password(password), role=role)
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _admin_headers(client, db):
    admin = _make_user(db, name="Admin", email="admin-dash-p2@example.com", phone="9600000001", role=UserRole.ADMIN)
    token = create_access_token(admin.id)
    return {"Authorization": f"Bearer {token}"}


def _make_order(db, *, user_id, status, total, created_hours_ago=None):
    order = Order(
        user_id=user_id,
        customer_name="Some Customer",
        customer_email="customer@example.com",
        restaurant_id="rest-1",
        restaurant_name="Test Restaurant",
        order_number=f"ORD-{uuid.uuid4().hex[:20]}",
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
    if created_hours_ago is not None:
        from datetime import UTC, datetime, timedelta

        db.query(Order).filter(Order.id == order.id).update(
            {Order.created_at: datetime.now(UTC) - timedelta(hours=created_hours_ago)}
        )
        db.commit()
    return order


def test_dashboard_requires_authentication(client):
    response = client.get(ADMIN_URL)
    assert response.status_code == 401


def test_dashboard_rejects_non_admin_roles(client):
    for role in (UserRole.CUSTOMER, UserRole.RIDER, UserRole.RESTAURANT_OWNER):
        db = _db(client)
        user = _make_user(db, name=f"Not Admin {role.value}", email=f"na-{role.value}@example.com", phone=f"96{role.value[:8]}", role=role)
        token = create_access_token(user.id)
        response = client.get(ADMIN_URL, headers={"Authorization": f"Bearer {token}"})
        assert response.status_code == 403, role


def test_dashboard_summary_reflects_seeded_data(client):
    db = _db(client)
    headers = _admin_headers(client, db)

    customer = _make_user(db, name="Cust One", email="cust-p2@example.com", phone="9600000010", role=UserRole.CUSTOMER)
    _make_user(db, name="Cust Two", email="cust-p2-b@example.com", phone="9600000011", role=UserRole.CUSTOMER)

    owner = _make_user(db, name="Owner P2", email="owner-p2@example.com", phone="9600000020", role=UserRole.RESTAURANT_OWNER)
    active_restaurant = Restaurant(
        owner_id=owner.id, name="Active Place", phone="9876500001", address="Addr",
        latitude=Decimal("12.97"), longitude=Decimal("77.59"),
        minimum_order=Decimal("0.00"), delivery_fee=Decimal("20.00"), is_active=True,
    )
    inactive_restaurant = Restaurant(
        owner_id=owner.id, name="Inactive Place", phone="9876500002", address="Addr",
        latitude=Decimal("12.97"), longitude=Decimal("77.59"),
        minimum_order=Decimal("0.00"), delivery_fee=Decimal("20.00"), is_active=False,
    )
    db.add_all([active_restaurant, inactive_restaurant])
    db.commit()

    approved_rider = _make_user(db, name="Approved Rider", email="rider-approved-p2@example.com", phone="9600000030", role=UserRole.RIDER)
    db.add(DeliveryPartner(user_id=approved_rider.id, approval_status=ApprovalStatus.APPROVED))
    pending_rider = _make_user(db, name="Pending Rider", email="rider-pending-p2@example.com", phone="9600000031", role=UserRole.RIDER)
    db.add(DeliveryPartner(user_id=pending_rider.id, approval_status=ApprovalStatus.PENDING))
    suspended_rider = _make_user(db, name="Suspended Rider", email="rider-suspended-p2@example.com", phone="9600000032", role=UserRole.RIDER)
    db.add(DeliveryPartner(user_id=suspended_rider.id, approval_status=ApprovalStatus.SUSPENDED))
    db.commit()

    delivered_today = _make_order(db, user_id=customer.id, status=OrderStatus.DELIVERED, total=Decimal("250.00"))
    _make_order(db, user_id=customer.id, status=OrderStatus.PREPARING, total=Decimal("100.00"))
    _make_order(db, user_id=customer.id, status=OrderStatus.CANCELLED, total=Decimal("75.00"))

    payment = Payment(
        order_id=delivered_today.id, user_id=customer.id, provider=PaymentProvider.COD,
        payment_status=PaymentStatus.PAID, amount=Decimal("250.00"), collected_by_rider_id=approved_rider.id,
    )
    db.add(payment)
    db.add(RiderSettlement(rider_id=approved_rider.id, settlement_type=SettlementType.REMITTANCE, amount=Decimal("100.00")))
    db.commit()

    response = client.get(ADMIN_URL, headers=headers)
    assert response.status_code == 200
    body = response.json()
    summary = body["summary"]

    assert summary["total_customers"] == 2
    assert summary["total_restaurants"] == 2
    assert summary["active_restaurants"] == 1
    assert summary["total_riders"] == 3
    assert summary["active_riders"] == 1
    assert summary["todays_orders"] == 3
    assert Decimal(summary["todays_revenue"]) == Decimal("425.00")
    assert summary["pending_orders"] == 1
    assert summary["pending_rider_approvals"] == 1
    assert summary["pending_restaurant_approvals"] == 0
    assert Decimal(summary["pending_cod_settlement"]) == Decimal("150.00")

    assert len(body["recent_orders"]) == 3
    assert any(reg["role"] == "CUSTOMER" for reg in body["recent_registrations"])
    assert len(body["pending_approvals"]) == 1
    assert body["pending_approvals"][0]["type"] == "rider"

    alert_messages = [a["message"] for a in body["alerts"]]
    assert any("suspended" in m for m in alert_messages)
    assert any("awaiting review" in m for m in alert_messages)
    assert any("not yet remitted" in m for m in alert_messages)


def test_stale_unaccepted_order_triggers_alert(client):
    db = _db(client)
    headers = _admin_headers(client, db)
    customer = _make_user(db, name="Stale Cust", email="stale-cust-p2@example.com", phone="9600000040", role=UserRole.CUSTOMER)
    _make_order(db, user_id=customer.id, status=OrderStatus.PLACED, total=Decimal("50.00"), created_hours_ago=1)

    response = client.get(ADMIN_URL, headers=headers)
    assert response.status_code == 200
    alerts = response.json()["alerts"]
    assert any("awaiting restaurant acceptance" in a["message"] for a in alerts)


def test_every_alert_has_a_navigable_link(client):
    """Phase 24's own requirement: every alert must be clickable straight
    to its relevant admin section — never a dead-end banner."""
    db = _db(client)
    headers = _admin_headers(client, db)
    customer = _make_user(db, name="Link Cust", email="link-cust-p24@example.com", phone="9600000050", role=UserRole.CUSTOMER)
    _make_order(db, user_id=customer.id, status=OrderStatus.CANCELLED, total=Decimal("50.00"))

    response = client.get(ADMIN_URL, headers=headers)
    assert response.status_code == 200
    alerts = response.json()["alerts"]
    assert len(alerts) > 0
    for alert in alerts:
        assert alert["link"].startswith("/")


def test_failed_payment_today_triggers_alert(client):
    db = _db(client)
    headers = _admin_headers(client, db)
    customer = _make_user(db, name="Fail Cust", email="fail-cust-p24@example.com", phone="9600000051", role=UserRole.CUSTOMER)
    order = _make_order(db, user_id=customer.id, status=OrderStatus.PLACED, total=Decimal("50.00"))
    db.add(Payment(
        order_id=order.id, user_id=customer.id, provider=PaymentProvider.RAZORPAY,
        payment_status=PaymentStatus.FAILED, amount=Decimal("50.00"), failure_reason="Signature verification failed",
    ))
    db.commit()

    response = client.get(ADMIN_URL, headers=headers)
    alerts = response.json()["alerts"]
    matching = [a for a in alerts if "payment(s) failed" in a["message"]]
    assert len(matching) == 1
    assert matching[0]["link"] == "/payments?status=FAILED"


def test_cancelled_order_today_triggers_alert_linking_to_orders(client):
    db = _db(client)
    headers = _admin_headers(client, db)
    customer = _make_user(db, name="Cancel Cust", email="cancel-cust-p24@example.com", phone="9600000052", role=UserRole.CUSTOMER)
    _make_order(db, user_id=customer.id, status=OrderStatus.CANCELLED, total=Decimal("50.00"))

    response = client.get(ADMIN_URL, headers=headers)
    alerts = response.json()["alerts"]
    matching = [a for a in alerts if "cancelled today" in a["message"]]
    assert len(matching) == 1
    assert matching[0]["link"] == "/orders?status=cancelled"


def test_pending_restaurant_approval_triggers_alert(client):
    db = _db(client)
    headers = _admin_headers(client, db)
    owner = _make_user(db, name="Pending Owner", email="pending-owner-p24@example.com", phone="9600000053", role=UserRole.RESTAURANT_OWNER)
    from app.models.delivery_partner import ApprovalStatus as RestaurantApprovalStatus

    restaurant = Restaurant(
        owner_id=owner.id, name="Awaiting Place", phone="9876500010", address="Addr",
        latitude=Decimal("12.97"), longitude=Decimal("77.59"), minimum_order=Decimal("0.00"),
        delivery_fee=Decimal("20.00"), approval_status=RestaurantApprovalStatus.PENDING,
    )
    db.add(restaurant)
    db.commit()

    response = client.get(ADMIN_URL, headers=headers)
    alerts = response.json()["alerts"]
    matching = [a for a in alerts if "awaiting approval" in a["message"]]
    assert len(matching) == 1
    assert matching[0]["link"] == "/restaurants?approval_status=PENDING"


def test_maintenance_mode_triggers_critical_system_issue_alert(client):
    db = _db(client)
    headers = _admin_headers(client, db)

    before = client.get(ADMIN_URL, headers=headers).json()["alerts"]
    assert not any("Maintenance mode" in a["message"] for a in before)

    settle = client.patch(
        "/api/v1/admin/settings", headers=headers, json={"maintenance_mode": True, "reason": "test"}
    )
    assert settle.status_code == 200

    after = client.get(ADMIN_URL, headers=headers).json()["alerts"]
    matching = [a for a in after if "Maintenance mode" in a["message"]]
    assert len(matching) == 1
    assert matching[0]["severity"] == "critical"
    assert matching[0]["link"] == "/settings"
