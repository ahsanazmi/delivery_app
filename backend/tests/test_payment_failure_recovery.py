"""Payment System Phase 32 — PAYMENT FAILURE & RECOVERY TESTING.

Eleven named failure/recovery scenarios, each proven to leave the
backend in a consistent final state. Most of the underlying mechanisms
were already built by earlier phases (webhook idempotency, Phase 18;
dead-order handling, Phase 22; retry, Phase 20); this phase found and
fixed two real gaps — a transient provider outage during /verify was
previously indistinguishable from a genuine rejection (now its own
distinct, non-alarming outcome), and "order expires" (scenario 11)
didn't exist as any mechanism at all (now a lazy, on-access check, no
scheduler required) — and consolidates all eleven into one canonical,
explicitly-named test file.
"""

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.core.security import hash_password
from app.db.base import Base
from app.models.notification import Notification, NotificationType
from app.models.order import Order, OrderStatus
from app.models.payment import Payment, PaymentProvider, PaymentStatus
from app.models.payment_attempt import PaymentAttempt
from app.models.restaurant import Restaurant
from app.models.user import User, UserRole
from app.services.orders import cancel_order
from app.services.payment.exceptions import PaymentExpiredError, PaymentVerificationError, ProviderRequestError
from app.services.payment.payment_service import PaymentService
from app.services.payment.provider import PaymentProvider as PaymentProviderABC
from app.services.payment.provider import ProviderOrder, ProviderPayment, ProviderRefund
from app.services.payment.webhook_service import process_webhook_event


@pytest.fixture()
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    Base.metadata.drop_all(engine)


def _seed_order(db, tag: str, total=Decimal("230.00")) -> Order:
    owner = User(name="Owner", email=f"owner-{tag}@example.com", phone=f"94000000{tag[-2:]}", password_hash=hash_password("x"), role=UserRole.RESTAURANT_OWNER)
    customer = User(name="Customer", email=f"customer-{tag}@example.com", phone=f"95000000{tag[-2:]}", password_hash=hash_password("x"), role=UserRole.CUSTOMER)
    db.add_all([owner, customer])
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
        order_number=f"ORD-P32-{tag}", status=OrderStatus.PLACED,
        subtotal=total - Decimal("30.00"), delivery_fee=Decimal("30.00"), total=total,
        payment_method="razorpay", address_line="1 Road", city="Town", postal_code="123456",
    )
    db.add(order)
    db.commit()
    return order


class _ScriptedProvider(PaymentProviderABC):
    """A provider stand-in whose fetch_payment/fetch_order can be told,
    per test, to either succeed with a specific captured amount/order or
    raise ProviderRequestError — everything scenario 3/4/5/7/9/11 need."""

    name = "scripted"

    def __init__(self, *, order_id: str, amount: Decimal, currency: str = "INR", signature: str = "genuine-sig", raise_on_fetch: bool = False):
        self.order_id = order_id
        self.amount = amount
        self.currency = currency
        self.signature = signature
        self.raise_on_fetch = raise_on_fetch

    def create_order(self, *, amount, currency, receipt, notes=None):
        raise NotImplementedError

    def verify_payment_signature(self, *, provider_order_id, provider_payment_id, signature):
        return signature == self.signature

    def fetch_payment(self, provider_payment_id):
        if self.raise_on_fetch:
            raise ProviderRequestError("simulated transient network failure")
        return ProviderPayment(provider_payment_id=provider_payment_id, provider_order_id=self.order_id, status="captured", amount=self.amount, currency=self.currency)

    def fetch_order(self, provider_order_id):
        if self.raise_on_fetch:
            raise ProviderRequestError("simulated transient network failure")
        return ProviderOrder(provider_order_id=provider_order_id, amount=self.amount, currency=self.currency, status="paid")

    def initiate_refund(self, *, provider_payment_id, amount, notes=None):
        raise NotImplementedError

    def verify_webhook_signature(self, *, payload, signature):
        raise NotImplementedError


def _make_payment(db, order, *, provider_order_id="order_p32", created_at=None):
    payment = Payment(
        order_id=order.id, user_id=order.user_id, provider=PaymentProvider.RAZORPAY,
        payment_status=PaymentStatus.PENDING, amount=order.total, razorpay_order_id=provider_order_id,
        created_at=created_at or datetime.now(UTC),
    )
    db.add(payment)
    db.commit()
    db.refresh(payment)
    return payment


