"""Payment System Phase 22 — PAYMENT/ORDER STATE MACHINE.

Proves the two explicit invariants this phase names:
1. DELIVERED + PAYMENT FAILED can never happen — a razorpay order can't
   even be accepted (the first step toward DELIVERED) while unpaid
   (Phase 16), so a FAILED payment structurally can't coexist with
   DELIVERED.
2. CANCELLED/REJECTED + a newly successful payment never silently looks
   like a normal, resolved PAID order — it's flagged REFUND_PENDING with
   an admin alert, per the "defined refund/reconciliation workflow" this
   phase requires instead of either denying a real charge happened or
   quietly treating a dead order as fulfilled.
"""
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.core.security import hash_password
from app.db.base import Base
from app.models.notification import Notification, NotificationType
from app.models.order import Order, OrderStatus
from app.models.payment import PaymentStatus
from app.models.restaurant import Restaurant
from app.models.user import User, UserRole
from app.services.orders import accept_order
from app.services.payment.exceptions import PaymentError
from app.services.payment.payment_service import PaymentService
from app.services.payment.provider import PaymentProvider, ProviderOrder, ProviderPayment, ProviderRefund


@pytest.fixture()
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    Base.metadata.drop_all(engine)


def _seed_order_and_restaurant(db, tag: str, total=Decimal("300.00")):
    owner = User(name="Owner", email=f"owner-{tag}@example.com", phone=f"9100000{tag[-3:]}", password_hash=hash_password("x"), role=UserRole.RESTAURANT_OWNER)
    customer = User(name="Customer", email=f"customer-{tag}@example.com", phone=f"9200000{tag[-3:]}", password_hash=hash_password("x"), role=UserRole.CUSTOMER)
    admin = User(name="Admin", email=f"admin-{tag}@example.com", phone=f"9300000{tag[-3:]}", password_hash=hash_password("x"), role=UserRole.ADMIN, is_active=True)
    db.add_all([owner, customer, admin])
    db.commit()
    restaurant = Restaurant(
        owner_id=owner.id, name=f"Diner {tag}", phone="9876543210", address="1 Road",
        latitude=Decimal("12.1"), longitude=Decimal("77.1"),
        minimum_order=Decimal("0.00"), delivery_fee=Decimal("30.00"),
    )
    db.add(restaurant)
    db.commit()
    order = Order(
        user_id=customer.id, customer_name=customer.name, customer_email=customer.email,
        restaurant_id=str(restaurant.id), restaurant_name=restaurant.name,
        order_number=f"ORD-{tag}-0001", status=OrderStatus.PLACED,
        subtotal=total - Decimal("30.00"), delivery_fee=Decimal("30.00"), total=total,
        payment_method="razorpay", address_line="1 Road", city="Town", postal_code="123456",
    )
    db.add(order)
    db.commit()
    return order, restaurant


class FakeProvider(PaymentProvider):
    name = "fake"

    def __init__(self):
        self.orders: dict[str, Decimal] = {}
        self._counter = 0

    def create_order(self, *, amount, currency, receipt, notes=None):
        self._counter += 1
        order_id = f"order_p22_{self._counter}"
        self.orders[order_id] = amount
        return ProviderOrder(provider_order_id=order_id, amount=amount, currency=currency, status="created")

    def _signature_for(self, order_id: str, payment_id: str) -> str:
        return f"sig::{order_id}::{payment_id}"

    def verify_payment_signature(self, *, provider_order_id, provider_payment_id, signature):
        return signature == self._signature_for(provider_order_id, provider_payment_id)

    def fetch_payment(self, provider_payment_id):
        order_id = next(reversed(self.orders), None)
        amount = self.orders.get(order_id, Decimal("0.00"))
        return ProviderPayment(provider_payment_id=provider_payment_id, provider_order_id=order_id, status="captured", amount=amount, currency="INR")

    def fetch_order(self, provider_order_id):
        amount = self.orders.get(provider_order_id, Decimal("0.00"))
        return ProviderOrder(provider_order_id=provider_order_id, amount=amount, currency="INR", status="paid")

    def initiate_refund(self, *, provider_payment_id, amount, notes=None):
        return ProviderRefund(provider_refund_id="rfnd_p22", status="processed", amount=amount)

    def verify_webhook_signature(self, *, payload, signature):
        return True


def _genuine_result_for(fake: FakeProvider, order_id: str):
    payment_id = order_id.replace("order_", "pay_", 1)
    return order_id, payment_id, fake._signature_for(order_id, payment_id)


# ---------------------------------------------------------------------------
# Invariant 1 — DELIVERED + PAYMENT FAILED can never happen
# ---------------------------------------------------------------------------


def test_a_razorpay_order_can_never_be_accepted_while_payment_is_failed(db):
    """The first step toward DELIVERED (accept_order -> CONFIRMED)
    already refuses an unpaid order (Phase 16) — a FAILED payment is
    unpaid by definition, so this closes off the only path to DELIVERED
    before it can ever start."""
    fake = FakeProvider()
    service = PaymentService(providers={"razorpay": fake})
    order, restaurant = _seed_order_and_restaurant(db, "deliverfail")
    payment = service.create_payment_for_order(db, order=order, method="razorpay")
    payment.payment_status = PaymentStatus.FAILED
    db.commit()

    with pytest.raises(Exception) as exc_info:
        accept_order(db, restaurant.id, order.id)
    assert getattr(exc_info.value, "status_code", None) == 409

    db.refresh(order)
    assert order.status == OrderStatus.PLACED  # never moved toward DELIVERED
    db.refresh(payment)
    assert payment.payment_status == PaymentStatus.FAILED  # untouched


