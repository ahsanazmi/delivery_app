"""Notifications & Communication System Phase 21 — Payment Notifications.

PAYMENT_SUCCESS, PAYMENT_FAILED, REFUND_INITIATED, and REFUND_COMPLETED
were all already wired for the client-driven path (PaymentService.
verify_payment / RefundService.create_refund, Phase 8) and
REFUND_COMPLETED was already wired for its async webhook resolution
(_handle_refund_processed). REFUND_INITIATED has no webhook-path
counterpart to wire — a refund is only ever *initiated* synchronously,
by an admin calling create_refund(); a webhook only ever resolves one
already in flight. The two genuine gaps this phase's own audit found
were payment.captured and payment.failed reaching PAID/FAILED via the
async webhook (rather than the client's own /verify call getting there
first) previously notifying nobody but admins — this file covers both,
and confirms (this phase's own explicit requirement) that the
notification calls never influence the payment_status decision itself,
only ever run after it's already been made.
"""

import json
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.core.security import hash_password
from app.db.base import Base
from app.models.notification import Notification, NotificationType
from app.models.payment import Payment, PaymentProvider, PaymentStatus
from app.models.product import Product
from app.models.restaurant import Restaurant
from app.models.user import User, UserRole
from app.services.addresses import create_address
from app.services.cart import add_item, create_cart_for_user
from app.services.orders import create_order
from app.services.payment.webhook_service import process_webhook_event


@pytest.fixture()
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    Base.metadata.drop_all(engine)


def _order_with_payment(db, tag="p21"):
    customer = User(name="Cust", email=f"customer-{tag}@example.com", password_hash=hash_password("x"), role=UserRole.CUSTOMER)
    db.add(customer)
    db.commit()
    owner = User(name="Owner", email=f"owner-{tag}@example.com", password_hash=hash_password("x"), role=UserRole.RESTAURANT_OWNER)
    db.add(owner)
    db.commit()
    restaurant = Restaurant(
        owner_id=owner.id, name=f"Diner {tag}", phone="9876543210", address="1 Road",
        latitude=Decimal("12.1"), longitude=Decimal("77.1"),
        minimum_order=Decimal("0.00"), delivery_fee=Decimal("30.00"),
    )
    db.add(restaurant)
    db.commit()
    product = Product(restaurant_id=restaurant.id, name="Item", price=Decimal("200.00"))
    db.add(product)
    db.commit()
    cart = create_cart_for_user(db, customer.id)
    add_item(db, cart, product.id, 1)
    address = create_address(db, customer.id, {
        "label": "Home", "recipient_name": "Cust", "phone": "9999999999",
        "address_line": "1 Road", "city": "Bengaluru", "state": "Karnataka", "postal_code": "560001",
    })
    order = create_order(db, customer, address.id, payment_method="cod")
    payment = Payment(
        order_id=order.id, user_id=customer.id, provider=PaymentProvider.RAZORPAY,
        amount=order.total, payment_status=PaymentStatus.PENDING, razorpay_order_id=f"order_{tag}",
    )
    db.add(payment)
    db.commit()
    db.refresh(payment)
    db.refresh(order)
    return customer, owner, order, payment


def _captured_body(order_id, payment_id, amount_paise, currency="INR"):
    return json.dumps({
        "event": "payment.captured",
        "payload": {"payment": {"entity": {
            "id": payment_id, "order_id": order_id, "amount": amount_paise, "currency": currency, "status": "captured",
        }}},
    }).encode()


def _failed_body(order_id, payment_id, description="Card declined"):
    return json.dumps({
        "event": "payment.failed",
        "payload": {"payment": {"entity": {
            "id": payment_id, "order_id": order_id, "amount": 0, "currency": "INR", "status": "failed",
            "error_description": description,
        }}},
    }).encode()


def test_payment_captured_via_webhook_notifies_the_customer(db):
    customer, owner, order, payment = _order_with_payment(db, "capturecust")
    amount_paise = int(payment.amount * 100)

    event = process_webhook_event(db, raw_body=_captured_body(payment.razorpay_order_id, "pay_p21_1", amount_paise))

    assert event.outcome == "payment_marked_paid"
    notification = db.scalar(
        select(Notification).where(Notification.user_id == customer.id, Notification.type == NotificationType.PAYMENT_SUCCESS)
    )
    assert notification is not None
    assert notification.order_id == order.id


def test_payment_captured_via_webhook_notifies_the_restaurant_owner(db):
    customer, owner, order, payment = _order_with_payment(db, "captureowner")
    amount_paise = int(payment.amount * 100)

    process_webhook_event(db, raw_body=_captured_body(payment.razorpay_order_id, "pay_p21_2", amount_paise))

    notification = db.scalar(
        select(Notification).where(Notification.user_id == owner.id, Notification.type == NotificationType.PAYMENT_UPDATE)
    )
    assert notification is not None
    assert notification.role == UserRole.RESTAURANT_OWNER
    assert "confirmed" in notification.body.lower()


def test_payment_failed_via_webhook_notifies_the_customer(db):
    customer, owner, order, payment = _order_with_payment(db, "failcust")

    event = process_webhook_event(db, raw_body=_failed_body(payment.razorpay_order_id, "pay_p21_3", "Card declined"))

    assert event.outcome == "payment_marked_failed"
    notification = db.scalar(
        select(Notification).where(Notification.user_id == customer.id, Notification.type == NotificationType.PAYMENT_UPDATE)
    )
    assert notification is not None
    assert notification.role == UserRole.CUSTOMER
    assert notification.order_id == order.id


def test_duplicate_captured_webhook_never_sends_a_second_success_notification(db):
    """Payment state is decided once, by the first genuine capture — a
    redelivered/duplicate webhook for an already-PAID payment must never
    raise a second notification, since it never re-decides anything."""
    customer, owner, order, payment = _order_with_payment(db, "duplicatecapture")
    amount_paise = int(payment.amount * 100)

    process_webhook_event(db, raw_body=_captured_body(payment.razorpay_order_id, "pay_p21_4", amount_paise))
    event = process_webhook_event(db, raw_body=_captured_body(payment.razorpay_order_id, "pay_p21_4", amount_paise))

    assert event.outcome == "duplicate_ignored"
    notifications = db.scalars(
        select(Notification).where(Notification.user_id == customer.id, Notification.type == NotificationType.PAYMENT_SUCCESS)
    ).all()
    assert len(notifications) == 1


def test_notifications_never_run_before_payment_status_is_actually_decided(db):
    """This phase's own explicit requirement: notifications must never
    determine payment status. An amount/currency mismatch — an anomaly
    webhook_service.py deliberately never resolves toward PAID or
    FAILED — must raise no payment notification of either kind; the
    payment's own status stays exactly what it already was."""
    customer, owner, order, payment = _order_with_payment(db, "mismatch")

    event = process_webhook_event(db, raw_body=_captured_body(payment.razorpay_order_id, "pay_p21_5", 1))  # wrong amount

    assert event.outcome == "amount_mismatch"
    db.refresh(payment)
    assert payment.payment_status == PaymentStatus.PENDING
    # Excludes ORDER_PLACED — create_order's own unrelated notification,
    # not a payment one — the point here is specifically that no
    # PAYMENT_SUCCESS/PAYMENT_UPDATE notification was raised.
    payment_notifications = db.scalars(
        select(Notification).where(
            Notification.user_id == customer.id,
            Notification.type.in_([NotificationType.PAYMENT_SUCCESS, NotificationType.PAYMENT_UPDATE]),
        )
    ).all()
    assert payment_notifications == []
