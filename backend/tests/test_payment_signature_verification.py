"""Payment System Phase 14 — PAYMENT SIGNATURE VERIFICATION.

Proves the three independent checks PaymentService.verify_payment() now
enforces, in order: the provider_order_id belongs to *this* payment (never
just any genuinely-signed order/payment pair), the HMAC signature itself
is genuine, and the amount Razorpay confirms via fetch_payment() matches
this order's own total. Also proves the exact replay scenario that
motivated the order-id check: a real, validly-signed (order_id,
payment_id, signature) triple from one payment can never be used to mark
a *different* payment PAID.
"""
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.core.security import hash_password
from app.db.base import Base
from app.models.order import Order, OrderStatus
from app.models.payment import Payment, PaymentStatus
from app.models.restaurant import Restaurant
from app.models.user import User, UserRole
from app.services.payment.exceptions import PaymentVerificationError
from app.services.payment.payment_service import PaymentService
from app.services.payment.provider import PaymentProvider, ProviderOrder, ProviderPayment, ProviderRefund


@pytest.fixture()
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    Base.metadata.drop_all(engine)


def _seed_order(db, tag: str, total=Decimal("230.00")) -> Order:
    owner = User(name="Owner", email=f"owner-{tag}@example.com", phone=f"96000000{tag[-2:]}", password_hash=hash_password("x"), role=UserRole.RESTAURANT_OWNER)
    customer = User(name="Customer", email=f"customer-{tag}@example.com", phone=f"97000000{tag[-2:]}", password_hash=hash_password("x"), role=UserRole.CUSTOMER)
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
        order_number=f"ORD-{tag}-0001", status=OrderStatus.PLACED,
        subtotal=total - Decimal("30.00"), delivery_fee=Decimal("30.00"), total=total,
        payment_method="razorpay", address_line="1 Road", city="Town", postal_code="123456",
    )
    db.add(order)
    db.commit()
    return order


class RealisticFakeProvider(PaymentProvider):
    """Unlike test_payment_service_architecture.py's FakeProvider, this one
    genuinely ties each order_id to the amount it was created with and
    signs (order_id, payment_id) pairs deterministically — close enough to
    Razorpay's real behavior to make a genuine cross-payment replay
    attempt meaningful to test, not just something ruled out by
    construction."""

    name = "realistic-fake"

    def __init__(self):
        self.orders: dict[str, Decimal] = {}
        self.order_currencies: dict[str, str] = {}
        # Payment Amount Validation (Phase 15) — a per-order override,
        # distinct from self.orders (the order's own amount), so a test
        # can simulate the *payment* side reporting something different
        # from the *order* side without conflating the two checks.
        self.payment_amount_overrides: dict[str, Decimal] = {}
        self.payment_currency_overrides: dict[str, str] = {}
        self.payment_status_overrides: dict[str, str] = {}
        self._counter = 0

    def create_order(self, *, amount, currency, receipt, notes=None):
        self._counter += 1
        order_id = f"order_real_{self._counter}"
        self.orders[order_id] = amount
        self.order_currencies[order_id] = currency
        return ProviderOrder(provider_order_id=order_id, amount=amount, currency=currency, status="created")

    def _signature_for(self, order_id: str, payment_id: str) -> str:
        return f"sig::{order_id}::{payment_id}"

    def verify_payment_signature(self, *, provider_order_id, provider_payment_id, signature):
        return signature == self._signature_for(provider_order_id, provider_payment_id)

    def fetch_payment(self, provider_payment_id):
        # provider_payment_id encodes which order it was captured for, so
        # fetch_payment can honestly report that order's own amount by
        # default — matching how a real captured Razorpay payment is
        # always tied to one specific order's fixed amount.
        order_id = provider_payment_id.replace("pay_", "order_", 1) if provider_payment_id.startswith("pay_real_") else None
        amount = self.payment_amount_overrides.get(provider_payment_id)
        if amount is None:
            amount = self.orders.get(order_id, Decimal("0.00")) if order_id else Decimal("0.00")
        currency = self.payment_currency_overrides.get(provider_payment_id) or (
            self.order_currencies.get(order_id, "INR") if order_id else "INR"
        )
        status = self.payment_status_overrides.get(provider_payment_id, "captured")
        return ProviderPayment(
            provider_payment_id=provider_payment_id, provider_order_id=order_id,
            status=status, amount=amount, currency=currency,
        )

    def fetch_order(self, provider_order_id):
        amount = self.orders.get(provider_order_id, Decimal("0.00"))
        currency = self.order_currencies.get(provider_order_id, "INR")
        return ProviderOrder(provider_order_id=provider_order_id, amount=amount, currency=currency, status="paid")

    def initiate_refund(self, *, provider_payment_id, amount, notes=None):
        return ProviderRefund(provider_refund_id="rfnd_real", status="processed", amount=amount)

    def verify_webhook_signature(self, *, payload, signature):
        return True