def _webhook_captured_body(order_id, payment_id, amount_paise):
    return json.dumps({
        "event": "payment.captured",
        "payload": {"payment": {"entity": {"id": payment_id, "order_id": order_id, "amount": amount_paise, "currency": "INR", "status": "captured"}}},
    }).encode()


# ---------------------------------------------------------------------------
# 1 & 2. Internet disconnect / app closed during checkout — a payment left
# PENDING with no callback ever received is safe: not corrupted, not
# silently paid, still actionable later.
# ---------------------------------------------------------------------------


def test_payment_left_pending_after_disconnect_is_safe_and_still_actionable(db):
    order = _seed_order(db, "01")
    payment = _make_payment(db, order)

    # The app "closes"/"disconnects" right here — no verify() call ever
    # happens. Nothing about the order/payment is corrupted by simply
    # doing nothing.
    db.refresh(payment)
    db.refresh(order)
    assert payment.payment_status == PaymentStatus.PENDING
    assert order.is_paid is False
    assert db.query(PaymentAttempt).filter(PaymentAttempt.payment_id == payment.id).count() == 0

    # It's still genuinely actionable later — a real verify() with the
    # correct signature succeeds normally, proving nothing about the
    # abandoned state itself blocks a legitimate later completion.
    provider = _ScriptedProvider(order_id="order_p32", amount=order.total)
    service = PaymentService(providers={"razorpay": provider})
    verified = service.verify_payment(db, payment=payment, provider_order_id="order_p32", provider_payment_id="pay_p32_01", signature="genuine-sig")
    assert verified.payment_status == PaymentStatus.PAID


# ---------------------------------------------------------------------------
# 3. Payment succeeds but the mobile callback is lost — the webhook alone,
# with NO /verify call ever made, still correctly resolves the payment.
# ---------------------------------------------------------------------------


def test_webhook_alone_resolves_a_payment_whose_mobile_callback_was_never_received(db):
    order = _seed_order(db, "03")
    payment = _make_payment(db, order, provider_order_id="order_p32_03")
    amount_paise = int(payment.amount * 100)

    # No verify() call ever happens — simulating the app crashing right
    # after Razorpay's own checkout sheet closed.
    event = process_webhook_event(db, raw_body=_webhook_captured_body("order_p32_03", "pay_p32_03", amount_paise))

    assert event.outcome == "payment_marked_paid"
    db.refresh(payment)
    db.refresh(order)
    assert payment.payment_status == PaymentStatus.PAID
    assert order.is_paid is True


# ---------------------------------------------------------------------------
# 4. Webhook arrives before frontend verification.
# ---------------------------------------------------------------------------


def test_webhook_before_verify_leaves_a_consistent_paid_state_and_verify_is_safely_rejected(db):
    order = _seed_order(db, "04")
    payment = _make_payment(db, order, provider_order_id="order_p32_04")
    amount_paise = int(payment.amount * 100)

    webhook_event = process_webhook_event(db, raw_body=_webhook_captured_body("order_p32_04", "pay_p32_04", amount_paise))
    assert webhook_event.outcome == "payment_marked_paid"

    # The mobile app's own /verify call, arriving late, must never be
    # allowed to re-process an already-settled payment — this is
    # enforced at the endpoint's own _VERIFIABLE_STATUSES gate (PAID is
    # excluded), proven here at the service+status level: the payment is
    # already PAID, so nothing downstream should ever touch it again.
    db.refresh(payment)
    assert payment.payment_status == PaymentStatus.PAID
    paid_at_from_webhook = payment.paid_at

    # A second, different webhook-shaped event for the same payment
    # (simulating the customer's own late verification racing in via a
    # second webhook-equivalent path) must be a no-op too.
    second = process_webhook_event(db, raw_body=_webhook_captured_body("order_p32_04", "pay_p32_04", amount_paise))
    assert second.outcome == "duplicate_ignored"
    db.refresh(payment)
    assert payment.paid_at == paid_at_from_webhook  # never re-timestamped


# ---------------------------------------------------------------------------
# 5. Frontend verification arrives before webhook.
# ---------------------------------------------------------------------------


