"""Payment System Phase 4 — Payment Service Architecture.

Covers the new app/services/payment/ package in isolation: RazorpayProvider
(HTTP calls mocked via httpx.MockTransport — real Razorpay-shaped request/
response, no network), the generic HMAC primitive, PaymentService
(orchestration, tested against a fake in-memory provider so these tests
never depend on HTTP at all), and RefundService. Nothing here is wired
into any endpoint yet — see this phase's own completion report.
"""

from decimal import Decimal

import httpx
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.core.security import hash_password
from app.db.base import Base
from app.models.order import Order, OrderStatus
from app.models.payment import Payment, PaymentProvider as PaymentProviderEnum, PaymentStatus
from app.models.refund import RefundStatus
from app.models.restaurant import Restaurant
from app.models.user import User, UserRole
from app.services.payment import refund_service
from app.services.payment.exceptions import (
    PaymentError,
    PaymentVerificationError,
    ProviderNotConfiguredError,
    ProviderRequestError,
    RefundError,
)
from app.services.payment.payment_service import PaymentService
from app.services.payment.provider import PaymentProvider, ProviderOrder, ProviderPayment, ProviderRefund
from app.services.payment.razorpay_provider import RazorpayProvider
from app.services.payment.verification import verify_hmac_signature

# ---------------------------------------------------------------------------
# Shared fixtures / helpers
# ---------------------------------------------------------------------------


@pytest.fixture()
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    Base.metadata.drop_all(engine)


def _seed_order(db, total=Decimal("230.00")) -> Order:
    owner = User(name="Owner", email="owner-svc@example.com", phone="9600000001", password_hash=hash_password("x"), role=UserRole.RESTAURANT_OWNER)
    customer = User(name="Customer", email="customer-svc@example.com", phone="9600000002", password_hash=hash_password("x"), role=UserRole.CUSTOMER)
    db.add_all([owner, customer])
    db.commit()
    restaurant = Restaurant(
        owner_id=owner.id, name="Service Diner", phone="9876543210", address="1 Road",
        latitude=Decimal("12.1"), longitude=Decimal("77.1"),
        minimum_order=Decimal("0.00"), delivery_fee=Decimal("30.00"),
    )
    db.add(restaurant)
    db.commit()
    order = Order(
        user_id=customer.id, customer_name=customer.name, customer_email=customer.email,
        restaurant_id=str(restaurant.id), restaurant_name=restaurant.name,
        order_number="ORD-SVC-0001", status=OrderStatus.PLACED,
        subtotal=total - Decimal("30.00"), delivery_fee=Decimal("30.00"), total=total,
        payment_method="cod", address_line="1 Road", city="Town", postal_code="123456",
    )
    db.add(order)
    db.commit()
    return order