def _genuine_result_for(fake: RealisticFakeProvider, order_id: str):
    payment_id = order_id.replace("order_", "pay_", 1)
    return order_id, payment_id, fake._signature_for(order_id, payment_id)


def test_validates_expected_order_rejects_a_genuinely_valid_signature_for_a_different_payment(db):
    """The exact replay this phase's own audit found missing: a customer
    completes a real, cheap payment (order B), then tries to point that
    real (order_id, payment_id, signature) triple at a different,
    unrelated, expensive payment (order A) they also own."""
    fake = RealisticFakeProvider()
    service = PaymentService(providers={"razorpay": fake})

    order_a = _seed_order(db, "a", total=Decimal("5000.00"))
    order_b = _seed_order(db, "b", total=Decimal("40.00"))
    payment_a = service.create_payment_for_order(db, order=order_a, method="razorpay")
    payment_b = service.create_payment_for_order(db, order=order_b, method="razorpay")

    # Customer genuinely, legitimately pays for the CHEAP order B.
    order_id_b, payment_id_b, signature_b = _genuine_result_for(fake, payment_b.razorpay_order_id)
    verified_b = service.verify_payment(
        db, payment=payment_b, provider_order_id=order_id_b, provider_payment_id=payment_id_b, signature=signature_b,
    )
    assert verified_b.payment_status == PaymentStatus.PAID

    # Now replay that same, genuinely-valid triple against the EXPENSIVE order A.
    with pytest.raises(PaymentVerificationError):
        service.verify_payment(
            db, payment=payment_a, provider_order_id=order_id_b, provider_payment_id=payment_id_b, signature=signature_b,
        )

    db.refresh(payment_a)
    assert payment_a.payment_status == PaymentStatus.FAILED
    # The audit-trail PaymentAttempt row itself collides here (this exact
    # provider_payment_id is already recorded against payment_b's own
    # successful attempt) — the important guarantee is that this resolves
    # to a clean rejection rather than an unhandled crash, not that a
    # second attempt row necessarily exists for the same provider id.
    assert payment_a.failure_reason
    # And, decisively: payment_a was never actually marked PAID by the replay.
    assert payment_a.razorpay_payment_id is None


def test_validates_expected_order_before_ever_checking_the_signature(db):
    """A wrong order_id is rejected on its own — not merely because the
    signature also happens not to verify against it."""
    fake = RealisticFakeProvider()
    service = PaymentService(providers={"razorpay": fake})
    order = _seed_order(db, "c")
    payment = service.create_payment_for_order(db, order=order, method="razorpay")

    with pytest.raises(PaymentVerificationError):
        service.verify_payment(
            db, payment=payment, provider_order_id="order_not_mine", provider_payment_id="pay_not_mine",
            signature=fake._signature_for("order_not_mine", "pay_not_mine"),  # a genuinely-correct signature for THAT pair
        )
    db.refresh(payment)
    failed = [a for a in payment.attempts if a.status == PaymentStatus.FAILED][0]
    assert failed.failure_code == "ORDER_MISMATCH"


