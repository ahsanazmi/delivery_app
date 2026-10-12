"""E2E Validation Phase 13 — Razorpay audit P5/P6, reproduced live against
a real captured Test Mode payment: a late payment.captured flipped a
REFUNDED payment back to PAID, and a webhook-confirmed capture left no
PaymentAttempt. Sessions don't autoflush, like app.db.session.SessionLocal."""

import json
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.models.payment import PaymentStatus
from app.models.payment_attempt import PaymentAttempt
from app.services.payment.webhook_service import process_webhook_event
from tests.test_payment_webhooks import _captured_body, _order_with_payment


@pytest.fixture()
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with Session(engine, autoflush=False) as session:
        yield session
    Base.metadata.drop_all(engine)


def _failed_body(order_id, payment_id):
    return json.dumps({"event": "payment.failed", "payload": {"payment": {"entity": {
        "id": payment_id, "order_id": order_id, "amount": 100, "currency": "INR", "status": "failed",
        "error_description": "late failure",
    }}}}).encode()


@pytest.mark.parametrize("settled", [PaymentStatus.REFUNDED, PaymentStatus.PARTIALLY_REFUNDED, PaymentStatus.REFUND_PENDING])
def test_a_late_capture_never_reverts_a_settled_payment_to_paid(db, settled):
    _, payment = _order_with_payment(db, tag="p5", price=Decimal("20.00"), order_id="order_p5_1")
    first = process_webhook_event(db, raw_body=_captured_body("order_p5_1", "pay_p5_1", int(payment.amount * 100)), event_id="evt_p5_first")
    assert first.outcome == "payment_marked_paid"
    payment.payment_status = settled
    db.commit()

    event = process_webhook_event(db, raw_body=_captured_body("order_p5_1", "pay_p5_1", int(payment.amount * 100)), event_id="evt_p5_late")

    assert event.outcome == "duplicate_ignored"
    db.refresh(payment)
    assert payment.payment_status == settled


def test_a_late_failure_never_downgrades_a_refunded_payment(db):
    _, payment = _order_with_payment(db, tag="p5f", price=Decimal("20.00"), order_id="order_p5_2")
    assert process_webhook_event(db, raw_body=_captured_body("order_p5_2", "pay_p5_2", int(payment.amount * 100)), event_id="evt_p5f_cap").outcome == "payment_marked_paid"
    payment.payment_status = PaymentStatus.REFUNDED
    db.commit()

    process_webhook_event(db, raw_body=_failed_body("order_p5_2", "pay_p5_2"), event_id="evt_p5f_fail")

    db.refresh(payment)
    assert payment.payment_status == PaymentStatus.REFUNDED


def test_a_webhook_confirmed_capture_is_recorded_as_a_paid_attempt(db):
    _, payment = _order_with_payment(db, tag="p6", price=Decimal("20.00"), order_id="order_p6_1")

    process_webhook_event(db, raw_body=_captured_body("order_p6_1", "pay_p6_1", int(payment.amount * 100)), event_id="evt_p6")

    attempt = db.scalar(select(PaymentAttempt).where(PaymentAttempt.provider_payment_id == "pay_p6_1"))
    assert attempt is not None and attempt.payment_id == payment.id
    assert attempt.status == PaymentStatus.PAID
    assert attempt.amount == payment.amount


def test_a_capture_after_an_expired_verify_updates_that_attempt_instead_of_duplicating_it(db):
    from app.models.payment import PaymentProvider

    _, payment = _order_with_payment(db, tag="p6e", price=Decimal("20.00"), order_id="order_p6_2")
    db.add(PaymentAttempt(
        payment_id=payment.id, provider=PaymentProvider.RAZORPAY, provider_order_id="order_p6_2",
        provider_payment_id="pay_p6_2", amount=payment.amount, status=PaymentStatus.FAILED, failure_code="PAYMENT_EXPIRED",
    ))
    payment.payment_status = PaymentStatus.FAILED
    db.commit()

    event = process_webhook_event(db, raw_body=_captured_body("order_p6_2", "pay_p6_2", int(payment.amount * 100)), event_id="evt_p6e")

    assert event.outcome == "payment_marked_paid"
    attempts = db.scalars(select(PaymentAttempt).where(PaymentAttempt.provider_payment_id == "pay_p6_2")).all()
    assert [(a.status, a.failure_code) for a in attempts] == [(PaymentStatus.PAID, None)]
