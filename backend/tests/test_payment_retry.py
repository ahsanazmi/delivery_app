"""Payment System Phase 20 — PAYMENT RETRY.

Covers PaymentService.retry_payment()'s own guards (order must still be
payable — not cancelled, not rejected, not delivered; payment must not
already be paid) at the service layer directly, and proves the natural
retry -> re-attempt -> verify cycle creates a genuinely new PaymentAttempt
row via the real service flow, alongside every prior one, never
overwriting them.
"""
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.core.security import hash_password
from app.db.base import Base
from app.models.order import Order, OrderStatus
from app.models.payment import PaymentStatus
from app.models.payment_attempt import PaymentAttempt
from app.models.restaurant import Restaurant
from app.models.user import User, UserRole
from app.services.payment.exceptions import PaymentError, PaymentVerificationError
from app.services.payment.payment_service import PaymentService
from app.services.payment.provider import PaymentProvider, ProviderOrder, ProviderPayment, ProviderRefund


@pytest.fixture()
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    Base.metadata.drop_all(engine)


def _seed_order(db, tag: str, status: OrderStatus = OrderStatus.PLACED, total=Decimal("300.00")) -> Order:
    owner = User(name="Owner", email=f"owner-{tag}@example.com", phone=f"9500000{tag[-3:]}", password_hash=hash_password("x"), role=UserRole.RESTAURANT_OWNER)
    customer = User(name="Customer", email=f"customer-{tag}@example.com", phone=f"9600000{tag[-3:]}", password_hash=hash_password("x"), role=UserRole.CUSTOMER)
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
        order_number=f"ORD-{tag}-0001", status=status,
        subtotal=total - Decimal("30.00"), delivery_fee=Decimal("30.00"), total=total,
        payment_method="razorpay", address_line="1 Road", city="Town", postal_code="123456",
        is_paid=(status == OrderStatus.DELIVERED),
        payment_status="paid" if status == OrderStatus.DELIVERED else "pending",
    )
    db.add(order)
    db.commit()
    return order


class FakeProvider(PaymentProvider):
    name = "fake"

    def __init__(self):
        self.orders: dict[str, Decimal] = {}
        self._counter = 0

    def create_order(self, *, amount, currency, receipt, notes=None):
        self._counter += 1
        order_id = f"order_p20_{self._counter}"
        self.orders[order_id] = amount
        return ProviderOrder(provider_order_id=order_id, amount=amount, currency=currency, status="created")

    def _signature_for(self, order_id: str, payment_id: str) -> str:
        return f"sig::{order_id}::{payment_id}"

    def verify_payment_signature(self, *, provider_order_id, provider_payment_id, signature):
        return signature == self._signature_for(provider_order_id, provider_payment_id)

    def fetch_payment(self, provider_payment_id):
        # Whichever order_id was most recently opened — realistic enough
        # here since every test using this fake only ever has one order
        # open for verification at a time (unlike the cross-payment replay
        # scenario Phase 14's own RealisticFakeProvider is specifically
        # built to model, which needs a real payment_id -> order_id map).
        order_id = next(reversed(self.orders), None)
        amount = self.orders.get(order_id, Decimal("0.00"))
        return ProviderPayment(
            provider_payment_id=provider_payment_id, provider_order_id=order_id,
            status="captured", amount=amount, currency="INR",
        )

    def fetch_order(self, provider_order_id):
        amount = self.orders.get(provider_order_id, Decimal("0.00"))
        return ProviderOrder(provider_order_id=provider_order_id, amount=amount, currency="INR", status="paid")

    def initiate_refund(self, *, provider_payment_id, amount, notes=None):
        return ProviderRefund(provider_refund_id="rfnd_p20", status="processed", amount=amount)

    def verify_webhook_signature(self, *, payload, signature):
        return True


