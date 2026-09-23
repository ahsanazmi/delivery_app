"""Automated Tests (Phase 38) — Concurrency.

Every existing "race"/"concurrency" test elsewhere in this suite
(test_idempotent_payment_creation.py::test_a_race_that_gets_past_the_lock_...,
test_payment_service_architecture.py::test_two_near_simultaneous_refunds_...,
test_rider_concurrency_and_failure_handling.py::test_two_riders_accept_same_delivery_...)
is an explicitly *sequential*, deterministic simulation of a race — every
one of those files' own docstrings says so, because the shared test
fixture (`sqlite://` in-memory + StaticPool, one physical connection
reused via check_same_thread=False) cannot support two independent,
concurrently-open transactions at all: a single DBAPI connection has only
one transaction state, so two threads racing on it would just corrupt
each other's statements rather than prove anything.

This file closes that gap without depending on any live/network
infrastructure (matching this project's own standing rule, stated in
conftest.py, that the automated suite must never depend on network
access to pass): it uses a *file-backed* SQLite database instead of
`:memory:`. A real file lets SQLAlchemy hand out genuinely separate
DBAPI connections to each thread, each with its own transaction, and
SQLite's own file-level locking (with a busy_timeout so a blocked writer
waits and retries instead of erroring) serializes concurrent writers the
same way a real database would for the purposes of these three
invariants. This does NOT reproduce Postgres's row-level
`SELECT ... FOR UPDATE` locking specifically (SQLite has no such thing;
that remains proven only via this project's live Postgres verification,
as every phase report since Phase 21 has documented) — but it does
subject the actual application code, running on genuinely independent OS
threads and DB connections with real, non-deterministic interleaving, to
the exact race each scenario describes, which a monkeypatched
simulation cannot do.
"""

import threading
import uuid
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, event, func, select
from sqlalchemy.orm import Session

from app.core.security import hash_password
from app.db.base import Base
from app.models.delivery_partner import ApprovalStatus, DeliveryPartner
from app.models.order import Order, OrderStatus
from app.models.payment import Payment, PaymentProvider as PaymentProviderEnum, PaymentStatus
from app.models.refund import RefundStatus
from app.models.restaurant import Restaurant
from app.models.user import User, UserRole
from app.services.payment import refund_service
from app.services.payment.exceptions import RefundError
from app.services.payment.payment_service import PaymentService
from app.services.payment.provider import PaymentProvider, ProviderOrder, ProviderPayment, ProviderRefund
from app.services.rider_deliveries import accept_delivery


@pytest.fixture()
def file_engine(tmp_path):
    db_path = tmp_path / "concurrency.db"
    engine = create_engine(f"sqlite:///{db_path}")

    @event.listens_for(engine, "connect")
    def _set_pragmas(dbapi_connection, _record):
        cursor = dbapi_connection.cursor()
        # Real, separate connections now genuinely contend for the same
        # file — busy_timeout makes a blocked writer wait and retry
        # (matching how a real database queues writers) instead of
        # raising "database is locked" the instant two threads overlap.
        cursor.execute("PRAGMA busy_timeout = 30000")
        cursor.execute("PRAGMA journal_mode = WAL")
        cursor.close()
        # pysqlite normally opens transactions lazily/deferred — a SELECT
        # only takes a shared read lock, so a later writer thread can
        # still commit *between* another thread's SELECT and its own
        # subsequent write, letting both threads act on a stale read
        # (this is exactly what test_real_concurrent_refunds_... would
        # observe without the fix below: SQLite's own with_for_update()
        # is a silent no-op, so nothing else stops it). Disabling
        # pysqlite's implicit transaction handling here and issuing our
        # own BEGIN IMMEDIATE below makes each transaction take SQLite's
        # write lock up front, before its own first SELECT runs — the
        # closest a file-backed SQLite database can genuinely get to the
        # blocking-read guarantee Postgres's real row lock provides.
        dbapi_connection.isolation_level = None

    @event.listens_for(engine, "begin")
    def _begin_immediate(conn):
        conn.exec_driver_sql("BEGIN IMMEDIATE")

    Base.metadata.create_all(engine)
    yield engine
    engine.dispose()


