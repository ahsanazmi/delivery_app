"""Payment System Phase 18 — WEBHOOK IDEMPOTENCY.

Covers the event_id-based dedup process_webhook_event() gained this
phase, on top of (not replacing) Phase 17's own state-based idempotency:
the same x-razorpay-event-id delivered twice results in exactly one
WebhookEvent row and exactly one processing pass — no second Payment/Order
mutation, no second audit row — and the underlying database constraint
makes that guarantee hold even under two genuinely concurrent deliveries
of the same event, not just sequential ones.
"""
import hashlib
import hmac
import json
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.core.config import settings
from app.core.security import hash_password
from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.models.payment import Payment, PaymentProvider, PaymentStatus
from app.models.product import Product
from app.models.restaurant import Restaurant
from app.models.user import User, UserRole
from app.models.webhook_event import WebhookEvent
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


def _customer(db, email="customer@example.com"):
    user = User(name="Customer", email=email, password_hash=hash_password("x"), role=UserRole.CUSTOMER)
    db.add(user)
    db.commit()
    return user


def _restaurant(db, tag="p18"):
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
    return restaurant


def _order_with_payment(db, tag="p18", price=Decimal("200.00"), order_id="order_p18_1"):
    customer = _customer(db, email=f"customer-{tag}@example.com")
    restaurant = _restaurant(db, tag)
    product = Product(restaurant_id=restaurant.id, name="Item", price=price)
    db.add(product)
    db.commit()
    cart = create_cart_for_user(db, customer.id)
    add_item(db, cart, product.id, 1)
    address = create_address(db, customer.id, {
        "label": "Home", "recipient_name": "Customer", "phone": "9999999999",
        "address_line": "15 Market Road", "city": "Bengaluru", "state": "Karnataka", "postal_code": "560001",
    })
    order = create_order(db, customer, address.id, payment_method="cod")
    payment = Payment(
        order_id=order.id, user_id=customer.id, provider=PaymentProvider.RAZORPAY,
        amount=order.total, payment_status=PaymentStatus.PENDING, razorpay_order_id=order_id,
    )
    db.add(payment)
    db.commit()
    db.refresh(payment)
    return order, payment


def _captured_body(order_id, payment_id, amount_paise, currency="INR"):
    return json.dumps({
        "event": "payment.captured",
        "payload": {"payment": {"entity": {
            "id": payment_id, "order_id": order_id, "amount": amount_paise, "currency": currency, "status": "captured",
        }}},
    }).encode()


# ---------------------------------------------------------------------------
# Service-level: same event_id twice -> processed once
# ---------------------------------------------------------------------------


def test_same_event_id_delivered_twice_is_processed_exactly_once(db):
    order, payment = _order_with_payment(db)
    body = _captured_body(payment.razorpay_order_id, "pay_p18_1", int(payment.amount * 100))

    first = process_webhook_event(db, raw_body=body, event_id="evt_p18_fixed_1")
    assert first.outcome == "payment_marked_paid"
    db.refresh(payment)
    paid_at_after_first = payment.paid_at

    second = process_webhook_event(db, raw_body=body, event_id="evt_p18_fixed_1")

    # The exact same row is returned — not a new one, not a re-processed one.
    assert second.id == first.id
    db.refresh(payment)
    assert payment.paid_at == paid_at_after_first  # untouched by the redelivery
    assert db.query(WebhookEvent).filter(WebhookEvent.event_id == "evt_p18_fixed_1").count() == 1


def test_redelivery_with_the_same_event_id_never_reprocesses_even_a_different_body(db):
    """A defensive edge case: even if a redelivery's body somehow differed
    (it shouldn't, but Razorpay's own retry semantics are Razorpay's to
    keep consistent, not this backend's to assume), the event_id gate
    checks *before* parsing the body at all — the original outcome always
    wins, and no second attempt to interpret a possibly-different payload
    ever happens."""
    order, payment = _order_with_payment(db, tag="samebody")
    first_body = _captured_body(payment.razorpay_order_id, "pay_p18_2", int(payment.amount * 100))
    process_webhook_event(db, raw_body=first_body, event_id="evt_p18_fixed_2")
    db.refresh(payment)
    assert payment.payment_status == PaymentStatus.PAID

    # A "redelivery" carrying a completely different (and malformed) body.
    weird_body = b"not even valid json for this retry"
    result = process_webhook_event(db, raw_body=weird_body, event_id="evt_p18_fixed_2")

    assert result.outcome == "payment_marked_paid"  # the ORIGINAL outcome, not re-evaluated
    db.refresh(payment)
    assert payment.payment_status == PaymentStatus.PAID
    assert db.query(WebhookEvent).filter(WebhookEvent.event_id == "evt_p18_fixed_2").count() == 1


def test_no_duplicate_payment_or_financial_mutation_across_many_redeliveries(db):
    """The phase's own closing requirement, proven directly: N redeliveries
    of the same event never create N payment records or N financial
    state changes — exactly one."""
    order, payment = _order_with_payment(db, tag="many")
    body = _captured_body(payment.razorpay_order_id, "pay_p18_3", int(payment.amount * 100))

    for _ in range(5):
        process_webhook_event(db, raw_body=body, event_id="evt_p18_fixed_3")

    assert db.query(Payment).filter(Payment.order_id == order.id).count() == 1
    assert db.query(WebhookEvent).filter(WebhookEvent.event_id == "evt_p18_fixed_3").count() == 1
    db.refresh(payment)
    assert payment.payment_status == PaymentStatus.PAID


