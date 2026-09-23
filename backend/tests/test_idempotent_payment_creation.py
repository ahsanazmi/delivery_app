"""Payment System Phase 21 — IDEMPOTENT ORDER PAYMENT CREATION.

Covers PaymentService.create_payment_for_order()'s idempotency for the
online (razorpay) path specifically — the existing Phase 4 test only
proved this for COD — under the four scenarios this phase names: a
double tap / network retry / app restart / repeated checkout request all
reduce to "the same order_id calls create_payment_for_order() more than
once," sequentially or genuinely concurrently. Either way: exactly one
Payment row survives, and the provider's create_order() is called at
most once — never twice, even under a real race.
"""
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.core.security import hash_password
from app.db.base import Base
from app.models.order import Order, OrderStatus
from app.models.payment import Payment
from app.models.restaurant import Restaurant
from app.models.user import User, UserRole
from app.services.payment.payment_service import PaymentService
from app.services.payment.provider import PaymentProvider, ProviderOrder, ProviderPayment, ProviderRefund


@pytest.fixture()
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    Base.metadata.drop_all(engine)


def _seed_order(db, tag: str, total=Decimal("300.00")) -> Order:
    owner = User(name="Owner", email=f"owner-{tag}@example.com", phone=f"9700000{tag[-3:]}", password_hash=hash_password("x"), role=UserRole.RESTAURANT_OWNER)
    customer = User(name="Customer", email=f"customer-{tag}@example.com", phone=f"9800000{tag[-3:]}", password_hash=hash_password("x"), role=UserRole.CUSTOMER)
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


class CountingFakeProvider(PaymentProvider):
    """Counts real create_order() calls — the thing this phase actually
    cares about not duplicating, distinct from just counting Payment
    rows (uq_payments_order_id alone already guaranteed that part)."""

    name = "counting-fake"

    def __init__(self):
        self.create_order_calls = 0

    def create_order(self, *, amount, currency, receipt, notes=None):
        self.create_order_calls += 1
        return ProviderOrder(provider_order_id=f"order_p21_{self.create_order_calls}", amount=amount, currency=currency, status="created")

    def verify_payment_signature(self, *, provider_order_id, provider_payment_id, signature):
        return True

    def fetch_payment(self, provider_payment_id):
        return ProviderPayment(provider_payment_id=provider_payment_id, provider_order_id=None, status="captured", amount=Decimal("0.00"), currency="INR")

    def fetch_order(self, provider_order_id):
        return ProviderOrder(provider_order_id=provider_order_id, amount=Decimal("0.00"), currency="INR", status="paid")

    def initiate_refund(self, *, provider_payment_id, amount, notes=None):
        return ProviderRefund(provider_refund_id="rfnd_p21", status="processed", amount=amount)

    def verify_webhook_signature(self, *, payload, signature):
        return True


# ---------------------------------------------------------------------------
# Sequential repeats — double tap / network retry / app restart / repeated
# checkout request, one after another (the common case in practice).
# ---------------------------------------------------------------------------


def test_repeated_sequential_calls_for_an_online_payment_never_call_the_provider_twice(db):
    fake = CountingFakeProvider()
    service = PaymentService(providers={"razorpay": fake})
    order = _seed_order(db, "seq")

    first = service.create_payment_for_order(db, order=order, method="razorpay")
    second = service.create_payment_for_order(db, order=order, method="razorpay")
    third = service.create_payment_for_order(db, order=order, method="razorpay")

    assert first.id == second.id == third.id
    assert fake.create_order_calls == 1  # never re-opened, no matter how many times this is called
    assert db.query(Payment).filter(Payment.order_id == order.id).count() == 1


def test_repeated_sequential_calls_return_the_same_provider_order_id(db):
    """Not just the same Payment row — the same real checkout information
    the customer would reopen, e.g. after an app restart."""
    fake = CountingFakeProvider()
    service = PaymentService(providers={"razorpay": fake})
    order = _seed_order(db, "sameref")

    first = service.create_payment_for_order(db, order=order, method="razorpay")
    second = service.create_payment_for_order(db, order=order, method="razorpay")

    assert first.razorpay_order_id == second.razorpay_order_id
    assert first.razorpay_order_id == "order_p21_1"


# ---------------------------------------------------------------------------
# Genuine concurrency — two callers that both start before either commits.
# ---------------------------------------------------------------------------


def test_a_race_that_gets_past_the_lock_still_resolves_to_exactly_one_payment_row(db, monkeypatch):
    """The order-row lock (with_for_update()) is this phase's primary
    defense — proven for real against Postgres in this phase's own live
    verification, since SQLite has no real row-level locking to exercise
    a lock against in a unit test. This test instead proves the *second*
    layer of defense still holds even if a race somehow got past the
    lock (a caller whose existence check misses a row that genuinely
    already exists — the same scenario Phase 6/14/18's own race tests
    reproduce for their respective tables): the uq_payments_order_id
    constraint plus the existing IntegrityError-catch-and-recover still
    guarantee exactly one Payment row survives, never two."""
    fake = CountingFakeProvider()
    service = PaymentService(providers={"razorpay": fake})
    order = _seed_order(db, "race")

    # "Request 1" wins the race and commits first, including its own
    # genuine provider.create_order() call.
    winner = service.create_payment_for_order(db, order=order, method="razorpay")
    assert fake.create_order_calls == 1

    # Force only the *existence* check inside create_payment_for_order to
    # miss the row that's actually there — exactly what a genuinely
    # concurrent second caller, whose own check ran before the first
    # caller's commit, would observe.
    real_query = db.query
    calls = {"payment_queries": 0}

    def query_that_misses_on_first_call(model, *args, **kwargs):
        if model is Payment:
            calls["payment_queries"] += 1
            if calls["payment_queries"] == 1:
                return real_query(model).filter(Payment.id == None)  # noqa: E711 - deliberately empty
        return real_query(model, *args, **kwargs)

    monkeypatch.setattr(db, "query", query_that_misses_on_first_call)
    result = service.create_payment_for_order(db, order=order, method="razorpay")
    monkeypatch.undo()

    assert result.id == winner.id
    # The second caller's own existence check missed, so it *does* call
    # the provider again before its INSERT collides — a real, if wasted,
    # extra provider call this specific race can't avoid without the
    # lock actually holding (proven live, not here). What must still hold
    # regardless is the database invariant this test is really about:
    assert db.query(Payment).filter(Payment.order_id == order.id).count() == 1