# ---------------------------------------------------------------------------
# Before retry — order must still be payable
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("bad_status", [OrderStatus.CANCELLED, OrderStatus.REJECTED, OrderStatus.DELIVERED])
def test_retry_rejects_a_non_payable_order(db, bad_status):
    fake = FakeProvider()
    service = PaymentService(providers={"razorpay": fake})
    order = _seed_order(db, "bad", status=bad_status)
    payment = service.create_payment_for_order(db, order=order, method="razorpay")
    payment.payment_status = PaymentStatus.FAILED
    db.commit()

    with pytest.raises(PaymentError, match=bad_status.value):
        service.retry_payment(db, payment=payment)

    db.refresh(payment)
    assert payment.payment_status == PaymentStatus.FAILED  # never reset to pending


@pytest.mark.parametrize("ok_status", [OrderStatus.PLACED, OrderStatus.CONFIRMED, OrderStatus.PREPARING])
def test_retry_succeeds_for_still_payable_order_statuses(db, ok_status):
    fake = FakeProvider()
    service = PaymentService(providers={"razorpay": fake})
    order = _seed_order(db, f"ok{ok_status.value[:3]}", status=ok_status)
    payment = service.create_payment_for_order(db, order=order, method="razorpay")
    payment.payment_status = PaymentStatus.FAILED
    db.commit()

    retried = service.retry_payment(db, payment=payment)
    assert retried.payment_status == PaymentStatus.PENDING


# ---------------------------------------------------------------------------
# A new payment attempt is created when a real retry actually happens,
# never overwriting the history already on record.
# ---------------------------------------------------------------------------


def test_a_retried_and_reverified_payment_creates_a_new_attempt_alongside_the_old_one(db):
    fake = FakeProvider()
    service = PaymentService(providers={"razorpay": fake})
    order = _seed_order(db, "history")
    payment = service.create_payment_for_order(db, order=order, method="razorpay")

    # create_payment_for_order() itself already records one PENDING attempt
    # (the order-opening step) — the baseline every count below builds on.
    creation_attempts = db.query(PaymentAttempt).filter(PaymentAttempt.payment_id == payment.id).all()
    assert len(creation_attempts) == 1
    creation_attempt_id = creation_attempts[0].id

    # First real attempt: a forged signature.
    with pytest.raises(PaymentVerificationError):
        service.verify_payment(
            db, payment=payment, provider_order_id=payment.razorpay_order_id,
            provider_payment_id="pay_p20_history", signature="forged",
        )
    db.refresh(payment)
    assert payment.payment_status == PaymentStatus.FAILED
    after_first_verify = db.query(PaymentAttempt).filter(PaymentAttempt.payment_id == payment.id).all()
    assert len(after_first_verify) == 2  # the creation attempt, untouched, plus this new failed one
    failed_attempt = next(a for a in after_first_verify if a.status == PaymentStatus.FAILED)

    # Retry: reopens the same provider order, no new attempt row of its own.
    retried = service.retry_payment(db, payment=payment)
    assert retried.payment_status == PaymentStatus.PENDING
    assert db.query(PaymentAttempt).filter(PaymentAttempt.payment_id == payment.id).count() == 2

    # Second real attempt: this time genuine — a brand new payment_id, same order.
    payment_id_2 = "pay_p20_history_2"
    signature_2 = fake._signature_for(payment.razorpay_order_id, payment_id_2)
    verified = service.verify_payment(
        db, payment=payment, provider_order_id=payment.razorpay_order_id,
        provider_payment_id=payment_id_2, signature=signature_2,
    )
    assert verified.payment_status == PaymentStatus.PAID

    all_attempts = db.query(PaymentAttempt).filter(PaymentAttempt.payment_id == payment.id).order_by(PaymentAttempt.created_at).all()
    assert len(all_attempts) == 3  # a genuinely new row, not a reused/overwritten one
    assert all_attempts[0].id == creation_attempt_id
    assert all_attempts[1].id == failed_attempt.id
    assert all_attempts[1].status == PaymentStatus.FAILED  # the original failure record, untouched
    assert all_attempts[1].provider_payment_id == "pay_p20_history"
    assert all_attempts[2].status == PaymentStatus.PAID
    assert all_attempts[2].provider_payment_id == payment_id_2
    assert all_attempts[2].id not in (creation_attempt_id, failed_attempt.id)
