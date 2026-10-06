"""Payment Webhooks (Phase 17) / Webhook Idempotency (Phase 18) —
processes a Razorpay webhook event *after* its signature has already been
verified by the route handler (verify_hmac_signature against
RAZORPAY_WEBHOOK_SECRET) — this module never re-checks authenticity
itself, and never receives a payload the caller hasn't already proven
genuinely came from Razorpay.

Idempotent on two complementary levels:

1. By event id (Phase 18) — Razorpay's own `x-razorpay-event-id` request
   header is unique per event delivery. process_webhook_event() checks
   for an existing WebhookEvent with that id *before* doing any
   event-specific work at all; a genuine redelivery of the same event is
   recognized here and returns the original event's own row untouched —
   "same event twice -> processed once", literally: no second
   Payment/Order mutation, no second audit row. uq_webhook_events_provider_event_id
   (Phase 18's own migration) makes the check-then-insert race-proof
   under two genuinely concurrent deliveries of the same event, the same
   IntegrityError-catch-and-recover pattern already used for
   uq_payments_order_id (Phase 6) and uq_payment_attempts_provider_payment_id
   (Phase 14).
2. By resulting state (Phase 17) — each _handle_* function below also
   checks the *current state* of the Payment/Refund row it's about to
   change before changing it. This matters independently of (1): it's
   what keeps two *different* events that would have the same effect
   (not just two deliveries of the *same* event) from double-applying,
   and it's the only protection at all when a request arrives with no
   event id (nullable, NULL-safe, same as every other provider-id
   constraint in this codebase).
"""

import json
import logging
from datetime import UTC, datetime
from typing import Any

from fastapi import BackgroundTasks
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.notification import NotificationType
from app.models.order import Order, OrderStatus
from app.models.payment import Payment
from app.models.payment import PaymentProvider as PaymentProviderEnum
from app.models.payment import PaymentStatus
from app.models.refund import Refund, RefundStatus
from app.models.webhook_event import WebhookEvent
from app.services.notifications import (
    notify_admins,
    notify_customer_payment_failed,
    notify_customer_payment_success,
    notify_customer_refund_completed,
    notify_restaurant_payment_confirmed,
)
from app.services.payment.razorpay_provider import _from_minor_units
from app.services.payment.refund_service import recompute_payment_refund_status

_DEAD_ORDER_STATUSES = (OrderStatus.CANCELLED, OrderStatus.REJECTED)

logger = logging.getLogger(__name__)


def _record(
    db: Session, *, event_type: str, raw_body: bytes, outcome: str, event_id: str | None = None,
    provider_payment_id: str | None = None, provider_order_id: str | None = None,
    provider_refund_id: str | None = None, payment_id=None,
) -> WebhookEvent:
    event = WebhookEvent(
        provider=PaymentProviderEnum.RAZORPAY, event_type=event_type, event_id=event_id,
        provider_payment_id=provider_payment_id, provider_order_id=provider_order_id,
        provider_refund_id=provider_refund_id, payment_id=payment_id, outcome=outcome,
        payload=raw_body.decode("utf-8", errors="replace"),
    )
    db.add(event)
    return event


