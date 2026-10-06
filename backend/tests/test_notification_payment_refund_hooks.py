"""Notifications & Communication System Phase 8 — Event-Driven
Notification Hooks.

Proves the three genuinely new hooks this phase wires: a customer is
notified when their online payment succeeds (PaymentService.verify_payment,
the actively-wired flow — not app/services/payments.py's simpler one),
when a refund is initiated (still PROCESSING at Razorpay), and when a
refund completes (whether that happens synchronously in create_refund or
asynchronously via the refund.processed webhook).
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
from app.models.order import Order, OrderStatus
from app.models.payment import Payment, PaymentProvider as PaymentProviderEnum, PaymentStatus
from app.models.restaurant import Restaurant
from app.models.user import User, UserRole
from app.services.payment import refund_service
from app.services.payment.payment_service import PaymentService
from app.services.payment.provider import PaymentProvider, ProviderOrder, ProviderPayment, ProviderRefund
from app.services.payment.webhook_service import process_webhook_event


@pytest.fixture()
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    Base.metadata.drop_all(engine)


def _seed_order(db, total=Decimal("500.00")) -> Order:
    owner = User(name="Owner", email="owner-p8@example.com", phone="9700000001", password_hash=hash_password("x"), role=UserRole.RESTAURANT_OWNER)
    customer = User(name="Customer", email="customer-p8@example.com", phone="9700000002", password_hash=hash_password("x"), role=UserRole.CUSTOMER)
    db.add_all([owner, customer])
    db.commit()
    restaurant = Restaurant(
        owner_id=owner.id, name="Notif Diner", phone="9876543210", address="1 Road",
        latitude=Decimal("12.1"), longitude=Decimal("77.1"),
        minimum_order=Decimal("0.00"), delivery_fee=Decimal("0.00"),
    )
    db.add(restaurant)
    db.commit()
    order = Order(
        user_id=customer.id, customer_name=customer.name, customer_email=customer.email,
        restaurant_id=str(restaurant.id), restaurant_name=restaurant.name,
        order_number="ORD-P8-0001", status=OrderStatus.PLACED,
        subtotal=total, delivery_fee=Decimal("0.00"), total=total,
        payment_method="cod", address_line="1 Road", city="Town", postal_code="123456",
    )
    db.add(order)
    db.commit()
    return order


class FakeProvider(PaymentProvider):
    """A minimal stand-in — only what this file's three scenarios need,
    not the full FakeProvider used elsewhere (each test file in this
    codebase keeps its own self-contained helpers, never importing from
    another test module)."""

    name = "fake"

    def __init__(self, *, refund_status: str = "processed"):
        self.refund_status = refund_status
        self._order_id: str | None = None
        self._amount: Decimal | None = None

    def create_order(self, *, amount, currency, receipt, notes=None):
        self._order_id = f"order_fake_{receipt}"
        self._amount = amount
        return ProviderOrder(provider_order_id=self._order_id, amount=amount, currency=currency, status="created")

    def verify_payment_signature(self, *, provider_order_id, provider_payment_id, signature):
        return True

    def fetch_payment(self, provider_payment_id):
        return ProviderPayment(
            provider_payment_id=provider_payment_id, provider_order_id=self._order_id,
            status="captured", amount=self._amount, currency="INR",
        )

    def fetch_order(self, provider_order_id):
        return ProviderOrder(provider_order_id=provider_order_id, amount=self._amount, currency="INR", status="paid")

    def initiate_refund(self, *, provider_payment_id, amount, notes=None):
        return ProviderRefund(provider_refund_id=f"rfnd_fake_{provider_payment_id}", status=self.refund_status, amount=amount)

    def verify_webhook_signature(self, *, payload, signature):
        return True


def test_payment_success_notifies_the_customer(db):
    order = _seed_order(db)
    fake = FakeProvider()
    service = PaymentService(providers={"razorpay": fake})
    payment = service.create_payment_for_order(db, order=order, method="razorpay")

    service.verify_payment(
        db, payment=payment, provider_order_id=payment.razorpay_order_id,
        provider_payment_id="pay_p8_1", signature="ok",
    )

    notification = db.scalar(
        select(Notification).where(Notification.order_id == order.id, Notification.type == NotificationType.PAYMENT_SUCCESS)
    )
    assert notification is not None
    assert notification.user_id == order.user_id
    assert notification.data["order_id"] == str(order.id)


def test_refund_still_processing_notifies_refund_initiated_not_completed(db):
    order = _seed_order(db)
    fake = FakeProvider()
    service = PaymentService(providers={"razorpay": fake})
    payment = service.create_payment_for_order(db, order=order, method="razorpay")
    service.verify_payment(
        db, payment=payment, provider_order_id=payment.razorpay_order_id,
        provider_payment_id="pay_p8_2", signature="ok",
    )
    db.refresh(payment)

    processing_provider = FakeProvider(refund_status="pending")
    refund_service.create_refund(db, payment=payment, amount=Decimal("150.00"), reason="test", provider=processing_provider)

    initiated = db.scalar(
        select(Notification).where(Notification.order_id == order.id, Notification.type == NotificationType.REFUND_INITIATED)
    )
    completed = db.scalar(
        select(Notification).where(Notification.order_id == order.id, Notification.type == NotificationType.REFUND_COMPLETED)
    )
    assert initiated is not None
    assert completed is None, "a refund still PROCESSING must not be told 'completed' yet"


def test_refund_settling_instantly_notifies_completed_only_not_initiated(db):
    """The COD/instant-"processed" case — a customer whose refund never
    passes through PROCESSING must get exactly one notification, not
    both."""
    order = _seed_order(db, total=Decimal("300.00"))
    customer_id = order.user_id
    payment = Payment(
        order_id=order.id, user_id=customer_id, provider=PaymentProviderEnum.COD,
        payment_status=PaymentStatus.PAID, amount=Decimal("300.00"),
    )
    db.add(payment)
    db.commit()

    refund_service.create_refund(db, payment=payment, amount=Decimal("100.00"), reason="test", provider=None)

    completed = db.scalar(
        select(Notification).where(Notification.order_id == order.id, Notification.type == NotificationType.REFUND_COMPLETED)
    )
    initiated = db.scalar(
        select(Notification).where(Notification.order_id == order.id, Notification.type == NotificationType.REFUND_INITIATED)
    )
    assert completed is not None
    assert initiated is None, "an instantly-settled refund must not also get an 'initiated' notification"


def test_refund_completing_later_via_webhook_notifies_completed_exactly_once(db):
    order = _seed_order(db)
    fake = FakeProvider()
    service = PaymentService(providers={"razorpay": fake})
    payment = service.create_payment_for_order(db, order=order, method="razorpay")
    service.verify_payment(
        db, payment=payment, provider_order_id=payment.razorpay_order_id,
        provider_payment_id="pay_p8_3", signature="ok",
    )
    db.refresh(payment)

    processing_provider = FakeProvider(refund_status="pending")
    refund = refund_service.create_refund(db, payment=payment, amount=Decimal("100.00"), reason="test", provider=processing_provider)
    assert refund.provider_refund_id is not None

    webhook_body = json.dumps({
        "event": "refund.processed",
        "payload": {"refund": {"entity": {
            "id": refund.provider_refund_id, "payment_id": payment.razorpay_payment_id, "amount": 10000, "status": "processed",
        }}},
    }).encode()

    process_webhook_event(db, raw_body=webhook_body, event_id="evt_p8_refund_1")

    completed_rows = list(
        db.scalars(select(Notification).where(Notification.order_id == order.id, Notification.type == NotificationType.REFUND_COMPLETED))
    )
    assert len(completed_rows) == 1

    # A duplicate webhook delivery of the exact same event must not
    # create a second notification — the pre-existing state-check guard
    # in _handle_refund_processed already prevents a second mutation, and
    # this proves the notification hook rides on that same guarantee.
    process_webhook_event(db, raw_body=webhook_body, event_id="evt_p8_refund_1")
    completed_rows_after_retry = list(
        db.scalars(select(Notification).where(Notification.order_id == order.id, Notification.type == NotificationType.REFUND_COMPLETED))
    )
    assert len(completed_rows_after_retry) == 1