def test_verifies_signature_after_order_matches(db):
    fake = RealisticFakeProvider()
    service = PaymentService(providers={"razorpay": fake})
    order = _seed_order(db, "d")
    payment = service.create_payment_for_order(db, order=order, method="razorpay")

    with pytest.raises(PaymentVerificationError):
        service.verify_payment(
            db, payment=payment, provider_order_id=payment.razorpay_order_id,
            provider_payment_id="pay_real_wrong", signature="totally-forged",
        )
    db.refresh(payment)
    failed = [a for a in payment.attempts if a.status == PaymentStatus.FAILED][0]
    assert failed.failure_code == "SIGNATURE_MISMATCH"


def test_validates_expected_amount_against_the_provider_independently(db):
    """Even with a matching order_id and a genuine signature, a captured
    amount that doesn't match this order's own total must still fail —
    defense in depth beyond the order/signature checks alone."""
    fake = RealisticFakeProvider()
    service = PaymentService(providers={"razorpay": fake})
    order = _seed_order(db, "e", total=Decimal("500.00"))
    payment = service.create_payment_for_order(db, order=order, method="razorpay")
    # Tamper with what the provider will report as captured for this exact order.
    fake.orders[payment.razorpay_order_id] = Decimal("1.00")

    order_id, payment_id, signature = _genuine_result_for(fake, payment.razorpay_order_id)
    with pytest.raises(PaymentVerificationError):
        service.verify_payment(db, payment=payment, provider_order_id=order_id, provider_payment_id=payment_id, signature=signature)

    db.refresh(payment)
    assert payment.payment_status == PaymentStatus.FAILED
    failed = [a for a in payment.attempts if a.status == PaymentStatus.FAILED][0]
    assert failed.failure_code == "AMOUNT_MISMATCH"


def test_all_three_checks_passing_marks_paid(db):
    fake = RealisticFakeProvider()
    service = PaymentService(providers={"razorpay": fake})
    order = _seed_order(db, "f", total=Decimal("777.00"))
    payment = service.create_payment_for_order(db, order=order, method="razorpay")

    order_id, payment_id, signature = _genuine_result_for(fake, payment.razorpay_order_id)
    verified = service.verify_payment(db, payment=payment, provider_order_id=order_id, provider_payment_id=payment_id, signature=signature)

    assert verified.payment_status == PaymentStatus.PAID
    assert verified.is_verified is True
    assert verified.paid_at is not None
    assert verified.razorpay_order_id == payment.razorpay_order_id  # never reassigned from client input


# ---------------------------------------------------------------------------
# Payment Amount Validation (Phase 15) — currency, provider-reported payment
# state, and the independent Razorpay *order* amount/currency check, on top
# of Phase 14's order-id/signature/payment-amount checks.
# ---------------------------------------------------------------------------


def test_a_captured_payment_amount_that_disagrees_with_the_order_amount_is_rejected(db):
    """The order and the payment can each independently report a
    different (tampered/drifted) amount — either one disagreeing with
    this Payment's own total must fail verification."""
    fake = RealisticFakeProvider()
    service = PaymentService(providers={"razorpay": fake})
    order = _seed_order(db, "g", total=Decimal("300.00"))
    payment = service.create_payment_for_order(db, order=order, method="razorpay")
    order_id, payment_id, signature = _genuine_result_for(fake, payment.razorpay_order_id)
    # The order's own amount matches, but the payment reports something else.
    fake.payment_amount_overrides[payment_id] = Decimal("299.00")

    with pytest.raises(PaymentVerificationError):
        service.verify_payment(db, payment=payment, provider_order_id=order_id, provider_payment_id=payment_id, signature=signature)

    db.refresh(payment)
    assert payment.payment_status == PaymentStatus.FAILED
    failed = [a for a in payment.attempts if a.status == PaymentStatus.FAILED][0]
    assert failed.failure_code == "AMOUNT_MISMATCH"