def _handle_payment_captured(
    db: Session, *, raw_body: bytes, payment_entity: dict[str, Any], background_tasks: BackgroundTasks | None = None
) -> WebhookEvent:
    provider_payment_id = payment_entity["id"]
    provider_order_id = payment_entity.get("order_id")
    amount = _from_minor_units(payment_entity["amount"])
    currency = payment_entity["currency"]

    payment = db.query(Payment).filter(
        Payment.provider == PaymentProviderEnum.RAZORPAY, Payment.razorpay_order_id == provider_order_id
    ).first()

    if payment is None:
        logger.warning("Payment error: webhook payment.captured for unknown order %s", provider_order_id)
        return _record(
            db, event_type="payment.captured", raw_body=raw_body, outcome="payment_not_found",
            provider_payment_id=provider_payment_id, provider_order_id=provider_order_id,
        )

    if payment.payment_status == PaymentStatus.PAID:
        # Idempotent — a redelivered or naturally-duplicate webhook for a
        # payment this backend already marked PAID (very likely via the
        # client's own /verify call already completing first).
        return _record(
            db, event_type="payment.captured", raw_body=raw_body, outcome="duplicate_ignored",
            provider_payment_id=provider_payment_id, provider_order_id=provider_order_id, payment_id=payment.id,
        )

    if amount != payment.amount or currency != payment.currency:
        # Payment Amount Validation (Phase 15)'s same principle, applied
        # here too — never let an inconsistent event move this payment
        # toward PAID. Deliberately doesn't move it toward FAILED either:
        # an amount/currency mismatch on a webhook is an anomaly to flag
        # for investigation, not proof the payment itself failed.
        logger.warning(
            "Payment error: webhook payment.captured amount/currency mismatch for payment %s (order %s)",
            payment.id, payment.order_id,
        )
        return _record(
            db, event_type="payment.captured", raw_body=raw_body, outcome="amount_mismatch",
            provider_payment_id=provider_payment_id, provider_order_id=provider_order_id, payment_id=payment.id,
        )

    payment.is_verified = True
    payment.razorpay_payment_id = provider_payment_id
    if not payment.paid_at:
        payment.paid_at = datetime.now(UTC)

    order = db.get(Order, payment.order_id)

    # Payment/Order State Machine (Phase 22) — the same "do not allow
    # CANCELLED + a newly successful payment without a defined refund/
    # reconciliation workflow" rule PaymentService.verify_payment()
    # enforces for the client-driven path applies here too — a webhook
    # can just as easily report a capture for an order that was
    # cancelled/rejected in the meantime. Never deny the capture itself
    # (the money genuinely moved); flag it instead.
    if order and order.status in _DEAD_ORDER_STATUSES:
        payment.payment_status = PaymentStatus.REFUND_PENDING
        logger.warning(
            "Payment error: webhook payment.captured for payment %s (order %s, status %s) arrived after "
            "the order was already %s — flagged for refund/reconciliation, not auto-paid.",
            payment.id, payment.order_id, order.status.value, order.status.value,
        )
        notify_admins(
            db, NotificationType.SYSTEM_ALERT, "Payment succeeded for a cancelled/rejected order",
            f"Order {order.order_number} is {order.status.value}, but its payment (id {payment.id}) "
            f"was just captured (via webhook) for {payment.amount} {payment.currency}. Needs manual refund/reconciliation.",
            order_id=payment.order_id, background_tasks=background_tasks,
        )
        return _record(
            db, event_type="payment.captured", raw_body=raw_body, outcome="refund_pending_dead_order",
            provider_payment_id=provider_payment_id, provider_order_id=provider_order_id, payment_id=payment.id,
        )

    payment.payment_status = PaymentStatus.PAID

    # Payment Status Synchronization (Phase 16) — the same, single rule:
    # only payment_status/is_paid move; order.status, Restaurant, and
    # rider fields are never touched here either.
    if order:
        order.payment_status = "paid"
        order.is_paid = True
        # Payment Notifications (Phase 21) — the same two notifications
        # PaymentService.verify_payment()'s client-driven success path
        # already raises, so a payment confirmed via this async webhook
        # (rather than the client's own /verify call reaching PAID first)
        # is never silently un-notified to the customer or restaurant.
        notify_restaurant_payment_confirmed(db, order)

    notify_customer_payment_success(db, payment)

    return _record(
        db, event_type="payment.captured", raw_body=raw_body, outcome="payment_marked_paid",
        provider_payment_id=provider_payment_id, provider_order_id=provider_order_id, payment_id=payment.id,
    )