class FakeProvider(PaymentProvider):
    """An in-memory stand-in used everywhere PaymentService/RefundService
    are tested — those two classes are responsible for orchestration, not
    HTTP calling, so their own tests should never depend on the network
    (RazorpayProvider gets its own, separate HTTP-mocked tests below)."""

    name = "fake"

    def __init__(
        self, *, signature_is_valid: bool = True, refund_should_fail: bool = False,
        fetch_payment_amount: Decimal | None = None, fetch_payment_currency: str | None = None,
        fetch_payment_status: str = "captured", fetch_payment_order_id: str | None = None,
        fetch_order_amount: Decimal | None = None, fetch_order_currency: str | None = None,
        refund_status: str = "processed",
    ):
        self.signature_is_valid = signature_is_valid
        self.refund_should_fail = refund_should_fail
        # Razorpay Refund (Phase 24) — a real initiate-refund call can come
        # back "processed" (settled), "pending" (accepted, not yet final),
        # or "failed" (accepted, then rejected) even without raising —
        # overridable so create_refund()'s own status mapping is tested
        # against all three, not just the always-instantly-settled default.
        self.refund_status = refund_status
        # Payment Signature/Amount Validation (Phase 14/15) — real Razorpay
        # ties an order to a fixed amount/currency at creation time, so
        # fetch_payment/fetch_order for that order naturally echo it back
        # by default; a caller can override any of these to simulate a
        # genuine provider-side mismatch or a not-yet-captured state.
        self._last_created_amount: Decimal | None = None
        self._last_created_currency: str | None = None
        self._last_created_order_id: str | None = None
        self.fetch_payment_amount_override = fetch_payment_amount
        self.fetch_payment_currency_override = fetch_payment_currency
        self.fetch_payment_status = fetch_payment_status
        self.fetch_payment_order_id_override = fetch_payment_order_id
        self.fetch_order_amount_override = fetch_order_amount
        self.fetch_order_currency_override = fetch_order_currency
        self.create_order_calls: list[dict] = []
        self.refund_calls: list[dict] = []

    def create_order(self, *, amount, currency, receipt, notes=None):
        self.create_order_calls.append({"amount": amount, "currency": currency, "receipt": receipt})
        self._last_created_amount = amount
        self._last_created_currency = currency
        self._last_created_order_id = f"order_fake_{receipt}"
        return ProviderOrder(provider_order_id=self._last_created_order_id, amount=amount, currency=currency, status="created")

    def verify_payment_signature(self, *, provider_order_id, provider_payment_id, signature):
        return self.signature_is_valid

    def fetch_payment(self, provider_payment_id):
        amount = self.fetch_payment_amount_override
        if amount is None:
            amount = self._last_created_amount if self._last_created_amount is not None else Decimal("0.00")
        currency = self.fetch_payment_currency_override or self._last_created_currency or "INR"
        order_id = (
            self.fetch_payment_order_id_override
            if self.fetch_payment_order_id_override is not None
            else self._last_created_order_id
        )
        return ProviderPayment(
            provider_payment_id=provider_payment_id, provider_order_id=order_id,
            status=self.fetch_payment_status, amount=amount, currency=currency,
        )

    def fetch_order(self, provider_order_id):
        amount = self.fetch_order_amount_override
        if amount is None:
            amount = self._last_created_amount if self._last_created_amount is not None else Decimal("0.00")
        currency = self.fetch_order_currency_override or self._last_created_currency or "INR"
        return ProviderOrder(provider_order_id=provider_order_id, amount=amount, currency=currency, status="paid")

    def initiate_refund(self, *, provider_payment_id, amount, notes=None):
        self.refund_calls.append({"provider_payment_id": provider_payment_id, "amount": amount})
        if self.refund_should_fail:
            raise ProviderRequestError("simulated provider failure")
        # Real Razorpay issues a distinct refund id per refund even against
        # the same payment (multiple partial refunds are routine) — keyed
        # only by provider_payment_id here would collide on a payment's
        # second refund, which a unique-provider-refund-id constraint
        # correctly rejects.
        provider_refund_id = f"rfnd_fake_{provider_payment_id}_{len(self.refund_calls)}"
        return ProviderRefund(provider_refund_id=provider_refund_id, status=self.refund_status, amount=amount)

    def verify_webhook_signature(self, *, payload, signature):
        return self.signature_is_valid


# ---------------------------------------------------------------------------
# verify_hmac_signature
# ---------------------------------------------------------------------------


def test_verify_hmac_signature_accepts_a_genuine_signature_and_rejects_everything_else():
    import hashlib
    import hmac

    secret = "test-secret"
    payload = "order_abc|pay_xyz"
    genuine = hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()

    assert verify_hmac_signature(payload, genuine, secret) is True
    assert verify_hmac_signature(payload, "not-the-real-signature", secret) is False
    assert verify_hmac_signature(payload, None, secret) is False
    assert verify_hmac_signature(payload, genuine, "") is False


# ---------------------------------------------------------------------------
# RazorpayProvider — real Razorpay-shaped HTTP, mocked transport (no network)
# ---------------------------------------------------------------------------


def test_razorpay_provider_refuses_to_call_out_without_credentials():
    provider = RazorpayProvider(key_id="", key_secret="")
    with pytest.raises(ProviderNotConfiguredError):
        provider.create_order(amount=Decimal("100.00"), currency="INR", receipt="order-1")