def test_currency_mismatch_is_rejected(db):
    fake = RealisticFakeProvider()
    service = PaymentService(providers={"razorpay": fake})
    order = _seed_order(db, "h", total=Decimal("300.00"))
    payment = service.create_payment_for_order(db, order=order, method="razorpay")
    order_id, payment_id, signature = _genuine_result_for(fake, payment.razorpay_order_id)
    fake.payment_currency_overrides[payment_id] = "USD"

    with pytest.raises(PaymentVerificationError):
        service.verify_payment(db, payment=payment, provider_order_id=order_id, provider_payment_id=payment_id, signature=signature)

    db.refresh(payment)
    assert payment.payment_status == PaymentStatus.FAILED
    failed = [a for a in payment.attempts if a.status == PaymentStatus.FAILED][0]
    assert failed.failure_code == "CURRENCY_MISMATCH"


def test_a_not_yet_captured_payment_state_is_rejected_even_with_a_valid_signature(db):
    """Razorpay's own "authorized but not captured" state must never be
    accepted as paid — money hasn't actually settled yet."""
    fake = RealisticFakeProvider()
    service = PaymentService(providers={"razorpay": fake})
    order = _seed_order(db, "i", total=Decimal("300.00"))
    payment = service.create_payment_for_order(db, order=order, method="razorpay")
    order_id, payment_id, signature = _genuine_result_for(fake, payment.razorpay_order_id)
    fake.payment_status_overrides[payment_id] = "authorized"

    with pytest.raises(PaymentVerificationError):
        service.verify_payment(db, payment=payment, provider_order_id=order_id, provider_payment_id=payment_id, signature=signature)

    db.refresh(payment)
    assert payment.payment_status == PaymentStatus.FAILED
    failed = [a for a in payment.attempts if a.status == PaymentStatus.FAILED][0]
    assert failed.failure_code == "PAYMENT_NOT_CAPTURED"


def test_the_providers_own_reported_order_id_for_the_payment_must_also_match(db):
    """Beyond the client-submitted order_id matching (already covered),
    Razorpay's own fetch_payment response reporting a *different* order_id
    for this payment_id than what was claimed must also be caught."""
    fake = RealisticFakeProvider()
    service = PaymentService(providers={"razorpay": fake})
    order = _seed_order(db, "j", total=Decimal("300.00"))
    payment = service.create_payment_for_order(db, order=order, method="razorpay")
    order_id, payment_id, signature = _genuine_result_for(fake, payment.razorpay_order_id)
    # Simulate Razorpay's own fetch_payment response reporting a different
    # order_id than the one this payment_id was genuinely signed against.
    real_fetch_payment = fake.fetch_payment

    def patched(provider_payment_id):
        result = real_fetch_payment(provider_payment_id)
        return ProviderPayment(
            provider_payment_id=result.provider_payment_id, provider_order_id="order_real_someone_else",
            status=result.status, amount=result.amount, currency=result.currency,
        )

    fake.fetch_payment = patched  # type: ignore[method-assign]

    with pytest.raises(PaymentVerificationError):
        service.verify_payment(db, payment=payment, provider_order_id=order_id, provider_payment_id=payment_id, signature=signature)

    db.refresh(payment)
    assert payment.payment_status == PaymentStatus.FAILED
    failed = [a for a in payment.attempts if a.status == PaymentStatus.FAILED][0]
    assert failed.failure_code == "ORDER_MISMATCH"


def test_amount_mismatch_never_marks_the_payment_paid_and_leaves_a_clear_audit_trail(db, caplog):
    """The phase's own closing requirement: a clear error and an
    audit/log record, never a silent or partial acceptance."""
    import logging

    fake = RealisticFakeProvider()
    service = PaymentService(providers={"razorpay": fake})
    order = _seed_order(db, "k", total=Decimal("450.00"))
    payment = service.create_payment_for_order(db, order=order, method="razorpay")
    order_id, payment_id, signature = _genuine_result_for(fake, payment.razorpay_order_id)
    fake.orders[payment.razorpay_order_id] = Decimal("1.00")

    with caplog.at_level(logging.WARNING):
        with pytest.raises(PaymentVerificationError):
            service.verify_payment(db, payment=payment, provider_order_id=order_id, provider_payment_id=payment_id, signature=signature)

    db.refresh(payment)
    assert payment.payment_status != PaymentStatus.PAID
    assert payment.is_verified is False
    assert payment.failure_reason
    assert any("AMOUNT_MISMATCH" in r.message for r in caplog.records)
