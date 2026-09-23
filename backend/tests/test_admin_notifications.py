"""Admin Portal — Phase 20: Admin Notifications.

Covers the two halves of this phase:
  1. The three read/mark-read endpoints — thin, admin-scoped wrappers around
     the already-generic, already-shared list_notifications /
     mark_notification_read / mark_all_notifications_read functions.
  2. notify_admins() itself, and the concrete triggers wired into it: a new
     restaurant registering, a new rider registering (but not a customer), a
     rider submitting a document, an order being cancelled/rejected, an
     online payment failing signature verification, and a rider's
     outstanding COD balance crossing the settlement-due threshold.
"""

import uuid
from decimal import Decimal

from app.core.config import settings
from app.core.security import create_access_token, hash_password
from app.db.session import get_db
from app.models.delivery_partner import ApprovalStatus, DeliveryPartner
from app.models.notification import Notification, NotificationType
from app.models.order import Order, OrderStatus
from app.models.payment import Payment, PaymentProvider, PaymentStatus
from app.models.restaurant import Restaurant
from app.models.rider_settlement import RiderSettlement, SettlementType
from app.models.user import User, UserRole
from app.schemas.auth import RegisterRequest
from app.schemas.restaurant import RestaurantCreate
from app.schemas.rider_document import RiderDocumentCreate
from app.services.auth import register_user
from app.services.orders import transition_order_status
from app.services.payments import verify_payment
from app.services.restaurants import create_restaurant
from app.services.rider_deliveries import COD_SETTLEMENT_DUE_THRESHOLD, collect_cod_payment
from app.services.rider_documents import create_rider_document

NOTIFICATIONS_URL = "/api/v1/admin/notifications"


def _db(client):
    return next(client.app.dependency_overrides[get_db]())


def _make_user(db, *, name, email, phone, role, is_active=True):
    user = User(name=name, email=email, phone=phone, password_hash=hash_password("x"), role=role, is_active=is_active)
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _admin(db, suffix, *, is_active=True):
    return _make_user(
        db, name=f"Admin {suffix}", email=f"admin-p20-{suffix}-{uuid.uuid4().hex[:6]}@example.com",
        phone=f"71{uuid.uuid4().hex[:8]}", role=UserRole.ADMIN, is_active=is_active,
    )


def _admin_headers(admin):
    return {"Authorization": f"Bearer {create_access_token(admin.id)}"}


def _notification_types_for(db, user_id):
    rows = db.query(Notification).filter(Notification.user_id == user_id).all()
    return [row.type for row in rows]


def test_notification_endpoints_require_admin(client):
    db = _db(client)
    customer = _make_user(db, name="Cust", email="cust-p20@example.com", phone="7100000001", role=UserRole.CUSTOMER)
    headers = {"Authorization": f"Bearer {create_access_token(customer.id)}"}

    assert client.get(NOTIFICATIONS_URL, headers=headers).status_code == 403
    assert client.get(NOTIFICATIONS_URL).status_code == 401
    assert client.post(f"{NOTIFICATIONS_URL}/{uuid.uuid4()}/read", headers=headers).status_code == 403
    assert client.post(f"{NOTIFICATIONS_URL}/read-all", headers=headers).status_code == 403
    assert client.post(f"{NOTIFICATIONS_URL}/read-all").status_code == 401


def test_list_mark_read_and_mark_all_read_work_for_an_admin(client):
    db = _db(client)
    admin = _admin(db, "list")
    headers = _admin_headers(admin)

    owner = _make_user(db, name="Owner", email="owner-p20-a@example.com", phone="7100000010", role=UserRole.RESTAURANT_OWNER)
    create_restaurant(
        db, RestaurantCreate(
            name="R1", phone="9876500000", address="Addr 1",
            latitude=Decimal("12.97"), longitude=Decimal("77.59"), owner_id=owner.id,
        ),
        actor=admin,
    )

    listed = client.get(NOTIFICATIONS_URL, headers=headers).json()
    assert len(listed) == 1
    assert listed[0]["type"] == "new_restaurant_registered"
    assert listed[0]["is_read"] is False

    read_one = client.post(f"{NOTIFICATIONS_URL}/{listed[0]['id']}/read", headers=headers)
    assert read_one.status_code == 200
    assert read_one.json()["is_read"] is True

    create_restaurant(
        db, RestaurantCreate(
            name="R2", phone="9876500001", address="Addr 2",
            latitude=Decimal("12.97"), longitude=Decimal("77.59"), owner_id=owner.id,
        ),
        actor=admin,
    )
    mark_all = client.post(f"{NOTIFICATIONS_URL}/read-all", headers=headers)
    assert mark_all.status_code == 200
    assert mark_all.json()["updated"] == 1

    listed_after = client.get(NOTIFICATIONS_URL, headers=headers).json()
    assert all(row["is_read"] for row in listed_after)


