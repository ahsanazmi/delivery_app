"""Payment System Phase 2 — Payment Domain Model.

Model-level tests only: this phase adds PaymentAttempt and Refund, extends
PaymentStatus, and adds Payment.paid_at — it deliberately does not wire any
service/API logic to populate them yet (that's later-phase work per the
master command's own phase breakdown), so these tests exercise the schema
itself (creation, constraints, relationships, enum values), not a flow.
"""

from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.core.security import hash_password
from app.db.base import Base
from app.models.order import Order, OrderStatus
from app.models.payment import Payment, PaymentProvider, PaymentStatus
from app.models.payment_attempt import PaymentAttempt
from app.models.refund import Refund, RefundStatus
from app.models.restaurant import Restaurant
from app.models.user import User, UserRole


@pytest.fixture()
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    Base.metadata.drop_all(engine)


def _seed_order(db) -> Order:
    owner = User(name="Owner", email="owner-payments@example.com", phone="9700000001", password_hash=hash_password("x"), role=UserRole.RESTAURANT_OWNER)
    customer = User(name="Customer", email="customer-payments@example.com", phone="9700000002", password_hash=hash_password("x"), role=UserRole.CUSTOMER)
    db.add_all([owner, customer])
    db.commit()
    restaurant = Restaurant(
        owner_id=owner.id, name="Payments Diner", phone="9876543210", address="1 Road",
        latitude=Decimal("12.1"), longitude=Decimal("77.1"),
        minimum_order=Decimal("0.00"), delivery_fee=Decimal("30.00"),
    )
    db.add(restaurant)
    db.commit()
    order = Order(
        user_id=customer.id, customer_name=customer.name, customer_email=customer.email,
        restaurant_id=str(restaurant.id), restaurant_name=restaurant.name,
        order_number="ORD-TEST-0001", status=OrderStatus.PLACED,
        subtotal=Decimal("200.00"), delivery_fee=Decimal("30.00"), total=Decimal("230.00"),
        payment_method="cod", address_line="1 Road", city="Town", postal_code="123456",
    )
    db.add(order)
    db.commit()
    return order, customer


def test_payment_status_enum_covers_the_extended_values(db):
    """PROCESSING, CANCELLED, and PARTIALLY_REFUNDED are new; the original
    five values must still all be present too — this is an extension, not
    a replacement (Phase 1's own recommendation)."""
    expected = {"pending", "processing", "paid", "failed", "cancelled", "refund_pending", "partially_refunded", "refunded"}
    actual = {member.value for member in PaymentStatus}
    assert actual == expected


def test_payment_has_paid_at_and_attempt_refund_relationships(db):
    order, customer = _seed_order(db)
    payment = Payment(order_id=order.id, user_id=customer.id, provider=PaymentProvider.RAZORPAY, amount=order.total)
    db.add(payment)
    db.commit()
    db.refresh(payment)

    assert payment.paid_at is None  # nothing sets it yet — that's later-phase work
    assert payment.attempts == []
    assert payment.refunds == []


def test_payment_attempt_creation_and_fields(db):
    order, customer = _seed_order(db)
    payment = Payment(order_id=order.id, user_id=customer.id, provider=PaymentProvider.RAZORPAY, amount=order.total)
    db.add(payment)
    db.commit()

    attempt = PaymentAttempt(
        payment_id=payment.id, provider=PaymentProvider.RAZORPAY,
        provider_order_id="order_abc123", provider_payment_id="pay_abc123",
        amount=order.total, status=PaymentStatus.FAILED,
        failure_code="BAD_REQUEST_ERROR", failure_message="Signature mismatch",
    )
    db.add(attempt)
    db.commit()
    db.refresh(payment)

    assert len(payment.attempts) == 1
    assert payment.attempts[0].failure_code == "BAD_REQUEST_ERROR"
    assert isinstance(payment.attempts[0].amount, Decimal)


