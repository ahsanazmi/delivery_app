"""Notifications & Communication System Phase 22 — COD Notifications.

COD_SETTLEMENT_DUE was already wired (Phase 11, admin + rider). This
file covers the three genuine gaps this phase's own audit found:
COD_COLLECTION_REQUIRED (a rider reminder, fired once the order is
actually OUT_FOR_DELIVERY), COD_COLLECTED (the cash-payment counterpart
to the customer's own online-payment success notification), and
COD_RECONCILIATION_ISSUE (a rider's app state disagreeing with what the
platform already has recorded as collected — reuses SYSTEM_ALERT, the
same "needs manual review" type Phase 13 already established for this
kind of anomaly). Also confirms this phase's own explicit requirement —
no sensitive financial information beyond what each recipient already
legitimately needs — by asserting exactly what each body does and does
not contain.
"""

from decimal import Decimal

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.core.security import hash_password
from app.db.base import Base
from app.models.delivery_partner import ApprovalStatus, DeliveryPartner
from app.models.notification import Notification, NotificationType
from app.models.order import OrderStatus
from app.models.restaurant import Restaurant
from app.models.user import User, UserRole
from app.services.addresses import create_address
from app.services.cart import add_item, create_cart_for_user
from app.services.orders import create_order, transition_order_status
from app.services.rider_deliveries import accept_delivery, collect_cod_payment, pickup_delivery, start_delivery


@pytest.fixture()
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    Base.metadata.drop_all(engine)


def _restaurant(db, tag="p22"):
    owner = User(name="Owner", email=f"owner-{tag}@example.com", password_hash=hash_password("x"), role=UserRole.RESTAURANT_OWNER)
    db.add(owner)
    db.commit()
    restaurant = Restaurant(
        owner_id=owner.id, name=f"Diner {tag}", phone="9876543210", address="1 Road",
        latitude=Decimal("12.1"), longitude=Decimal("77.1"),
        minimum_order=Decimal("0.00"), delivery_fee=Decimal("0.00"),
    )
    db.add(restaurant)
    db.commit()
    return restaurant


def _place_order(db, restaurant, *, customer_email="customer-p22@example.com"):
    customer = User(name="Cust", email=customer_email, password_hash=hash_password("x"), role=UserRole.CUSTOMER)
    db.add(customer)
    db.commit()
    from app.models.product import Product

    product = Product(restaurant_id=restaurant.id, name="Item", price=Decimal("150.00"))
    db.add(product)
    db.commit()
    cart = create_cart_for_user(db, customer.id)
    add_item(db, cart, product.id, 1)
    address = create_address(db, customer.id, {
        "label": "Home", "recipient_name": "Cust", "phone": "9999999999",
        "address_line": "1 Road", "city": "Bengaluru", "state": "Karnataka", "postal_code": "560001",
    })
    return customer, create_order(db, customer, address.id, payment_method="cod")


def _approved_rider(db, *, email, phone):
    rider = User(name="Rider", email=email, phone=phone, password_hash=hash_password("x"), role=UserRole.RIDER)
    db.add(rider)
    db.commit()
    db.add(DeliveryPartner(user_id=rider.id, approval_status=ApprovalStatus.APPROVED, is_online=True))
    db.commit()
    return rider


def _admin(db, email="admin-p22@example.com"):
    admin = User(name="Admin", email=email, password_hash=hash_password("x"), role=UserRole.ADMIN)
    db.add(admin)
    db.commit()
    return admin


def _to_out_for_delivery(db, order, rider):
    transition_order_status(db, order, OrderStatus.CONFIRMED)
    transition_order_status(db, order, OrderStatus.PREPARING)
    transition_order_status(db, order, OrderStatus.READY_FOR_PICKUP)
    accept_delivery(db, rider, order.id)
    pickup_delivery(db, rider, order.id)
    return start_delivery(db, rider, order.id)


def test_out_for_delivery_notifies_the_rider_to_collect_cash(db):
    restaurant = _restaurant(db, "required")
    customer, order = _place_order(db, restaurant, customer_email="cust-required@example.com")
    rider = _approved_rider(db, email="rider-required@example.com", phone="9800000020")

    _to_out_for_delivery(db, order, rider)

    notification = db.scalar(
        select(Notification).where(Notification.user_id == rider.id, Notification.type == NotificationType.COD_PENDING)
    )
    assert notification is not None
    assert notification.role == UserRole.RIDER
    assert str(order.total) in notification.body
    # No customer PII/payment-credential leakage into the rider's own
    # operational reminder.
    assert customer.email not in notification.body