def _handle_payment_failed(db: Session, *, raw_body: bytes, payment_entity: dict[str, Any]) -> WebhookEvent:
    provider_payment_id = payment_entity["id"]
    provider_order_id = payment_entity.get("order_id")

    payment = db.query(Payment).filter(
        Payment.provider == PaymentProviderEnum.RAZORPAY, Payment.razorpay_order_id == provider_order_id
    ).first()

    if payment is None:
        return _record(
            db, event_type="payment.failed", raw_body=raw_body, outcome="payment_not_found",
            provider_payment_id=provider_payment_id, provider_order_id=provider_order_id,
        )

    if payment.payment_status == PaymentStatus.PAID:
        # A late/out-of-order failure notification must never downgrade an
        # already-confirmed PAID payment — the capture is the more
        # authoritative, more recent fact.
        return _record(
            db, event_type="payment.failed", raw_body=raw_body, outcome="ignored_already_paid",
            provider_payment_id=provider_payment_id, provider_order_id=provider_order_id, payment_id=payment.id,
        )

    if payment.payment_status == PaymentStatus.FAILED:
        return _record(
            db, event_type="payment.failed", raw_body=raw_body, outcome="duplicate_ignored",
            provider_payment_id=provider_payment_id, provider_order_id=provider_order_id, payment_id=payment.id,
        )

    payment.payment_status = PaymentStatus.FAILED
    payment.failure_reason = payment_entity.get("error_description") or "Payment failed (reported via webhook)."
    # Notifications & Communication System Phase 13 — Admin Notifications.
    # PaymentService.verify_payment()'s own client-driven failure path
    # already alerts admins (PAYMENT_FAILURE) — this async, provider-
    # initiated failure (e.g. the customer abandoned the payment sheet
    # before the client ever called /verify) previously raised no alert
    # at all, a real gap: an admin had no way to learn this order's
    # payment failed except by noticing the order itself never got paid.
    notify_admins(
        db, NotificationType.PAYMENT_FAILURE, "Payment failure",
        f"Payment for order {payment.order_id} failed at the provider (reported via webhook).",
        order_id=payment.order_id,
    )
    # Payment Notifications (Phase 21) — the customer's own side of this
    # same event. PaymentService.verify_payment()'s client-driven failure
    # path already tells them (notify_customer_payment_failed); this
    # async webhook path previously only told admins, leaving a customer
    # whose payment failed without the client ever reaching /verify (the
    # same abandoned-payment-sheet case Phase 13's own admin alert
    # covers) with no idea anything went wrong at all.
    order = db.get(Order, payment.order_id)
    if order:
        notify_customer_payment_failed(db, user_id=payment.user_id, order_id=payment.order_id, order_number=order.order_number)
    return _record(
        db, event_type="payment.failed", raw_body=raw_body, outcome="payment_marked_failed",
        provider_payment_id=provider_payment_id, provider_order_id=provider_order_id, payment_id=payment.id,
    )


def _handle_refund_processed(db: Session, *, raw_body: bytes, refund_entity: dict[str, Any]) -> WebhookEvent:
    """Razorpay Refund (Phase 24) — the authoritative, final-status source
    for a refund create_refund() couldn't confirm as settled synchronously
    (recorded PROCESSING there, per Razorpay's own recommendation to treat
    this webhook, not the initiate-refund API response, as the real source
    of truth). Finishing the job create_refund() deliberately left undone:
    once this refund is genuinely COMPLETED, the parent Payment's own
    status is recomputed too — it may have been sitting at PAID or
    PARTIALLY_REFUNDED this whole time, understating what's actually been
    refunded, until this exact moment."""
    provider_refund_id = refund_entity["id"]
    provider_payment_id = refund_entity.get("payment_id")

    refund = db.query(Refund).filter(Refund.provider_refund_id == provider_refund_id).first()

    if refund is None:
        return _record(
            db, event_type="refund.processed", raw_body=raw_body, outcome="refund_not_found",
            provider_payment_id=provider_payment_id, provider_refund_id=provider_refund_id,
        )

    if refund.status == RefundStatus.COMPLETED:
        return _record(
            db, event_type="refund.processed", raw_body=raw_body, outcome="duplicate_ignored",
            provider_payment_id=provider_payment_id, provider_refund_id=provider_refund_id, payment_id=refund.payment_id,
        )

    refund.status = RefundStatus.COMPLETED
    payment = db.get(Payment, refund.payment_id)
    if payment:
        recompute_payment_refund_status(db, payment)
        # Notifications & Communication System Phase 8 — the async
        # resolution of a refund create_refund() could only record as
        # PROCESSING at the time. Safe against a duplicate webhook
        # delivery of this same event by construction: the
        # "already COMPLETED" guard above this function already returns
        # early before this line is ever reached a second time.
        notify_customer_refund_completed(db, refund, payment)
    return _record(
        db, event_type="refund.processed", raw_body=raw_body, outcome="refund_marked_completed",
        provider_payment_id=provider_payment_id, provider_refund_id=provider_refund_id, payment_id=refund.payment_id,
    )