def test_payment_attempt_amount_cannot_be_negative(db):
    order, customer = _seed_order(db)
    payment = Payment(order_id=order.id, user_id=customer.id, provider=PaymentProvider.RAZORPAY, amount=order.total)
    db.add(payment)
    db.commit()

    db.add(PaymentAttempt(payment_id=payment.id, provider=PaymentProvider.RAZORPAY, amount=Decimal("-1.00"), status=PaymentStatus.FAILED))
    with pytest.raises(IntegrityError):
        db.commit()


def test_deleting_a_payment_cascades_to_its_attempts(db):
    order, customer = _seed_order(db)
    payment = Payment(order_id=order.id, user_id=customer.id, provider=PaymentProvider.RAZORPAY, amount=order.total)
    db.add(payment)
    db.commit()
    db.add(PaymentAttempt(payment_id=payment.id, provider=PaymentProvider.RAZORPAY, amount=order.total, status=PaymentStatus.PENDING))
    db.commit()

    payment_id = payment.id
    db.delete(payment)
    db.commit()

    assert db.query(PaymentAttempt).filter(PaymentAttempt.payment_id == payment_id).count() == 0


def test_refund_creation_and_defaults(db):
    order, customer = _seed_order(db)
    payment = Payment(order_id=order.id, user_id=customer.id, provider=PaymentProvider.RAZORPAY, amount=order.total, payment_status=PaymentStatus.PAID)
    db.add(payment)
    db.commit()

    refund = Refund(payment_id=payment.id, order_id=order.id, amount=Decimal("50.00"), reason="Customer requested partial refund")
    db.add(refund)
    db.commit()
    db.refresh(payment)

    assert refund.status == RefundStatus.PENDING  # the model-level default
    assert len(payment.refunds) == 1
    assert payment.refunds[0].order_id == order.id


def test_refund_amount_cannot_be_negative(db):
    order, customer = _seed_order(db)
    payment = Payment(order_id=order.id, user_id=customer.id, provider=PaymentProvider.RAZORPAY, amount=order.total)
    db.add(payment)
    db.commit()

    db.add(Refund(payment_id=payment.id, order_id=order.id, amount=Decimal("-10.00")))
    with pytest.raises(IntegrityError):
        db.commit()


def test_multiple_refunds_can_exist_against_the_same_payment():
    """A partial refund followed by another partial refund — this is
    exactly the scenario the old refund_id/refund_status pair on Payment
    alone couldn't represent."""
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        order, customer = _seed_order(db)
        payment = Payment(order_id=order.id, user_id=customer.id, provider=PaymentProvider.RAZORPAY, amount=Decimal("230.00"), payment_status=PaymentStatus.PAID)
        db.add(payment)
        db.commit()

        db.add(Refund(payment_id=payment.id, order_id=order.id, amount=Decimal("30.00"), status=RefundStatus.COMPLETED))
        db.add(Refund(payment_id=payment.id, order_id=order.id, amount=Decimal("20.00"), status=RefundStatus.PENDING))
        db.commit()
        db.refresh(payment)

        assert len(payment.refunds) == 2
        assert sum((r.amount for r in payment.refunds), Decimal("0.00")) == Decimal("50.00")
    Base.metadata.drop_all(engine)


# ---------------------------------------------------------------------------
# Database Migrations (Phase 3) — provider-id uniqueness
# ---------------------------------------------------------------------------


def test_two_cod_payments_never_collide_on_null_provider_ids(db):
    """COD payments never set razorpay_order_id/razorpay_payment_id — the
    unique constraint must not treat two NULLs as a conflict, or every
    second COD order would fail to record a payment."""
    order_a, customer = _seed_order(db)
    db.add(Payment(order_id=order_a.id, user_id=customer.id, provider=PaymentProvider.COD, amount=order_a.total))
    db.commit()

    order_b = Order(
        user_id=customer.id, customer_name=customer.name, customer_email=customer.email,
        restaurant_id=order_a.restaurant_id, restaurant_name=order_a.restaurant_name,
        order_number="ORD-TEST-0002", status=OrderStatus.PLACED,
        subtotal=Decimal("100.00"), delivery_fee=Decimal("30.00"), total=Decimal("130.00"),
        payment_method="cod", address_line="1 Road", city="Town", postal_code="123456",
    )
    db.add(order_b)
    db.commit()
    db.add(Payment(order_id=order_b.id, user_id=customer.id, provider=PaymentProvider.COD, amount=order_b.total))
    db.commit()  # must not raise — two COD payments, both with NULL provider ids