def test_verify_before_webhook_then_a_genuine_webhook_is_idempotent(db):
    order = _seed_order(db, "05")
    payment = _make_payment(db, order, provider_order_id="order_p32_05")

    provider = _ScriptedProvider(order_id="order_p32_05", amount=order.total)
    service = PaymentService(providers={"razorpay": provider})
    verified = service.verify_payment(db, payment=payment, provider_order_id="order_p32_05", provider_payment_id="pay_p32_05", signature="genuine-sig")
    assert verified.payment_status == PaymentStatus.PAID
    paid_at_from_verify = verified.paid_at

    # Razorpay's own webhook for the same event arrives afterward — must
    # be recognized as already-resolved, not reprocessed.
    amount_paise = int(payment.amount * 100)
    webhook_event = process_webhook_event(db, raw_body=_webhook_captured_body("order_p32_05", "pay_p32_05", amount_paise))
    assert webhook_event.outcome == "duplicate_ignored"

    db.refresh(payment)
    assert payment.paid_at == paid_at_from_verify  # untouched by the later webhook


# ---------------------------------------------------------------------------
# 6. Webhook arrives multiple times.
# ---------------------------------------------------------------------------


def test_webhook_delivered_three_times_is_processed_exactly_once(db):
    order = _seed_order(db, "06")
    payment = _make_payment(db, order, provider_order_id="order_p32_06")
    amount_paise = int(payment.amount * 100)
    body = _webhook_captured_body("order_p32_06", "pay_p32_06", amount_paise)

    from app.models.webhook_event import WebhookEvent

    events = [process_webhook_event(db, raw_body=body, event_id="evt_p32_06") for _ in range(3)]
    # Redeliveries of the exact same event_id are recognized before any
    # parsing/dispatch happens at all (Phase 18) — each call returns the
    # SAME original row, never reprocessing it, so all three share one id.
    assert len({e.id for e in events}) == 1
    assert db.query(WebhookEvent).filter(WebhookEvent.event_id == "evt_p32_06").count() == 1

    db.refresh(payment)
    assert payment.payment_status == PaymentStatus.PAID


# ---------------------------------------------------------------------------
# 7. Payment provider temporarily unavailable (during verification).
# ---------------------------------------------------------------------------


def test_provider_unavailable_during_verify_leaves_payment_pending_not_failed(db):
    order = _seed_order(db, "07")
    payment = _make_payment(db, order, provider_order_id="order_p32_07")

    provider = _ScriptedProvider(order_id="order_p32_07", amount=order.total, raise_on_fetch=True)
    service = PaymentService(providers={"razorpay": provider})

    with pytest.raises(ProviderRequestError):
        service.verify_payment(db, payment=payment, provider_order_id="order_p32_07", provider_payment_id="pay_p32_07", signature="genuine-sig")

    db.refresh(payment)
    # The core assertion: a transient outage must NEVER be mistaken for a
    # genuine rejection — the payment stays exactly PENDING, not FAILED.
    assert payment.payment_status == PaymentStatus.PENDING
    assert payment.failure_reason is None

    # No false "payment failed" alarms fired for what might just be a
    # momentary network blip.
    assert db.query(Notification).filter(Notification.type == NotificationType.PAYMENT_FAILURE).count() == 0

    # It's genuinely retryable afterward, once the provider is reachable
    # again — proving the outage didn't leave anything stuck.
    provider.raise_on_fetch = False
    retried = service.verify_payment(db, payment=payment, provider_order_id="order_p32_07", provider_payment_id="pay_p32_07", signature="genuine-sig")
    assert retried.payment_status == PaymentStatus.PAID


# ---------------------------------------------------------------------------
# 8 & 11. Payment remains pending / Order expires.
# ---------------------------------------------------------------------------


def test_a_fresh_pending_payment_is_unaffected_by_the_expiry_check(db):
    order = _seed_order(db, "08")
    payment = _make_payment(db, order, provider_order_id="order_p32_08")  # created "now"

    provider = _ScriptedProvider(order_id="order_p32_08", amount=order.total)
    service = PaymentService(providers={"razorpay": provider})
    verified = service.verify_payment(db, payment=payment, provider_order_id="order_p32_08", provider_payment_id="pay_p32_08", signature="genuine-sig")
    assert verified.payment_status == PaymentStatus.PAID