def _handle_refund_failed(db: Session, *, raw_body: bytes, refund_entity: dict[str, Any]) -> WebhookEvent:
    """A refund Razorpay initially accepted (recorded PROCESSING) can
    still later fail — per Razorpay's own docs, this is a real, if rare,
    outcome. The parent Payment's status is deliberately left untouched:
    it was never moved toward REFUNDED/PARTIALLY_REFUNDED for this refund
    in the first place (create_refund() only does that for a refund
    that's genuinely COMPLETED), so there's nothing to undo — the amount
    simply becomes available again the next time someone checks
    (recompute_payment_refund_status only ever counts COMPLETED refunds,
    and the amount-availability check only ever counts COMPLETED/
    PROCESSING ones, from which a FAILED refund is now excluded)."""
    provider_refund_id = refund_entity["id"]
    provider_payment_id = refund_entity.get("payment_id")

    refund = db.query(Refund).filter(Refund.provider_refund_id == provider_refund_id).first()

    if refund is None:
        return _record(
            db, event_type="refund.failed", raw_body=raw_body, outcome="refund_not_found",
            provider_payment_id=provider_payment_id, provider_refund_id=provider_refund_id,
        )

    if refund.status == RefundStatus.FAILED:
        return _record(
            db, event_type="refund.failed", raw_body=raw_body, outcome="duplicate_ignored",
            provider_payment_id=provider_payment_id, provider_refund_id=provider_refund_id, payment_id=refund.payment_id,
        )

    if refund.status == RefundStatus.COMPLETED:
        # A late/out-of-order failure notification must never downgrade an
        # already-settled refund — same reasoning as payment.failed's own
        # ignored_already_paid case.
        return _record(
            db, event_type="refund.failed", raw_body=raw_body, outcome="ignored_already_completed",
            provider_payment_id=provider_payment_id, provider_refund_id=provider_refund_id, payment_id=refund.payment_id,
        )

    refund.status = RefundStatus.FAILED
    logger.warning(
        "Payment error: refund %s (provider id %s) for payment %s failed at the provider.",
        refund.id, provider_refund_id, refund.payment_id,
    )
    # Notifications & Communication System Phase 13 — Admin Notifications,
    # "refund issue." A refund Razorpay initially accepted (PROCESSING)
    # failing later is exactly the kind of anomalous financial state
    # SYSTEM_ALERT already exists for (see the adjacent
    # payment-succeeded-for-a-dead-order alert above, and
    # PaymentService.verify_payment()'s own copy of it) — the money never
    # actually made it back to the customer, so this needs a human to
    # follow up, not a dedicated new NotificationType for what is, from
    # an admin's point of view, the same "needs manual reconciliation"
    # situation.
    notify_admins(
        db, NotificationType.SYSTEM_ALERT, "Refund failed",
        f"Refund {refund.id} for payment {refund.payment_id} (amount {refund.amount}) failed at the provider "
        "and needs manual reconciliation.",
        order_id=refund.order_id,
    )
    return _record(
        db, event_type="refund.failed", raw_body=raw_body, outcome="refund_marked_failed",
        provider_payment_id=provider_payment_id, provider_refund_id=provider_refund_id, payment_id=refund.payment_id,
    )