def test_new_restaurant_registration_notifies_only_active_admins(client):
    db = _db(client)
    active_admin = _admin(db, "active-r")
    inactive_admin = _admin(db, "inactive-r", is_active=False)
    non_admin = _make_user(db, name="NA", email="na-p20-r@example.com", phone="7100000020", role=UserRole.CUSTOMER)
    owner = _make_user(db, name="Owner2", email="owner-p20-b@example.com", phone="7100000021", role=UserRole.RESTAURANT_OWNER)

    create_restaurant(
        db, RestaurantCreate(
            name="Notif R", phone="9876500002", address="Addr Line 1", latitude=Decimal("12.97"),
            longitude=Decimal("77.59"), owner_id=owner.id,
        ),
        actor=active_admin,
    )

    assert NotificationType.NEW_RESTAURANT_REGISTERED in _notification_types_for(db, active_admin.id)
    assert _notification_types_for(db, inactive_admin.id) == []
    assert _notification_types_for(db, non_admin.id) == []


def test_new_rider_registration_notifies_admins_but_customer_registration_does_not(client):
    db = _db(client)
    admin = _admin(db, "reg")

    register_user(db, RegisterRequest(
        name="New Customer", email=f"cust-reg-p20-{uuid.uuid4().hex[:6]}@example.com", password="Passw0rd!", role=UserRole.CUSTOMER,
    ))
    assert NotificationType.NEW_RIDER_REGISTERED not in _notification_types_for(db, admin.id)

    register_user(db, RegisterRequest(
        name="New Rider", email=f"rider-reg-p20-{uuid.uuid4().hex[:6]}@example.com", password="Passw0rd!", role=UserRole.RIDER,
    ))
    types = _notification_types_for(db, admin.id)
    assert types.count(NotificationType.NEW_RIDER_REGISTERED) == 1


def test_document_submitted_notifies_admins(client):
    db = _db(client)
    admin = _admin(db, "doc")
    rider = _make_user(db, name="Doc Rider", email="doc-rider-p20@example.com", phone="7100000030", role=UserRole.RIDER)

    create_rider_document(db, rider.id, RiderDocumentCreate(
        document_type="IDENTITY_DOCUMENT", document_url="https://example.com/id.jpg",
    ))

    types = _notification_types_for(db, admin.id)
    assert NotificationType.DOCUMENT_SUBMITTED in types


def test_order_cancellation_and_rejection_notify_admins_as_order_issue(client):
    db = _db(client)
    admin = _admin(db, "order")
    customer = _make_user(db, name="Ord Cust", email="ord-cust-p20@example.com", phone="7100000040", role=UserRole.CUSTOMER)
    owner = _make_user(db, name="Ord Owner", email="ord-owner-p20@example.com", phone="7100000041", role=UserRole.RESTAURANT_OWNER)
    restaurant = Restaurant(
        owner_id=owner.id, name="Ord Restaurant", phone="9876500003", address="Addr",
        latitude=Decimal("12.97"), longitude=Decimal("77.59"),
        minimum_order=Decimal("0.00"), delivery_fee=Decimal("20.00"),
    )
    db.add(restaurant)
    db.commit()
    db.refresh(restaurant)

    def _make_order(order_status):
        order = Order(
            user_id=customer.id, customer_name=customer.name, customer_email=customer.email,
            restaurant_id=str(restaurant.id), restaurant_name=restaurant.name,
            order_number=f"ORD-{uuid.uuid4().hex[:20]}", status=OrderStatus.PLACED,
            subtotal=Decimal("100.00"), delivery_fee=Decimal("0.00"), total=Decimal("100.00"),
            payment_method="cod", address_line="123 Main St", city="Testville", postal_code="123456",
        )
        db.add(order)
        db.commit()
        db.refresh(order)
        return order

    cancelled_order = _make_order(OrderStatus.PLACED)
    transition_order_status(db, cancelled_order, OrderStatus.CANCELLED)

    rejected_order = _make_order(OrderStatus.PLACED)
    transition_order_status(db, rejected_order, OrderStatus.REJECTED)

    rows = db.query(Notification).filter(
        Notification.user_id == admin.id, Notification.type == NotificationType.ORDER_ISSUE
    ).all()
    order_ids = {row.order_id for row in rows}
    assert cancelled_order.id in order_ids
    assert rejected_order.id in order_ids


