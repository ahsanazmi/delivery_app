"""Payment System Phase 17 — PAYMENT WEBHOOKS.

Covers: process_webhook_event() identifies the payment/order, applies
payment.captured/payment.failed/refund.processed idempotently, and always
records a WebhookEvent audit row — even for events it can't match or
doesn't act on. Also covers the real HTTP endpoint: a genuinely-signed
event is processed end to end, and an unsigned/forged one is rejected
before ever reaching the processing/audit layer at all.
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
from app.models.order import Order, OrderStatus
from app.models.payment import Payment, PaymentProvider, PaymentStatus
from app.models.product import Product
from app.models.refund import Refund, RefundStatus
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


def _restaurant(db, tag="p17"):
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


def _order_with_payment(db, tag="p17", price=Decimal("200.00"), order_id="order_p17_1"):
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
    db.refresh(order)
    return order, payment


def _captured_body(order_id, payment_id, amount_paise, currency="INR"):
    return json.dumps({
        "event": "payment.captured",
        "payload": {"payment": {"entity": {
            "id": payment_id, "order_id": order_id, "amount": amount_paise, "currency": currency, "status": "captured",
        }}},
    }).encode()


def _failed_body(order_id, payment_id, description="Card declined"):
    return json.dumps({
        "event": "payment.failed",
        "payload": {"payment": {"entity": {
            "id": payment_id, "order_id": order_id, "amount": 0, "currency": "INR", "status": "failed",
            "error_description": description,
        }}},
    }).encode()


def _refund_processed_body(refund_id, payment_id, amount_paise):
    return json.dumps({
        "event": "refund.processed",
        "payload": {"refund": {"entity": {"id": refund_id, "payment_id": payment_id, "amount": amount_paise, "status": "processed"}}},
    }).encode()


def _refund_failed_body(refund_id, payment_id, amount_paise):
    return json.dumps({
        "event": "refund.failed",
        "payload": {"refund": {"entity": {"id": refund_id, "payment_id": payment_id, "amount": amount_paise, "status": "failed"}}},
    }).encode()


# ---------------------------------------------------------------------------
# process_webhook_event — payment.captured
# ---------------------------------------------------------------------------


def test_payment_captured_marks_payment_paid_and_syncs_order(db):
    order, payment = _order_with_payment(db)
    amount_paise = int(payment.amount * 100)
    body = _captured_body(payment.razorpay_order_id, "pay_p17_1", amount_paise)

    event = process_webhook_event(db, raw_body=body)

    assert event.outcome == "payment_marked_paid"
    assert event.event_type == "payment.captured"
    assert event.payment_id == payment.id
    db.refresh(payment)
    db.refresh(order)
    assert payment.payment_status == PaymentStatus.PAID
    assert payment.is_verified is True
    assert payment.razorpay_payment_id == "pay_p17_1"
    assert order.payment_status == "paid"
    assert order.is_paid is True
    assert order.status == OrderStatus.PLACED  # never touched


def test_payment_captured_is_idempotent_on_replay(db):
    order, payment = _order_with_payment(db, tag="replay")
    amount_paise = int(payment.amount * 100)
    body = _captured_body(payment.razorpay_order_id, "pay_p17_2", amount_paise)

    first = process_webhook_event(db, raw_body=body)
    assert first.outcome == "payment_marked_paid"
    paid_at_after_first = payment.paid_at

    second = process_webhook_event(db, raw_body=body)
    assert second.outcome == "duplicate_ignored"
    db.refresh(payment)
    assert payment.paid_at == paid_at_after_first  # untouched by the replay
    assert db.query(WebhookEvent).filter(WebhookEvent.payment_id == payment.id).count() == 2  # both still recorded


def test_payment_captured_for_unknown_order_is_recorded_not_crashed(db):
    body = _captured_body("order_does_not_exist", "pay_ghost", 10000)
    event = process_webhook_event(db, raw_body=body)
    assert event.outcome == "payment_not_found"
    assert event.payment_id is None


def test_payment_captured_amount_mismatch_never_marks_paid(db):
    order, payment = _order_with_payment(db, tag="mismatch")
    wrong_amount_paise = int(payment.amount * 100) + 100  # off by 1.00
    body = _captured_body(payment.razorpay_order_id, "pay_p17_3", wrong_amount_paise)

    event = process_webhook_event(db, raw_body=body)

    assert event.outcome == "amount_mismatch"
    db.refresh(payment)
    assert payment.payment_status == PaymentStatus.PENDING  # unchanged, never PAID


# ---------------------------------------------------------------------------
# Payment/Order State Machine (Phase 22) — a webhook capture for an order
# that's already dead (cancelled/rejected) is flagged, never silently paid.
# ---------------------------------------------------------------------------


def test_payment_captured_for_a_cancelled_order_is_flagged_not_silently_paid(db):
    from app.models.notification import Notification, NotificationType
    from app.models.user import User, UserRole

    order, payment = _order_with_payment(db, tag="deadwebhook")
    admin = User(name="Admin", email="admin-deadwebhook@example.com", password_hash=hash_password("x"), role=UserRole.ADMIN, is_active=True)
    db.add(admin)
    order.status = OrderStatus.CANCELLED
    db.commit()

    body = _captured_body(payment.razorpay_order_id, "pay_p22_webhook", int(payment.amount * 100))
    event = process_webhook_event(db, raw_body=body)

    assert event.outcome == "refund_pending_dead_order"
    db.refresh(payment)
    assert payment.payment_status == PaymentStatus.REFUND_PENDING
    assert payment.is_verified is True  # the capture itself genuinely happened
    db.refresh(order)
    assert order.status == OrderStatus.CANCELLED
    assert order.is_paid is False  # order fields left untouched

    alerts = db.query(Notification).filter(Notification.type == NotificationType.SYSTEM_ALERT).all()
    assert len(alerts) == 1


def test_payment_captured_for_a_cancelled_order_defers_the_admin_push_to_background_tasks(db, monkeypatch):
    """Performance & Reliability (Phase 39) — the admin alert this dead-
    order path raises is a real network call to Expo (up to 5s), which
    must never block the webhook's own response to Razorpay. When the
    real endpoint's background_tasks is supplied, the synchronous
    send_push_to_users() must never run inline at all — only be
    scheduled via send_push_to_users_in_background() to run after the
    response. (test_payment_captured_for_a_cancelled_order_is_flagged_...
    above still covers the no-background_tasks default, unchanged.)"""
    from fastapi import BackgroundTasks

    from app.models.user import User, UserRole
    from app.services import notifications as notifications_module

    order, payment = _order_with_payment(db, tag="deadwebhookbg")
    admin = User(
        name="Admin", email="admin-deadwebhookbg@example.com", password_hash=hash_password("x"),
        role=UserRole.ADMIN, is_active=True,
    )
    db.add(admin)
    order.status = OrderStatus.CANCELLED
    db.commit()

    def _fail_if_called_synchronously(*args, **kwargs):
        raise AssertionError("send_push_to_users must not run synchronously when background_tasks is supplied")

    monkeypatch.setattr(notifications_module, "send_push_to_users", _fail_if_called_synchronously)

    body = _captured_body(payment.razorpay_order_id, "pay_p39_webhook", int(payment.amount * 100))
    background_tasks = BackgroundTasks()
    event = process_webhook_event(db, raw_body=body, background_tasks=background_tasks)

    assert event.outcome == "refund_pending_dead_order"
    assert len(background_tasks.tasks) == 1
    assert background_tasks.tasks[0].func.__name__ == "send_push_to_users_in_background"


# ---------------------------------------------------------------------------
# process_webhook_event — payment.failed
# ---------------------------------------------------------------------------


def test_payment_failed_marks_payment_failed(db):
    order, payment = _order_with_payment(db, tag="fail")
    body = _failed_body(payment.razorpay_order_id, "pay_p17_4", "Card declined")

    event = process_webhook_event(db, raw_body=body)

    assert event.outcome == "payment_marked_failed"
    db.refresh(payment)
    assert payment.payment_status == PaymentStatus.FAILED
    assert payment.failure_reason == "Card declined"


def test_payment_failed_never_downgrades_an_already_paid_payment(db):
    order, payment = _order_with_payment(db, tag="latefail")
    amount_paise = int(payment.amount * 100)
    process_webhook_event(db, raw_body=_captured_body(payment.razorpay_order_id, "pay_p17_5", amount_paise))
    db.refresh(payment)
    assert payment.payment_status == PaymentStatus.PAID

    # A late/out-of-order failure notification for the same payment arrives after capture.
    event = process_webhook_event(db, raw_body=_failed_body(payment.razorpay_order_id, "pay_p17_5"))

    assert event.outcome == "ignored_already_paid"
    db.refresh(payment)
    assert payment.payment_status == PaymentStatus.PAID  # still paid, never downgraded


# ---------------------------------------------------------------------------
# process_webhook_event — refund.processed
# ---------------------------------------------------------------------------


def test_refund_processed_marks_refund_completed(db):
    order, payment = _order_with_payment(db, tag="refund")
    refund = Refund(
        payment_id=payment.id, order_id=order.id, amount=Decimal("50.00"),
        status=RefundStatus.PROCESSING, provider_refund_id="rfnd_p17_1",
    )
    db.add(refund)
    db.commit()

    event = process_webhook_event(db, raw_body=_refund_processed_body("rfnd_p17_1", "pay_x", 5000))

    assert event.outcome == "refund_marked_completed"
    db.refresh(refund)
    assert refund.status == RefundStatus.COMPLETED


def test_refund_processed_is_idempotent_on_replay(db):
    order, payment = _order_with_payment(db, tag="refundreplay")
    refund = Refund(
        payment_id=payment.id, order_id=order.id, amount=Decimal("50.00"),
        status=RefundStatus.COMPLETED, provider_refund_id="rfnd_p17_2",
    )
    db.add(refund)
    db.commit()

    event = process_webhook_event(db, raw_body=_refund_processed_body("rfnd_p17_2", "pay_x", 5000))
    assert event.outcome == "duplicate_ignored"


def test_refund_processed_for_unknown_refund_is_recorded_not_crashed(db):
    event = process_webhook_event(db, raw_body=_refund_processed_body("rfnd_ghost", "pay_x", 100))
    assert event.outcome == "refund_not_found"


def test_refund_processed_resolves_a_processing_refund_and_updates_the_payment_status(db):
    """Razorpay Refund (Phase 24) — a refund create_refund() could only
    record PROCESSING (not yet confirmed settled) must, once this webhook
    confirms it, also update the parent Payment's own status — not just
    the Refund row in isolation."""
    order, payment = _order_with_payment(db, tag="refundwebhookstatus")
    payment.payment_status = PaymentStatus.PAID
    db.commit()
    refund = Refund(
        payment_id=payment.id, order_id=order.id, amount=payment.amount,
        status=RefundStatus.PROCESSING, provider_refund_id="rfnd_p24_1",
    )
    db.add(refund)
    db.commit()

    event = process_webhook_event(db, raw_body=_refund_processed_body("rfnd_p24_1", "pay_x", int(payment.amount * 100)))

    assert event.outcome == "refund_marked_completed"
    db.refresh(refund)
    db.refresh(payment)
    assert refund.status == RefundStatus.COMPLETED
    assert payment.payment_status == PaymentStatus.REFUNDED


# ---------------------------------------------------------------------------
# process_webhook_event — refund.failed
# ---------------------------------------------------------------------------


def test_refund_failed_marks_the_refund_row_failed(db):
    order, payment = _order_with_payment(db, tag="refundfailed")
    refund = Refund(
        payment_id=payment.id, order_id=order.id, amount=Decimal("50.00"),
        status=RefundStatus.PROCESSING, provider_refund_id="rfnd_p24_2",
    )
    db.add(refund)
    db.commit()

    event = process_webhook_event(db, raw_body=_refund_failed_body("rfnd_p24_2", "pay_x", 5000))

    assert event.outcome == "refund_marked_failed"
    db.refresh(refund)
    assert refund.status == RefundStatus.FAILED


def test_refund_failed_never_downgrades_an_already_completed_refund(db):
    order, payment = _order_with_payment(db, tag="refundfailedlate")
    refund = Refund(
        payment_id=payment.id, order_id=order.id, amount=Decimal("50.00"),
        status=RefundStatus.COMPLETED, provider_refund_id="rfnd_p24_3",
    )
    db.add(refund)
    db.commit()

    event = process_webhook_event(db, raw_body=_refund_failed_body("rfnd_p24_3", "pay_x", 5000))

    assert event.outcome == "ignored_already_completed"
    db.refresh(refund)
    assert refund.status == RefundStatus.COMPLETED


def test_refund_failed_is_idempotent_on_replay(db):
    order, payment = _order_with_payment(db, tag="refundfailedreplay")
    refund = Refund(
        payment_id=payment.id, order_id=order.id, amount=Decimal("50.00"),
        status=RefundStatus.FAILED, provider_refund_id="rfnd_p24_4",
    )
    db.add(refund)
    db.commit()

    event = process_webhook_event(db, raw_body=_refund_failed_body("rfnd_p24_4", "pay_x", 5000))
    assert event.outcome == "duplicate_ignored"


def test_refund_failed_for_unknown_refund_is_recorded_not_crashed(db):
    event = process_webhook_event(db, raw_body=_refund_failed_body("rfnd_ghost", "pay_x", 100))
    assert event.outcome == "refund_not_found"


# ---------------------------------------------------------------------------
# process_webhook_event — events not acted on, malformed payloads
# ---------------------------------------------------------------------------


def test_unhandled_event_type_is_recorded_and_never_crashes(db):
    body = json.dumps({"event": "order.paid", "payload": {}}).encode()
    event = process_webhook_event(db, raw_body=body)
    assert event.outcome == "unhandled_event_type"
    assert event.event_type == "order.paid"


def test_invalid_json_is_recorded_not_crashed(db):
    event = process_webhook_event(db, raw_body=b"not json at all")
    assert event.outcome == "invalid_json"


def test_every_processed_webhook_leaves_an_audit_row_with_the_raw_payload(db):
    order, payment = _order_with_payment(db, tag="audit")
    body = _captured_body(payment.razorpay_order_id, "pay_p17_audit", int(payment.amount * 100))
    process_webhook_event(db, raw_body=body)

    stored = db.query(WebhookEvent).filter(WebhookEvent.payment_id == payment.id).one()
    assert json.loads(stored.payload)["event"] == "payment.captured"


# ---------------------------------------------------------------------------
# The real HTTP endpoint — signature verification gates everything
# ---------------------------------------------------------------------------


def test_http_endpoint_processes_a_genuinely_signed_event_end_to_end(monkeypatch):
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

        body = _captured_body(order_id, "pay_p17_http", amount_paise)
        signature = hmac.new(b"whsec_test", body, hashlib.sha256).hexdigest()

        with TestClient(app) as client:
            response = client.post(
                "/api/v1/payments/webhooks/razorpay",
                headers={"x-razorpay-signature": signature},
                content=body,
            )
            assert response.status_code == 200

        with Session(engine) as check:
            refreshed = check.get(Payment, payment_id_db)
            assert refreshed.payment_status == PaymentStatus.PAID
            events = check.query(WebhookEvent).filter(WebhookEvent.payment_id == payment_id_db).all()
            assert len(events) == 1
            assert events[0].outcome == "payment_marked_paid"
    finally:
        app.dependency_overrides.clear()
        Base.metadata.drop_all(engine)


def test_http_endpoint_never_processes_an_unsigned_payload(monkeypatch):
    """Do not trust webhook payloads without signature verification — an
    unsigned/forged request must never reach process_webhook_event() at
    all, so no WebhookEvent row (and no payment mutation) ever results
    from it."""
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)

    def override_get_db():
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    monkeypatch.setattr(settings, "RAZORPAY_WEBHOOK_SECRET", "whsec_test")
    try:
        with Session(engine) as seed:
            order, payment = _order_with_payment(seed, tag="forged")
            order_id = payment.razorpay_order_id
            amount_paise = int(payment.amount * 100)
            payment_id_db = payment.id

        body = _captured_body(order_id, "pay_p17_forged", amount_paise)

        with TestClient(app) as client:
            forged = client.post(
                "/api/v1/payments/webhooks/razorpay",
                headers={"x-razorpay-signature": "not-even-close"},
                content=body,
            )
            assert forged.status_code == 400

            missing = client.post("/api/v1/payments/webhooks/razorpay", content=body)
            assert missing.status_code == 400

        with Session(engine) as check:
            refreshed = check.get(Payment, payment_id_db)
            assert refreshed.payment_status == PaymentStatus.PENDING  # completely untouched
            assert check.query(WebhookEvent).count() == 0  # nothing was ever recorded
    finally:
        app.dependency_overrides.clear()
        Base.metadata.drop_all(engine)


def test_http_endpoint_never_500s_on_a_genuinely_signed_but_malformed_body(monkeypatch):
    """Automated Tests (Phase 38) — Webhook verification. Unlike
    test_invalid_json_is_recorded_not_crashed above (which calls
    process_webhook_event() directly, after signature verification has
    already happened), this drives the full stack: a real HMAC computed
    over genuinely malformed bytes, through the actual HTTP endpoint, to
    confirm signature verification runs — and passes — before the body
    is ever parsed as JSON, and that a malformed-but-signed payload is
    still a clean 200/"invalid_json" outcome, never an unhandled 500."""
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)

    def override_get_db():
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    monkeypatch.setattr(settings, "RAZORPAY_WEBHOOK_SECRET", "whsec_test")
    try:
        body = b"this is not json at all {{{"
        signature = hmac.new(b"whsec_test", body, hashlib.sha256).hexdigest()

        with TestClient(app) as client:
            response = client.post(
                "/api/v1/payments/webhooks/razorpay",
                headers={"x-razorpay-signature": signature},
                content=body,
            )
            assert response.status_code == 200

        with Session(engine) as check:
            events = check.query(WebhookEvent).all()
            assert len(events) == 1
            assert events[0].outcome == "invalid_json"
    finally:
        app.dependency_overrides.clear()
        Base.metadata.drop_all(engine)