def test_razorpay_provider_create_order_sends_amount_in_paise_and_parses_the_response():
    captured_request = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured_request["method"] = request.method
        captured_request["url"] = str(request.url)
        captured_request["body"] = request.read()
        return httpx.Response(200, json={"id": "order_real123", "amount": 23000, "currency": "INR", "status": "created"})

    provider = RazorpayProvider(key_id="key_test", key_secret="secret_test", transport=httpx.MockTransport(handler))
    result = provider.create_order(amount=Decimal("230.00"), currency="INR", receipt="order-1")

    assert result.provider_order_id == "order_real123"
    assert result.amount == Decimal("230.00")
    assert captured_request["url"].endswith("/orders")
    assert b'"amount":23000' in captured_request["body"] or b'"amount": 23000' in captured_request["body"]


def test_razorpay_provider_create_order_raises_provider_request_error_on_gateway_failure():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"error": {"description": "Bad request"}})

    provider = RazorpayProvider(key_id="key_test", key_secret="secret_test", transport=httpx.MockTransport(handler))
    with pytest.raises(ProviderRequestError):
        provider.create_order(amount=Decimal("100.00"), currency="INR", receipt="order-1")


def test_razorpay_provider_verify_payment_signature():
    provider = RazorpayProvider(key_id="key_test", key_secret="secret_test")
    import hashlib
    import hmac

    genuine = hmac.new(b"secret_test", b"order_1|pay_1", hashlib.sha256).hexdigest()
    assert provider.verify_payment_signature(provider_order_id="order_1", provider_payment_id="pay_1", signature=genuine) is True
    assert provider.verify_payment_signature(provider_order_id="order_1", provider_payment_id="pay_1", signature="forged") is False


def test_razorpay_provider_fetch_payment():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/payments/pay_real123")
        return httpx.Response(200, json={
            "id": "pay_real123", "order_id": "order_real123", "status": "captured", "amount": 23000, "currency": "INR",
        })

    provider = RazorpayProvider(key_id="key_test", key_secret="secret_test", transport=httpx.MockTransport(handler))
    result = provider.fetch_payment("pay_real123")
    assert result.status == "captured"
    assert result.amount == Decimal("230.00")
    assert result.currency == "INR"
    assert result.provider_order_id == "order_real123"


def test_razorpay_provider_fetch_order():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/orders/order_real123")
        return httpx.Response(200, json={"id": "order_real123", "amount": 23000, "currency": "INR", "status": "paid"})

    provider = RazorpayProvider(key_id="key_test", key_secret="secret_test", transport=httpx.MockTransport(handler))
    result = provider.fetch_order("order_real123")
    assert result.provider_order_id == "order_real123"
    assert result.amount == Decimal("230.00")
    assert result.currency == "INR"
    assert result.status == "paid"


def test_razorpay_provider_initiate_refund():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/payments/pay_real123/refund")
        return httpx.Response(200, json={"id": "rfnd_real123", "status": "processed", "amount": 5000})

    provider = RazorpayProvider(key_id="key_test", key_secret="secret_test", transport=httpx.MockTransport(handler))
    result = provider.initiate_refund(provider_payment_id="pay_real123", amount=Decimal("50.00"))
    assert result.provider_refund_id == "rfnd_real123"
    assert result.amount == Decimal("50.00")


def test_razorpay_provider_verify_webhook_signature_requires_a_configured_secret():
    provider = RazorpayProvider(key_id="key_test", key_secret="secret_test", webhook_secret="")
    with pytest.raises(ProviderNotConfiguredError):
        provider.verify_webhook_signature(payload=b"{}", signature="whatever")


# ---------------------------------------------------------------------------
# PaymentService
# ---------------------------------------------------------------------------


def test_create_payment_for_order_cod_never_calls_a_provider(db):
    order = _seed_order(db)
    fake = FakeProvider()
    service = PaymentService(providers={"razorpay": fake})

    payment = service.create_payment_for_order(db, order=order, method="cod")

    assert payment.provider == PaymentProviderEnum.COD
    assert payment.amount == order.total
    assert fake.create_order_calls == []