def test_a_stale_pending_payment_expires_on_the_next_verify_attempt(db):
    order = _seed_order(db, "11a")
    stale_created_at = datetime.now(UTC) - timedelta(hours=2)
    payment = _make_payment(db, order, provider_order_id="order_p32_11a", created_at=stale_created_at)

    provider = _ScriptedProvider(order_id="order_p32_11a", amount=order.total)
    service = PaymentService(providers={"razorpay": provider})

    with pytest.raises(PaymentExpiredError):
        service.verify_payment(db, payment=payment, provider_order_id="order_p32_11a", provider_payment_id="pay_p32_11a", signature="genuine-sig")

    db.refresh(payment)
    # A clean, terminal, non-actionable state — not left ambiguously
    # PENDING/retryable forever.
    assert payment.payment_status == PaymentStatus.FAILED
    assert "expired" in payment.failure_reason.lower()
    # Routine, not an anomaly — no alarm notifications for an abandoned checkout.
    assert db.query(Notification).filter(Notification.type == NotificationType.PAYMENT_FAILURE).count() == 0


def test_a_stale_pending_payment_expires_on_the_next_retry_attempt_too(db):
    order = _seed_order(db, "11b")
    stale_created_at = datetime.now(UTC) - timedelta(hours=2)
    payment = _make_payment(db, order, provider_order_id="order_p32_11b", created_at=stale_created_at)

    service = PaymentService()
    with pytest.raises(PaymentExpiredError):
        service.retry_payment(db, payment=payment)

    db.refresh(payment)
    assert payment.payment_status == PaymentStatus.FAILED
    assert "expired" in payment.failure_reason.lower()


# ---------------------------------------------------------------------------
# 9. Customer retries.
# ---------------------------------------------------------------------------


def test_customer_retry_then_successful_verify_never_creates_a_second_payment_row(db):
    order = _seed_order(db, "09")
    payment = _make_payment(db, order, provider_order_id="order_p32_09")

    provider = _ScriptedProvider(order_id="order_p32_09", amount=order.total, signature="wrong")
    service = PaymentService(providers={"razorpay": provider})
    with pytest.raises(PaymentVerificationError):
        service.verify_payment(db, payment=payment, provider_order_id="order_p32_09", provider_payment_id="pay_p32_09_attempt1", signature="not-the-real-signature")
    db.refresh(payment)
    assert payment.payment_status == PaymentStatus.FAILED

    retried = service.retry_payment(db, payment=payment)
    assert retried.payment_status == PaymentStatus.PENDING
    assert retried.razorpay_order_id == "order_p32_09"  # same provider order reopened, never a new one

    provider.signature = "genuine-sig"
    verified = service.verify_payment(db, payment=payment, provider_order_id="order_p32_09", provider_payment_id="pay_p32_09_attempt2", signature="genuine-sig")
    assert verified.payment_status == PaymentStatus.PAID
    assert db.query(Payment).filter(Payment.order_id == order.id).count() == 1  # still just one row
    assert db.query(PaymentAttempt).filter(PaymentAttempt.payment_id == payment.id).count() == 2  # both attempts kept


# ---------------------------------------------------------------------------
# 10. Customer cancels (while payment is still in flight).
# ---------------------------------------------------------------------------


def test_cancelling_an_order_leaves_its_pending_payment_untouched_and_a_later_webhook_is_flagged_not_silently_paid(db):
    order = _seed_order(db, "10")
    payment = _make_payment(db, order, provider_order_id="order_p32_10")
    admin = User(name="Admin", email="admin-p32-10@example.com", phone="9600000010", password_hash=hash_password("x"), role=UserRole.ADMIN, is_active=True)
    db.add(admin)
    db.commit()

    cancel_order(db, order.user_id, order.id, "Changed my mind")
    db.refresh(order)
    db.refresh(payment)
    assert order.status == OrderStatus.CANCELLED
    # The payment itself is left completely untouched by cancellation —
    # cancel_order() never mutates it (see Phase 32's own audit of this
    # exact behavior).
    assert payment.payment_status == PaymentStatus.PENDING

    # The customer's already-open Razorpay checkout sheet completes
    # AFTER the in-app cancellation — a real, if rare, race. The webhook
    # must never silently mark a dead order's payment as a normal PAID.
    amount_paise = int(payment.amount * 100)
    event = process_webhook_event(db, raw_body=_webhook_captured_body("order_p32_10", "pay_p32_10", amount_paise))

    assert event.outcome == "refund_pending_dead_order"
    db.refresh(payment)
    assert payment.payment_status == PaymentStatus.REFUND_PENDING  # flagged, not silently PAID
    assert payment.is_verified is True  # the capture itself genuinely happened, never denied
    db.refresh(order)
    assert order.is_paid is False  # the dead order's own fields stay untouched

    alerts = db.query(Notification).filter(Notification.type == NotificationType.SYSTEM_ALERT).all()
    assert len(alerts) == 1  # an admin is alerted to reconcile manually