class ThreadSafeCountingProvider(PaymentProvider):
    """Same purpose as test_idempotent_payment_creation.py's
    CountingFakeProvider, but with a real lock around the counter since
    this one is genuinely called from multiple threads at once."""

    name = "counting-fake"

    def __init__(self):
        self._lock = threading.Lock()
        self.create_order_calls = 0

    def create_order(self, *, amount, currency, receipt, notes=None):
        with self._lock:
            self.create_order_calls += 1
            n = self.create_order_calls
        return ProviderOrder(provider_order_id=f"order_race_{n}", amount=amount, currency=currency, status="created")

    def verify_payment_signature(self, *, provider_order_id, provider_payment_id, signature):
        return True

    def fetch_payment(self, provider_payment_id):
        return ProviderPayment(provider_payment_id=provider_payment_id, provider_order_id=None, status="captured", amount=Decimal("0.00"), currency="INR")

    def fetch_order(self, provider_order_id):
        return ProviderOrder(provider_order_id=provider_order_id, amount=Decimal("0.00"), currency="INR", status="paid")

    def initiate_refund(self, *, provider_payment_id, amount, notes=None):
        return ProviderRefund(provider_refund_id="rfnd_race", status="processed", amount=amount)

    def verify_webhook_signature(self, *, payload, signature):
        return True


def _seed_order(db, total=Decimal("300.00")) -> uuid.UUID:
    tag = uuid.uuid4().hex[:10]
    owner = User(name="Owner", email=f"owner-{tag}@example.com", phone=f"9{tag[:9]}", password_hash=hash_password("x"), role=UserRole.RESTAURANT_OWNER)
    customer = User(name="Customer", email=f"customer-{tag}@example.com", phone=f"8{tag[:9]}", password_hash=hash_password("x"), role=UserRole.CUSTOMER)
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
        order_number=f"ORD-{tag}", status=OrderStatus.PLACED,
        subtotal=total - Decimal("30.00"), delivery_fee=Decimal("30.00"), total=total,
        payment_method="razorpay", address_line="1 Road", city="Town", postal_code="123456",
    )
    db.add(order)
    db.commit()
    return order.id


def test_real_concurrent_duplicate_payment_creation_still_yields_exactly_one_payment_row(file_engine):
    """Duplicate payment / Concurrency — N genuinely concurrent threads,
    each on its own DB connection with its own transaction, all call
    create_payment_for_order() for the exact same order at once (a real
    double-tap / retry-storm, not a simulated one). Exactly one Payment
    row must survive, and every thread must resolve to that same row
    without raising — never a duplicate, never an unhandled error
    surfaced to the caller."""
    seed_db = Session(file_engine)
    order_id = _seed_order(seed_db)
    seed_db.close()

    provider = ThreadSafeCountingProvider()
    results: list[uuid.UUID] = []
    errors: list[BaseException] = []
    results_lock = threading.Lock()

    def attempt():
        db = Session(file_engine)
        try:
            service = PaymentService(providers={"razorpay": provider})
            order = db.get(Order, order_id)
            payment = service.create_payment_for_order(db, order=order, method="razorpay")
            with results_lock:
                results.append(payment.id)
        except BaseException as exc:  # noqa: BLE001 - we want to see genuinely anything that escapes
            with results_lock:
                errors.append(exc)
        finally:
            db.close()

    threads = [threading.Thread(target=attempt) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)

    assert not errors, f"unexpected exceptions under real concurrency: {errors}"
    assert len(results) == 8
    assert len(set(results)) == 1  # every thread resolved to the SAME payment row

    verify_db = Session(file_engine)
    count = verify_db.scalar(select(func.count()).select_from(Payment).where(Payment.order_id == order_id))
    assert count == 1
    verify_db.close()