def test_create_payment_for_order_is_idempotent(db):
    order = _seed_order(db)
    service = PaymentService(providers={"razorpay": FakeProvider()})

    first = service.create_payment_for_order(db, order=order, method="cod")
    second = service.create_payment_for_order(db, order=order, method="cod")

    assert first.id == second.id
    assert db.query(Payment).filter(Payment.order_id == order.id).count() == 1


def test_create_payment_for_order_online_creates_a_payment_and_attempt_via_the_provider(db):
    order = _seed_order(db)
    fake = FakeProvider()
    service = PaymentService(providers={"razorpay": fake})

    payment = service.create_payment_for_order(db, order=order, method="razorpay")

    assert payment.provider == PaymentProviderEnum.RAZORPAY
    assert payment.razorpay_order_id == f"order_fake_{order.id}"
    assert len(fake.create_order_calls) == 1
    assert fake.create_order_calls[0]["amount"] == order.total
    assert len(payment.attempts) == 1


def test_create_payment_for_order_unknown_method_raises(db):
    order = _seed_order(db)
    service = PaymentService(providers={})
    with pytest.raises(PaymentError):
        service.create_payment_for_order(db, order=order, method="razorpay")


def test_verify_payment_success_marks_paid_and_sets_paid_at(db):
    order = _seed_order(db)
    fake = FakeProvider(signature_is_valid=True)
    service = PaymentService(providers={"razorpay": fake})
    payment = service.create_payment_for_order(db, order=order, method="razorpay")

    verified = service.verify_payment(
        db, payment=payment, provider_order_id=payment.razorpay_order_id,
        provider_payment_id="pay_test_1", signature="whatever-the-fake-accepts",
    )

    assert verified.payment_status == PaymentStatus.PAID
    assert verified.is_verified is True
    assert verified.paid_at is not None
    assert any(a.status == PaymentStatus.PAID for a in verified.attempts)


def test_verify_payment_failure_marks_failed_and_records_the_attempt(db):
    order = _seed_order(db)
    fake = FakeProvider(signature_is_valid=False)
    service = PaymentService(providers={"razorpay": fake})
    payment = service.create_payment_for_order(db, order=order, method="razorpay")

    with pytest.raises(PaymentVerificationError):
        service.verify_payment(
            db, payment=payment, provider_order_id=payment.razorpay_order_id,
            provider_payment_id="pay_test_2", signature="forged",
        )

    db.refresh(payment)
    assert payment.payment_status == PaymentStatus.FAILED
    failed_attempts = [a for a in payment.attempts if a.status == PaymentStatus.FAILED]
    assert len(failed_attempts) == 1
    assert failed_attempts[0].failure_code == "SIGNATURE_MISMATCH"


def test_payment_service_refund_uses_no_provider_for_cod(db):
    order = _seed_order(db)
    fake = FakeProvider()
    service = PaymentService(providers={"razorpay": fake})
    payment = service.create_payment_for_order(db, order=order, method="cod")
    payment.payment_status = PaymentStatus.PAID
    db.commit()

    refund = service.refund(db, payment=payment, amount=Decimal("50.00"), reason="test")

    assert refund.status == RefundStatus.COMPLETED
    assert fake.refund_calls == []  # COD never calls the provider


def test_payment_service_refund_uses_the_provider_for_online_payments(db):
    order = _seed_order(db)
    fake = FakeProvider()
    service = PaymentService(providers={"razorpay": fake})
    payment = service.create_payment_for_order(db, order=order, method="razorpay")
    service.verify_payment(db, payment=payment, provider_order_id=payment.razorpay_order_id, provider_payment_id="pay_refund_test", signature="ok")

    refund = service.refund(db, payment=payment, amount=Decimal("50.00"), reason="test")

    assert refund.status == RefundStatus.COMPLETED
    assert refund.provider_refund_id == "rfnd_fake_pay_refund_test_1"
    assert len(fake.refund_calls) == 1


# ---------------------------------------------------------------------------
# refund_service.create_refund
# ---------------------------------------------------------------------------


def test_refund_rejects_a_payment_that_was_never_paid(db):
    order = _seed_order(db)
    payment = Payment(order_id=order.id, user_id=order.user_id, provider=PaymentProviderEnum.COD, amount=order.total, payment_status=PaymentStatus.PENDING)
    db.add(payment)
    db.commit()

    with pytest.raises(RefundError):
        refund_service.create_refund(db, payment=payment, amount=Decimal("10.00"), provider=None)