def process_webhook_event(
    db: Session, *, raw_body: bytes, event_id: str | None = None, background_tasks: BackgroundTasks | None = None
) -> WebhookEvent:
    """The single entry point the route handler calls once signature
    verification has already passed. Always returns a WebhookEvent — even
    an event type this backend doesn't act on is recorded, never silently
    dropped, and always resolves to a committed row rather than raising
    (a webhook handler's job is to acknowledge receipt; a provider-side
    payload we don't understand is not this backend's error to surface as
    one).

    Webhook Idempotency (Phase 18) — the event_id gate. Checked first,
    before any parsing or dispatch: if this exact (provider, event_id) has
    already been recorded, that original row is returned as-is and
    nothing else in this function runs at all — no second Payment/Order
    mutation, no second WebhookEvent row. event_id is optional (a request
    with no x-razorpay-event-id header falls through to Phase 17's
    state-based idempotency alone, same as before this phase)."""
    if event_id is not None:
        existing = db.query(WebhookEvent).filter(
            WebhookEvent.provider == PaymentProviderEnum.RAZORPAY, WebhookEvent.event_id == event_id
        ).first()
        if existing is not None:
            return existing

    try:
        body = json.loads(raw_body)
    except (json.JSONDecodeError, UnicodeDecodeError):
        event = _record(db, event_type="unknown", raw_body=raw_body, outcome="invalid_json", event_id=event_id)
        return _commit_or_recover_from_duplicate(db, event, event_id=event_id)

    event_type = body.get("event", "unknown")
    payload = body.get("payload", {})

    if event_type == "payment.captured":
        entity = payload.get("payment", {}).get("entity")
        event = (
            _handle_payment_captured(db, raw_body=raw_body, payment_entity=entity, background_tasks=background_tasks)
            if entity else _record(db, event_type=event_type, raw_body=raw_body, outcome="malformed_payload")
        )
    elif event_type == "payment.failed":
        entity = payload.get("payment", {}).get("entity")
        event = (
            _handle_payment_failed(db, raw_body=raw_body, payment_entity=entity)
            if entity else _record(db, event_type=event_type, raw_body=raw_body, outcome="malformed_payload")
        )
    elif event_type == "refund.processed":
        entity = payload.get("refund", {}).get("entity")
        event = (
            _handle_refund_processed(db, raw_body=raw_body, refund_entity=entity)
            if entity else _record(db, event_type=event_type, raw_body=raw_body, outcome="malformed_payload")
        )
    elif event_type == "refund.failed":
        entity = payload.get("refund", {}).get("entity")
        event = (
            _handle_refund_failed(db, raw_body=raw_body, refund_entity=entity)
            if entity else _record(db, event_type=event_type, raw_body=raw_body, outcome="malformed_payload")
        )
    else:
        # Any other genuine Razorpay event (payment.authorized, order.paid,
        # dispute.*, ...) — recorded for the audit trail, deliberately not
        # acted on. Returning 200 either way keeps Razorpay from retrying
        # an event this backend was never going to do anything with.
        event = _record(db, event_type=event_type, raw_body=raw_body, outcome="unhandled_event_type")

    event.event_id = event_id
    return _commit_or_recover_from_duplicate(db, event, event_id=event_id)


def _commit_or_recover_from_duplicate(db: Session, event: WebhookEvent, *, event_id: str | None) -> WebhookEvent:
    """Two genuinely concurrent deliveries of the same event can both pass
    the existence check above before either has committed — the same
    check-then-insert race Phase 6/14 already solved for Payment/PaymentAttempt.
    uq_webhook_events_provider_event_id lets exactly one commit win here;
    the loser rolls back everything it staged (including any Payment/Order
    mutation from this same call) and returns the winner's own row instead
    of erroring — a forged-looking race must never surface as a 500."""
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        existing = db.query(WebhookEvent).filter(
            WebhookEvent.provider == PaymentProviderEnum.RAZORPAY, WebhookEvent.event_id == event_id
        ).first()
        if existing is not None:
            return existing
        raise
    return event