def test_the_same_razorpay_payment_id_cannot_be_claimed_by_two_payments(db):
    """The replay/double-claim scenario this constraint exists for: a real
    (provider, razorpay_payment_id) pair must never end up attached to two
    different Payment rows, even for two different orders."""
    order_a, customer = _seed_order(db)
    db.add(Payment(
        order_id=order_a.id, user_id=customer.id, provider=PaymentProvider.RAZORPAY,
        amount=order_a.total, razorpay_order_id="order_shared", razorpay_payment_id="pay_shared",
    ))
    db.commit()

    order_b = Order(
        user_id=customer.id, customer_name=customer.name, customer_email=customer.email,
        restaurant_id=order_a.restaurant_id, restaurant_name=order_a.restaurant_name,
        order_number="ORD-TEST-0003", status=OrderStatus.PLACED,
        subtotal=Decimal("100.00"), delivery_fee=Decimal("30.00"), total=Decimal("130.00"),
        payment_method="cod", address_line="1 Road", city="Town", postal_code="123456",
    )
    db.add(order_b)
    db.commit()
    db.add(Payment(
        order_id=order_b.id, user_id=customer.id, provider=PaymentProvider.RAZORPAY,
        amount=order_b.total, razorpay_order_id="order_shared", razorpay_payment_id="pay_shared",
    ))
    with pytest.raises(IntegrityError):
        db.commit()


def test_multiple_payment_attempts_may_legitimately_share_one_provider_order_id(db):
    """A declined card followed by a retry with a different card — both
    attempts reference the same Razorpay order id. This must succeed."""
    order, customer = _seed_order(db)
    payment = Payment(order_id=order.id, user_id=customer.id, provider=PaymentProvider.RAZORPAY, amount=order.total)
    db.add(payment)
    db.commit()

    db.add(PaymentAttempt(
        payment_id=payment.id, provider=PaymentProvider.RAZORPAY, provider_order_id="order_retry_shared",
        provider_payment_id="pay_attempt_1", amount=order.total, status=PaymentStatus.FAILED,
    ))
    db.add(PaymentAttempt(
        payment_id=payment.id, provider=PaymentProvider.RAZORPAY, provider_order_id="order_retry_shared",
        provider_payment_id="pay_attempt_2", amount=order.total, status=PaymentStatus.PAID,
    ))
    db.commit()  # must not raise — same provider_order_id, two legitimate attempts

    assert len(payment.attempts) == 2


def test_the_same_provider_payment_id_cannot_appear_on_two_attempts(db):
    order, customer = _seed_order(db)
    payment = Payment(order_id=order.id, user_id=customer.id, provider=PaymentProvider.RAZORPAY, amount=order.total)
    db.add(payment)
    db.commit()

    db.add(PaymentAttempt(payment_id=payment.id, provider=PaymentProvider.RAZORPAY, provider_payment_id="pay_dup", amount=order.total, status=PaymentStatus.PAID))
    db.commit()
    db.add(PaymentAttempt(payment_id=payment.id, provider=PaymentProvider.RAZORPAY, provider_payment_id="pay_dup", amount=order.total, status=PaymentStatus.FAILED))
    with pytest.raises(IntegrityError):
        db.commit()


def test_the_same_provider_refund_id_cannot_appear_on_two_refunds(db):
    order, customer = _seed_order(db)
    payment = Payment(order_id=order.id, user_id=customer.id, provider=PaymentProvider.RAZORPAY, amount=order.total, payment_status=PaymentStatus.PAID)
    db.add(payment)
    db.commit()

    db.add(Refund(payment_id=payment.id, order_id=order.id, amount=Decimal("10.00"), provider_refund_id="rfnd_dup"))
    db.commit()
    db.add(Refund(payment_id=payment.id, order_id=order.id, amount=Decimal("10.00"), provider_refund_id="rfnd_dup"))
    with pytest.raises(IntegrityError):
        db.commit()
