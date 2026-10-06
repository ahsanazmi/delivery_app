"""Notifications & Communication System Phase 13 — Admin Notifications.

Covers the two genuine gaps this phase's own audit found: the async,
provider-initiated payment.failed webhook and the refund.failed webhook
previously raised no admin alert at all (only the client-driven
verify_payment() failure path did). Every other example in this phase's
checklist — COD reconciliation, restaurant approval requests, rider
approval requests, delivery exceptions — is already covered by existing
Admin Portal Phase 20 / Notifications Phase 7 hooks (NEW_RESTAURANT_
REGISTERED, NEW_RIDER_REGISTERED, DOCUMENT_SUBMITTED, ORDER_ISSUE,
COD_SETTLEMENT_DUE); this file does not re-test those, only the two new
ones.
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
from app.models.refund import Refund, RefundStatus
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


def _admin(db, email="admin-p13@example.com"):
    admin = User(name="Admin", email=email, password_hash=hash_password("x"), role=UserRole.ADMIN)
    db.add(admin)
    db.commit()
    return admin


def _order_with_payment(db, tag="p13"):
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
    return order, payment


def _failed_body(order_id, payment_id, description="Card declined"):
    return json.dumps({
        "event": "payment.failed",
        "payload": {"payment": {"entity": {
            "id": payment_id, "order_id": order_id, "amount": 0, "currency": "INR", "status": "failed",
            "error_description": description,
        }}},
    }).encode()


def _refund_failed_body(refund_id, payment_id, amount_paise):
    return json.dumps({
        "event": "refund.failed",
        "payload": {"refund": {"entity": {"id": refund_id, "payment_id": payment_id, "amount": amount_paise, "status": "failed"}}},
    }).encode()


def test_payment_failed_webhook_notifies_admins(db):
    admin = _admin(db)
    order, payment = _order_with_payment(db, tag="payfail")

    event = process_webhook_event(db, raw_body=_failed_body(payment.razorpay_order_id, "pay_p13_1", "Card declined"))

    assert event.outcome == "payment_marked_failed"
    notification = db.scalar(
        select(Notification).where(Notification.user_id == admin.id, Notification.type == NotificationType.PAYMENT_FAILURE)
    )
    assert notification is not None
    assert notification.role == UserRole.ADMIN
    assert notification.order_id == order.id


def test_payment_failed_webhook_never_notifies_when_already_paid(db):
    """A late/out-of-order failure notification for an already-PAID
    payment must never raise a false "payment failed" admin alert — the
    handler's own existing idempotency guard (ignored_already_paid) means
    this code path is never reached at all."""
    admin = _admin(db, email="admin-nopaid@example.com")
    order, payment = _order_with_payment(db, tag="alreadypaid")
    payment.payment_status = PaymentStatus.PAID
    db.commit()

    event = process_webhook_event(db, raw_body=_failed_body(payment.razorpay_order_id, "pay_p13_2"))

    assert event.outcome == "ignored_already_paid"
    notification = db.scalar(
        select(Notification).where(Notification.user_id == admin.id, Notification.type == NotificationType.PAYMENT_FAILURE)
    )
    assert notification is None


def test_refund_failed_webhook_notifies_admins(db):
    admin = _admin(db, email="admin-refundfail@example.com")
    order, payment = _order_with_payment(db, tag="refundfail")
    refund = Refund(
        payment_id=payment.id, order_id=order.id, amount=Decimal("50.00"),
        status=RefundStatus.PROCESSING, provider_refund_id="rfnd_p13_1",
    )
    db.add(refund)
    db.commit()

    event = process_webhook_event(db, raw_body=_refund_failed_body("rfnd_p13_1", "pay_x", 5000))

    assert event.outcome == "refund_marked_failed"
    notification = db.scalar(
        select(Notification).where(Notification.user_id == admin.id, Notification.type == NotificationType.SYSTEM_ALERT)
    )
    assert notification is not None
    assert notification.role == UserRole.ADMIN
    assert notification.order_id == order.id
    assert "reconciliation" in notification.body.lower()


def test_refund_failed_webhook_never_notifies_when_already_completed(db):
    admin = _admin(db, email="admin-refundlate@example.com")
    order, payment = _order_with_payment(db, tag="refundlate")
    refund = Refund(
        payment_id=payment.id, order_id=order.id, amount=Decimal("50.00"),
        status=RefundStatus.COMPLETED, provider_refund_id="rfnd_p13_2",
    )
    db.add(refund)
    db.commit()

    event = process_webhook_event(db, raw_body=_refund_failed_body("rfnd_p13_2", "pay_x", 5000))

    assert event.outcome == "ignored_already_completed"
    notification = db.scalar(
        select(Notification).where(Notification.user_id == admin.id, Notification.type == NotificationType.SYSTEM_ALERT)
    )
    assert notification is None