def test_real_concurrent_refunds_never_together_exceed_the_captured_amount(file_engine):
    """Refund / Partial refund / Concurrency — two genuinely concurrent
    threads each try to refund an amount that, if both succeeded in
    full, would exceed the ₹100 captured. Under real concurrent
    transactions the total ever marked COMPLETED must never exceed the
    captured amount — exactly one of the two must be rejected or
    reduced, never both accepted in full."""
    seed_db = Session(file_engine)
    order_id = _seed_order(seed_db, total=Decimal("100.00"))
    order = seed_db.get(Order, order_id)
    payment = Payment(
        order_id=order.id, user_id=order.user_id, provider=PaymentProviderEnum.COD,
        amount=Decimal("100.00"), payment_status=PaymentStatus.PAID,
    )
    seed_db.add(payment)
    seed_db.commit()
    payment_id = payment.id
    seed_db.close()

    outcomes: list[str] = []
    outcomes_lock = threading.Lock()

    def attempt(amount: Decimal):
        db = Session(file_engine)
        try:
            local_payment = db.get(Payment, payment_id)
            refund_service.create_refund(db, payment=local_payment, amount=amount, provider=None)
            with outcomes_lock:
                outcomes.append("accepted")
        except RefundError:
            with outcomes_lock:
                outcomes.append("rejected")
        finally:
            db.close()

    t1 = threading.Thread(target=attempt, args=(Decimal("70.00"),))
    t2 = threading.Thread(target=attempt, args=(Decimal("70.00"),))
    t1.start()
    t2.start()
    t1.join(timeout=30)
    t2.join(timeout=30)

    assert sorted(outcomes) == ["accepted", "rejected"]

    verify_db = Session(file_engine)
    final_payment = verify_db.get(Payment, payment_id)
    total_completed = sum(
        (r.amount for r in final_payment.refunds if r.status == RefundStatus.COMPLETED), Decimal("0.00")
    )
    assert total_completed <= Decimal("100.00")
    assert total_completed == Decimal("70.00")  # exactly the one accepted refund, never both
    verify_db.close()


def test_real_concurrent_delivery_accept_only_one_rider_ever_gets_assigned(file_engine):
    """Concurrency — two riders, on genuinely separate threads/
    connections, call accept_delivery() for the same order at the same
    moment. The atomic conditional UPDATE (`WHERE rider_id IS NULL`,
    see accept_delivery()'s own docstring) must let exactly one through;
    the other gets the real 409 the endpoint raises for a lost race,
    not a corrupted double-assignment."""
    from fastapi import HTTPException

    seed_db = Session(file_engine)
    order_id = _seed_order(seed_db)
    order = seed_db.get(Order, order_id)
    order.status = OrderStatus.READY_FOR_PICKUP
    seed_db.add(order)

    riders = []
    for i in range(2):
        tag = uuid.uuid4().hex[:8]
        rider = User(
            name=f"Rider {i}", email=f"rider-{tag}@example.com", phone=f"7{tag[:9]}",
            password_hash=hash_password("x"), role=UserRole.RIDER,
        )
        seed_db.add(rider)
        seed_db.commit()
        partner = DeliveryPartner(user_id=rider.id, approval_status=ApprovalStatus.APPROVED, is_online=True)
        seed_db.add(partner)
        seed_db.commit()
        riders.append(rider.id)
    seed_db.commit()
    seed_db.close()

    outcomes: list[str] = []
    outcomes_lock = threading.Lock()

    def attempt(rider_id):
        db = Session(file_engine)
        try:
            rider = db.get(User, rider_id)
            accept_delivery(db, rider, order_id)
            with outcomes_lock:
                outcomes.append("accepted")
        except HTTPException:
            with outcomes_lock:
                outcomes.append("rejected")
        finally:
            db.close()

    t1 = threading.Thread(target=attempt, args=(riders[0],))
    t2 = threading.Thread(target=attempt, args=(riders[1],))
    t1.start()
    t2.start()
    t1.join(timeout=30)
    t2.join(timeout=30)

    assert sorted(outcomes) == ["accepted", "rejected"]

    verify_db = Session(file_engine)
    final_order = verify_db.get(Order, order_id)
    assert final_order.rider_id in riders
    verify_db.close()