def test_delivered_orders_payment_is_always_paid_never_failed(db):
    """The converse proof: walk a real payment all the way to PAID, then
    confirm accept_order() only then allows progress — DELIVERED and
    FAILED are never simultaneously true for the same order."""
    fake = FakeProvider()
    service = PaymentService(providers={"razorpay": fake})
    order, restaurant = _seed_order_and_restaurant(db, "deliverok")
    payment = service.create_payment_for_order(db, order=order, method="razorpay")
    order_id, payment_id, signature = _genuine_result_for(fake, payment.razorpay_order_id)
    verified = service.verify_payment(db, payment=payment, provider_order_id=order_id, provider_payment_id=payment_id, signature=signature)
    assert verified.payment_status == PaymentStatus.PAID

    accepted = accept_order(db, restaurant.id, order.id)
    assert accepted.status == OrderStatus.CONFIRMED
    db.refresh(payment)
    assert payment.payment_status == PaymentStatus.PAID  # never FAILED once past accept


# ---------------------------------------------------------------------------
# Invariant 2 — CANCELLED + a newly successful payment is never silently
# treated as a normal, resolved PAID order.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("dead_status", [OrderStatus.CANCELLED, OrderStatus.REJECTED])
def test_a_payment_that_succeeds_after_the_order_is_already_dead_is_flagged_not_silently_paid(db, dead_status):
    fake = FakeProvider()
    service = PaymentService(providers={"razorpay": fake})
    order, restaurant = _seed_order_and_restaurant(db, f"dead{dead_status.value[:3]}")
    payment = service.create_payment_for_order(db, order=order, method="razorpay")

    # The order dies (cancelled/rejected) while the payment is still open.
    order.status = dead_status
    db.commit()

    order_id, payment_id, signature = _genuine_result_for(fake, payment.razorpay_order_id)
    result = service.verify_payment(db, payment=payment, provider_order_id=order_id, provider_payment_id=payment_id, signature=signature)

    # The verification itself succeeds (the charge genuinely happened —
    # denying it would not un-charge the customer) but is never a plain,
    # resolved PAID.
    assert result.payment_status == PaymentStatus.REFUND_PENDING
    assert result.is_verified is True
    assert result.paid_at is not None
    assert result.razorpay_payment_id == payment_id

    # The order's own fields are deliberately left untouched.
    db.refresh(order)
    assert order.status == dead_status
    assert order.is_paid is False
    assert order.payment_status != "paid"

    # An urgent admin alert was raised for manual reconciliation.
    alerts = db.query(Notification).filter(Notification.type == NotificationType.SYSTEM_ALERT).all()
    assert len(alerts) == 1
    assert "cancelled/rejected" in alerts[0].title.lower() or "cancelled" in alerts[0].title.lower()
    assert str(order.order_number) in alerts[0].body


def test_a_normal_payment_on_a_still_live_order_is_never_flagged(db):
    """Confirms the new check isn't over-broad — an ordinary successful
    payment on a live order is unaffected."""
    fake = FakeProvider()
    service = PaymentService(providers={"razorpay": fake})
    order, restaurant = _seed_order_and_restaurant(db, "livepay")
    payment = service.create_payment_for_order(db, order=order, method="razorpay")

    order_id, payment_id, signature = _genuine_result_for(fake, payment.razorpay_order_id)
    result = service.verify_payment(db, payment=payment, provider_order_id=order_id, provider_payment_id=payment_id, signature=signature)

    assert result.payment_status == PaymentStatus.PAID
    db.refresh(order)
    assert order.is_paid is True
    assert order.payment_status == "paid"
    assert db.query(Notification).filter(Notification.type == NotificationType.SYSTEM_ALERT).count() == 0


def test_the_payment_attempt_record_reflects_the_genuine_capture_regardless_of_the_orders_fate(db):
    """The PaymentAttempt is the raw, honest record of what happened at
    the provider (captured = paid) — distinct from the parent Payment's
    own business-level status (which reflects that it now needs a
    refund), never conflated."""
    from app.models.payment_attempt import PaymentAttempt

    fake = FakeProvider()
    service = PaymentService(providers={"razorpay": fake})
    order, restaurant = _seed_order_and_restaurant(db, "attemptcheck")
    payment = service.create_payment_for_order(db, order=order, method="razorpay")
    order.status = OrderStatus.CANCELLED
    db.commit()

    order_id, payment_id, signature = _genuine_result_for(fake, payment.razorpay_order_id)
    service.verify_payment(db, payment=payment, provider_order_id=order_id, provider_payment_id=payment_id, signature=signature)

    attempts = db.query(PaymentAttempt).filter(PaymentAttempt.payment_id == payment.id, PaymentAttempt.provider_payment_id == payment_id).all()
    assert len(attempts) == 1
    assert attempts[0].status == PaymentStatus.PAID  # the attempt honestly records the real capture