def test_online_payment_orders_never_trigger_a_cod_collection_reminder(db):
    """Order State Rule — payment_method is "cod" by default in this test
    suite's own helper; this proves the guard is payment-method-aware,
    not just status-aware, using the same default order but manually
    marking it already paid (the state a razorpay order would actually
    be in by the time it reaches OUT_FOR_DELIVERY)."""
    restaurant = _restaurant(db, "online")
    customer, order = _place_order(db, restaurant, customer_email="cust-online@example.com")
    order.payment_method = "razorpay"
    order.is_paid = True
    db.commit()
    rider = _approved_rider(db, email="rider-online@example.com", phone="9800000021")

    transition_order_status(db, order, OrderStatus.CONFIRMED)
    transition_order_status(db, order, OrderStatus.PREPARING)
    transition_order_status(db, order, OrderStatus.READY_FOR_PICKUP)
    accept_delivery(db, rider, order.id)
    pickup_delivery(db, rider, order.id)
    start_delivery(db, rider, order.id)

    notification = db.scalar(
        select(Notification).where(Notification.user_id == rider.id, Notification.type == NotificationType.COD_PENDING)
    )
    assert notification is None


def test_cod_collection_notifies_the_customer(db):
    restaurant = _restaurant(db, "collected")
    customer, order = _place_order(db, restaurant, customer_email="cust-collected@example.com")
    rider = _approved_rider(db, email="rider-collected@example.com", phone="9800000022")
    _to_out_for_delivery(db, order, rider)

    collect_cod_payment(db, rider, order.id)

    notification = db.scalar(
        select(Notification).where(Notification.user_id == customer.id, Notification.type == NotificationType.COD_COLLECTED)
    )
    assert notification is not None
    assert notification.role == UserRole.CUSTOMER
    assert str(order.total) in notification.body
    # No rider identity or internal commission/settlement figures leak
    # into the customer's own payment-received confirmation.
    assert rider.name not in notification.body


def test_a_conflicting_collection_attempt_raises_a_reconciliation_issue_for_admins(db):
    """The realistic shape of this conflict (per collect_cod_payment's
    own docstring): the order's own currently-assigned rider tries to
    collect cash the platform already has recorded as collected by
    someone/something else — a different rider's prior collection, or
    the admin settlement fallback with no rider attribution. Two
    different riders simultaneously "assigned" isn't reachable at all
    (Order.rider_id is a single field, and reassignment is only valid
    while still RIDER_ASSIGNED, before pickup) — so this is constructed
    directly, the same way that real anomaly would actually arise."""
    restaurant = _restaurant(db, "conflict")
    customer, order = _place_order(db, restaurant, customer_email="cust-conflict@example.com")
    rider_a = _approved_rider(db, email="rider-conflict-a@example.com", phone="9800000023")
    other_rider = _approved_rider(db, email="rider-conflict-other@example.com", phone="9800000024")
    admin = _admin(db)
    _to_out_for_delivery(db, order, rider_a)

    from app.models.payment import Payment, PaymentProvider, PaymentStatus

    db.add(Payment(
        order_id=order.id, user_id=customer.id, provider=PaymentProvider.COD, amount=order.total,
        payment_status=PaymentStatus.PAID, collected_by_rider_id=other_rider.id,
    ))
    order.is_paid = True
    db.commit()

    from fastapi import HTTPException

    with pytest.raises(HTTPException):
        collect_cod_payment(db, rider_a, order.id)

    notification = db.scalar(
        select(Notification).where(Notification.user_id == admin.id, Notification.type == NotificationType.SYSTEM_ALERT)
    )
    assert notification is not None
    assert notification.order_id == order.id
    assert rider_a.name in notification.body


def test_a_same_rider_retry_never_raises_a_false_reconciliation_issue(db):
    """The idempotent-retry path (Phase 28) is a safe replay, not a real
    conflict — it must never page an admin."""
    restaurant = _restaurant(db, "retry")
    customer, order = _place_order(db, restaurant, customer_email="cust-retry@example.com")
    rider = _approved_rider(db, email="rider-retry@example.com", phone="9800000025")
    admin = _admin(db, email="admin-retry@example.com")
    _to_out_for_delivery(db, order, rider)

    collect_cod_payment(db, rider, order.id)
    collect_cod_payment(db, rider, order.id)  # retried call, same rider

    notification = db.scalar(
        select(Notification).where(Notification.user_id == admin.id, Notification.type == NotificationType.SYSTEM_ALERT)
    )
    assert notification is None