def test_payment_verification_failure_notifies_admins(client, monkeypatch):
    db = _db(client)
    admin = _admin(db, "pay")
    customer = _make_user(db, name="Pay Cust", email="pay-cust-p20@example.com", phone="7100000050", role=UserRole.CUSTOMER)
    order = Order(
        user_id=customer.id, customer_name=customer.name, customer_email=customer.email,
        restaurant_id=str(uuid.uuid4()), restaurant_name="R", order_number=f"ORD-{uuid.uuid4().hex[:20]}",
        status=OrderStatus.PLACED, subtotal=Decimal("100.00"), delivery_fee=Decimal("0.00"), total=Decimal("100.00"),
        payment_method="online", address_line="123 Main St", city="Testville", postal_code="123456",
    )
    db.add(order)
    db.commit()
    db.refresh(order)

    payment = Payment(
        user_id=customer.id, order_id=order.id, provider=PaymentProvider.RAZORPAY,
        payment_status=PaymentStatus.PENDING, amount=Decimal("100.00"),
        razorpay_order_id="order_test123",
    )
    db.add(payment)
    db.commit()
    db.refresh(payment)

    monkeypatch.setattr(settings, "RAZORPAY_KEY_SECRET", "test-secret")

    try:
        verify_payment(db, payment=payment, payload={
            "razorpay_order_id": "order_test123", "razorpay_payment_id": "pay_test123", "signature": "not-a-real-signature",
        })
    except Exception:
        pass

    rows = db.query(Notification).filter(
        Notification.user_id == admin.id, Notification.type == NotificationType.PAYMENT_FAILURE
    ).all()
    assert len(rows) == 1
    assert rows[0].order_id == order.id

    # Notification Event Integration (Phase 20) — the customer's own side
    # of the same failure, not just the admin alert.
    customer_rows = db.query(Notification).filter(
        Notification.user_id == customer.id, Notification.type == NotificationType.PAYMENT_UPDATE
    ).all()
    assert len(customer_rows) == 1
    assert customer_rows[0].order_id == order.id
    assert order.order_number in customer_rows[0].body


def test_cod_settlement_due_fires_once_outstanding_crosses_threshold(client):
    db = _db(client)
    admin = _admin(db, "cod")
    rider = _make_user(db, name="Cod Rider", email="cod-rider-p20@example.com", phone="7100000060", role=UserRole.RIDER)
    db.add(DeliveryPartner(user_id=rider.id, approval_status=ApprovalStatus.APPROVED))
    db.commit()
    customer = _make_user(db, name="Cod Cust", email="cod-cust-p20@example.com", phone="7100000061", role=UserRole.CUSTOMER)

    def _make_out_for_delivery_order(total):
        order = Order(
            user_id=customer.id, rider_id=rider.id, customer_name=customer.name, customer_email=customer.email,
            restaurant_id=str(uuid.uuid4()), restaurant_name="R", order_number=f"ORD-{uuid.uuid4().hex[:20]}",
            status=OrderStatus.OUT_FOR_DELIVERY, subtotal=total, delivery_fee=Decimal("0.00"), total=total,
            payment_method="cod", address_line="123 Main St", city="Testville", postal_code="123456",
        )
        db.add(order)
        db.commit()
        db.refresh(order)
        return order

    below_threshold_order = _make_out_for_delivery_order(Decimal("500.00"))
    collect_cod_payment(db, rider, below_threshold_order.id)
    assert NotificationType.COD_SETTLEMENT_DUE not in _notification_types_for(db, admin.id)

    at_threshold_order = _make_out_for_delivery_order(COD_SETTLEMENT_DUE_THRESHOLD - Decimal("500.00"))
    collect_cod_payment(db, rider, at_threshold_order.id)
    assert NotificationType.COD_SETTLEMENT_DUE in _notification_types_for(db, admin.id)


def test_cod_settlement_due_respects_remittances_already_settled(client):
    db = _db(client)
    admin = _admin(db, "cod2")
    rider = _make_user(db, name="Settled Rider", email="settled-rider-p20@example.com", phone="7100000070", role=UserRole.RIDER)
    db.add(DeliveryPartner(user_id=rider.id, approval_status=ApprovalStatus.APPROVED))
    db.add(RiderSettlement(rider_id=rider.id, settlement_type=SettlementType.REMITTANCE, amount=COD_SETTLEMENT_DUE_THRESHOLD))
    db.commit()
    customer = _make_user(db, name="Settled Cust", email="settled-cust-p20@example.com", phone="7100000071", role=UserRole.CUSTOMER)

    order = Order(
        user_id=customer.id, rider_id=rider.id, customer_name=customer.name, customer_email=customer.email,
        restaurant_id=str(uuid.uuid4()), restaurant_name="R", order_number=f"ORD-{uuid.uuid4().hex[:20]}",
        status=OrderStatus.OUT_FOR_DELIVERY, subtotal=Decimal("300.00"), delivery_fee=Decimal("0.00"), total=Decimal("300.00"),
        payment_method="cod", address_line="123 Main St", city="Testville", postal_code="123456",
    )
    db.add(order)
    db.commit()
    db.refresh(order)

    collect_cod_payment(db, rider, order.id)
    assert NotificationType.COD_SETTLEMENT_DUE not in _notification_types_for(db, admin.id)