def test_refund_rejects_an_amount_exceeding_what_remains_refundable(db):
    order = _seed_order(db)
    payment = Payment(order_id=order.id, user_id=order.user_id, provider=PaymentProviderEnum.COD, amount=Decimal("100.00"), payment_status=PaymentStatus.PAID)
    db.add(payment)
    db.commit()

    with pytest.raises(RefundError):
        refund_service.create_refund(db, payment=payment, amount=Decimal("150.00"), provider=None)


def test_partial_refund_then_full_refund_transitions_payment_status_correctly(db):
    order = _seed_order(db)
    payment = Payment(order_id=order.id, user_id=order.user_id, provider=PaymentProviderEnum.COD, amount=Decimal("100.00"), payment_status=PaymentStatus.PAID)
    db.add(payment)
    db.commit()

    refund_service.create_refund(db, payment=payment, amount=Decimal("40.00"), provider=None)
    db.refresh(payment)
    assert payment.payment_status == PaymentStatus.PARTIALLY_REFUNDED

    refund_service.create_refund(db, payment=payment, amount=Decimal("60.00"), provider=None)
    db.refresh(payment)
    assert payment.payment_status == PaymentStatus.REFUNDED


def test_a_failed_provider_refund_marks_the_refund_row_failed_and_raises(db):
    order = _seed_order(db)
    payment = Payment(order_id=order.id, user_id=order.user_id, provider=PaymentProviderEnum.RAZORPAY, amount=Decimal("100.00"), payment_status=PaymentStatus.PAID, razorpay_payment_id="pay_will_fail")
    db.add(payment)
    db.commit()

    fake = FakeProvider(refund_should_fail=True)
    with pytest.raises(ProviderRequestError):
        refund_service.create_refund(db, payment=payment, amount=Decimal("50.00"), provider=fake)

    db.refresh(payment)
    failed = [r for r in payment.refunds if r.status == RefundStatus.FAILED]
    assert len(failed) == 1
    # The payment itself is untouched by a failed refund attempt — still PAID.
    assert payment.payment_status == PaymentStatus.PAID


def test_two_near_simultaneous_refunds_never_together_exceed_the_captured_amount(db):
    """Refund Architecture (Phase 23) — the row-lock's own genuine
    concurrency can't be exercised against SQLite (no real row-level
    locking — see this phase's live verification for that proof
    instead); this confirms the *sequential* guarantee the lock is meant
    to make airtight: each call's already_refunded is always recomputed
    fresh (db.refresh() after acquiring the lock), never a value that
    could have gone stale, so two requests can never together refund more
    than was actually captured."""
    order = _seed_order(db)
    payment = Payment(
        order_id=order.id, user_id=order.user_id, provider=PaymentProviderEnum.COD,
        amount=Decimal("100.00"), payment_status=PaymentStatus.PAID,
    )
    db.add(payment)
    db.commit()

    # First request: refunds 70 of 100, leaving 30 remaining.
    refund_service.create_refund(db, payment=payment, amount=Decimal("70.00"), provider=None)
    db.refresh(payment)
    assert payment.payment_status == PaymentStatus.PARTIALLY_REFUNDED

    # A second request for 30 is exactly the remaining amount — must
    # succeed; a request for anything more must still be rejected, proving
    # the check is against the *real*, freshly-locked total every time,
    # not a value cached from before the first refund.
    with pytest.raises(RefundError):
        refund_service.create_refund(db, payment=payment, amount=Decimal("30.01"), provider=None)

    refund_service.create_refund(db, payment=payment, amount=Decimal("30.00"), provider=None)
    db.refresh(payment)
    assert payment.payment_status == PaymentStatus.REFUNDED
    total_refunded = sum((r.amount for r in payment.refunds if r.status == RefundStatus.COMPLETED), Decimal("0.00"))
    assert total_refunded == Decimal("100.00")  # never a cent more than what was actually captured


# ---------------------------------------------------------------------------
# Razorpay Refund (Phase 24) — never mark a refund COMPLETED solely because
# the provider accepted the initiate-refund request; track its real state.
# ---------------------------------------------------------------------------