def test_different_event_ids_are_each_recorded_independently(db):
    """Not the same guarantee as above, deliberately: two genuinely
    different events (different ids) each get their own audit row, even
    if Phase 17's state-check means only the first actually changes
    anything."""
    order, payment = _order_with_payment(db, tag="different")
    body = _captured_body(payment.razorpay_order_id, "pay_p18_4", int(payment.amount * 100))

    first = process_webhook_event(db, raw_body=body, event_id="evt_p18_a")
    second = process_webhook_event(db, raw_body=body, event_id="evt_p18_b")

    assert first.id != second.id
    assert first.outcome == "payment_marked_paid"
    assert second.outcome == "duplicate_ignored"  # Phase 17's state-check still catches this
    assert db.query(WebhookEvent).count() == 2


def test_a_request_with_no_event_id_still_works_via_state_based_idempotency_alone(db):
    """No x-razorpay-event-id header at all falls back to exactly Phase
    17's original behavior — this phase is additive, not a replacement."""
    order, payment = _order_with_payment(db, tag="noid")
    body = _captured_body(payment.razorpay_order_id, "pay_p18_5", int(payment.amount * 100))

    event = process_webhook_event(db, raw_body=body, event_id=None)
    assert event.outcome == "payment_marked_paid"
    assert event.event_id is None


# ---------------------------------------------------------------------------
# The database constraint itself — race-proof, not just sequential
# ---------------------------------------------------------------------------


def test_a_concurrent_duplicate_insert_is_resolved_to_the_winners_row_not_an_error(db):
    """Reproduces the exact race two genuinely concurrent deliveries of
    the same event would hit: both pass the "does this event_id exist
    yet?" check before either has committed. Forces process_webhook_event's
    own pre-commit existence check to miss the row that's actually there
    (exactly what a truly concurrent transaction would observe), so this
    test actually exercises the IntegrityError-catch-and-recover branch,
    not just plain sequential idempotency (already covered above)."""
    order, payment = _order_with_payment(db, tag="race")
    body = _captured_body(payment.razorpay_order_id, "pay_p18_race", int(payment.amount * 100))

    # "Request 1" wins the race and commits first.
    winner = process_webhook_event(db, raw_body=body, event_id="evt_p18_race")
    assert winner.outcome == "payment_marked_paid"

    # Force only the existence-check query to miss the row that's actually
    # there — exactly what a genuinely concurrent transaction would see.
    real_query = db.query
    calls = {"count": 0}

    def query_that_misses_on_first_call(model, *args, **kwargs):
        if model is WebhookEvent:
            calls["count"] += 1
            if calls["count"] == 1:
                return real_query(model).filter(WebhookEvent.id == None)  # noqa: E711 - deliberately empty
        return real_query(model, *args, **kwargs)

    import pytest as _pytest
    monkeypatch = _pytest.MonkeyPatch()
    monkeypatch.setattr(db, "query", query_that_misses_on_first_call)
    try:
        result = process_webhook_event(db, raw_body=body, event_id="evt_p18_race")
    finally:
        monkeypatch.undo()

    assert result.id == winner.id
    assert db.query(WebhookEvent).filter(WebhookEvent.event_id == "evt_p18_race").count() == 1
    db.refresh(payment)
    assert payment.payment_status == PaymentStatus.PAID  # not corrupted by the race


# ---------------------------------------------------------------------------
# The real HTTP endpoint — the header is actually read and used
# ---------------------------------------------------------------------------


def test_http_endpoint_dedupes_by_the_x_razorpay_event_id_header(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)

    def override_get_db():
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    monkeypatch.setattr(settings, "RAZORPAY_WEBHOOK_SECRET", "whsec_test")
    try:
        with Session(engine) as seed:
            order, payment = _order_with_payment(seed, tag="http")
            order_id = payment.razorpay_order_id
            amount_paise = int(payment.amount * 100)
            payment_id_db = payment.id

        body = _captured_body(order_id, "pay_p18_http", amount_paise)
        signature = hmac.new(b"whsec_test", body, hashlib.sha256).hexdigest()
        headers = {"x-razorpay-signature": signature, "x-razorpay-event-id": "evt_p18_http_1"}

        with TestClient(app) as client:
            first = client.post("/api/v1/payments/webhooks/razorpay", headers=headers, content=body)
            assert first.status_code == 200
            # Razorpay redelivers the identical request (same signature, same event id).
            second = client.post("/api/v1/payments/webhooks/razorpay", headers=headers, content=body)
            assert second.status_code == 200

        with Session(engine) as check:
            events = check.query(WebhookEvent).filter(WebhookEvent.event_id == "evt_p18_http_1").all()
            assert len(events) == 1
            refreshed = check.get(Payment, payment_id_db)
            assert refreshed.payment_status == PaymentStatus.PAID
    finally:
        app.dependency_overrides.clear()
        Base.metadata.drop_all(engine)