def test_online_refund_pending_at_the_provider_is_recorded_processing_not_completed(db):
    order = _seed_order(db)
    payment = Payment(
        order_id=order.id, user_id=order.user_id, provider=PaymentProviderEnum.RAZORPAY,
        amount=Decimal("100.00"), payment_status=PaymentStatus.PAID, razorpay_payment_id="pay_pending",
    )
    db.add(payment)
    db.commit()

    fake = FakeProvider(refund_status="pending")
    refund = refund_service.create_refund(db, payment=payment, amount=Decimal("40.00"), provider=fake)

    assert refund.status == RefundStatus.PROCESSING
    db.refresh(payment)
    # A merely-accepted, not-yet-settled refund must never move the parent
    # Payment's own status — it's still exactly as PAID as before.
    assert payment.payment_status == PaymentStatus.PAID


def test_online_refund_failed_at_the_provider_without_raising_is_recorded_failed(db):
    order = _seed_order(db)
    payment = Payment(
        order_id=order.id, user_id=order.user_id, provider=PaymentProviderEnum.RAZORPAY,
        amount=Decimal("100.00"), payment_status=PaymentStatus.PAID, razorpay_payment_id="pay_rejected",
    )
    db.add(payment)
    db.commit()

    fake = FakeProvider(refund_status="failed")
    refund = refund_service.create_refund(db, payment=payment, amount=Decimal("40.00"), provider=fake)

    assert refund.status == RefundStatus.FAILED
    db.refresh(payment)
    assert payment.payment_status == PaymentStatus.PAID


def test_a_refund_still_processing_blocks_a_second_refund_for_the_remaining_amount(db):
    """The amount-availability check treats PROCESSING as just as "spoken
    for" as COMPLETED — otherwise two refunds could each independently
    pass the check while only one is actually settled, and together they'd
    eventually exceed what was ever captured once both resolve."""
    order = _seed_order(db)
    payment = Payment(
        order_id=order.id, user_id=order.user_id, provider=PaymentProviderEnum.RAZORPAY,
        amount=Decimal("100.00"), payment_status=PaymentStatus.PAID, razorpay_payment_id="pay_inflight",
    )
    db.add(payment)
    db.commit()

    fake = FakeProvider(refund_status="pending")
    refund_service.create_refund(db, payment=payment, amount=Decimal("70.00"), provider=fake)
    db.refresh(payment)
    assert payment.payment_status == PaymentStatus.PAID  # still PAID — nothing settled yet

    with pytest.raises(RefundError):
        refund_service.create_refund(db, payment=payment, amount=Decimal("30.01"), provider=fake)

    # Exactly what remains (100 - 70 committed) is still accepted.
    refund_service.create_refund(db, payment=payment, amount=Decimal("30.00"), provider=fake)


def test_webhook_refund_processed_propagates_a_processing_refund_to_the_payment_status(db):
    """Mirrors webhook_service.py::_handle_refund_processed()'s own job —
    covered end to end in test_payment_webhooks.py; this confirms the same
    guarantee at the refund_service layer: recompute_payment_refund_status()
    correctly reflects a refund that was PROCESSING and has just become
    COMPLETED, exactly as the webhook handler calls it."""
    order = _seed_order(db)
    payment = Payment(
        order_id=order.id, user_id=order.user_id, provider=PaymentProviderEnum.RAZORPAY,
        amount=Decimal("100.00"), payment_status=PaymentStatus.PAID, razorpay_payment_id="pay_resolves",
    )
    db.add(payment)
    db.commit()

    fake = FakeProvider(refund_status="pending")
    refund = refund_service.create_refund(db, payment=payment, amount=Decimal("100.00"), provider=fake)
    assert refund.status == RefundStatus.PROCESSING
    db.refresh(payment)
    assert payment.payment_status == PaymentStatus.PAID

    refund.status = RefundStatus.COMPLETED
    refund_service.recompute_payment_refund_status(db, payment)
    db.commit()
    db.refresh(payment)
    assert payment.payment_status == PaymentStatus.REFUNDED
