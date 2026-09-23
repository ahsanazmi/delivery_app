"""Payment System Phase 4 — the one place the rest of the application
should ever go to start, verify, refund, or inspect a payment. Route
handlers call PaymentService; PaymentService is the only thing that ever
touches a PaymentProvider. This keeps the promise the master command's
own architecture diagram makes:

    API -> PaymentService -> PaymentProvider -> RazorpayProvider -> Razorpay

Wired into app/api/v1/endpoints/payments.py as of Payment System Phase 5
— see that router and this phase's own completion report.
"""

import logging
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.notification import NotificationType
from app.models.order import Order, OrderStatus
from app.models.payment import Payment
from app.models.payment import PaymentProvider as PaymentProviderEnum
from app.models.payment import PaymentStatus
from app.models.payment_attempt import PaymentAttempt
from app.models.refund import Refund
from app.services.notifications import notify_admins, notify_customer_payment_failed
from app.services.payment import refund_service
from app.services.payment.exceptions import (
    PaymentError,
    PaymentExpiredError,
    PaymentVerificationError,
    ProviderRequestError,
)
from app.services.payment.provider import PaymentProvider
from app.services.payment.razorpay_provider import RazorpayProvider

logger = logging.getLogger(__name__)

_ONLINE_METHOD = "razorpay"
_COD_METHOD = "cod"

# Payment Failure & Recovery Testing (Phase 32) — "Order expires". No
# scheduler/cron exists anywhere in this codebase (confirmed by audit),
# so this is deliberately a lazy, on-access check rather than a
# background job: an abandoned checkout is never actively hunted down,
# but the moment anyone next tries to act on it (a customer's own
# /verify or /retry call), it's resolved to a clean, terminal, non-actionable
# state instead of staying ambiguously PENDING/retryable forever. A
# documented, adjustable business rule, not derived from anything —
# same pattern as COD_SETTLEMENT_DUE_THRESHOLD in rider_deliveries.py.
_PAYMENT_EXPIRY_WINDOW = timedelta(minutes=30)


def _is_payment_expired(payment: Payment) -> bool:
    created_at = payment.created_at
    # SQLite (the test suite's engine) hands back a naive datetime even
    # for a DateTime(timezone=True) column, unlike Postgres — every
    # created_at in this codebase is always written in UTC regardless
    # (server_default=func.now() / datetime.now(UTC)), so a naive value
    # is always safely UTC, never ambiguous.
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=UTC)
    return datetime.now(UTC) - created_at > _PAYMENT_EXPIRY_WINDOW


class PaymentService:
    def __init__(self, providers: dict[str, PaymentProvider] | None = None) -> None:
        # Real providers are only ever constructed lazily / injected — this
        # class must be safely instantiable even when RAZORPAY_KEY_ID/
        # SECRET aren't configured (e.g. this dev environment today);
        # RazorpayProvider itself only raises ProviderNotConfiguredError
        # when a method that actually needs credentials is called.
        self._providers: dict[str, PaymentProvider] = providers if providers is not None else {
            _ONLINE_METHOD: RazorpayProvider()
        }

    def _provider_for(self, method: str) -> PaymentProvider:
        try:
            return self._providers[method]
        except KeyError as exc:
            raise PaymentError(f"No payment provider registered for method '{method}'.") from exc

    def create_payment_for_order(self, db: Session, *, order: Order, method: str) -> Payment:
        """The amount is always order.total — never accepted from a
        caller. Idempotent: a second call for the same order returns the
        existing Payment rather than creating a duplicate (the same
        guarantee uq_payments_order_id already enforces at the database
        level for every other path that creates a Payment).

        Idempotent Order Payment Creation (Phase 21) — covers a double
        tap, a network-retry, an app restart, or any other repeated
        checkout/payment-initialization request for the same order,
        including two that genuinely overlap in time. The order row is
        locked first (same with_for_update() pattern admin_settle_cod()
        already uses for the same reason): a second, truly concurrent
        call for the same order_id blocks here until the first either
        commits or rolls back, then re-reads and finds the row the first
        call just created — closing the gap the uq_payments_order_id
        constraint alone doesn't: without this lock, two overlapping
        callers could both pass the "does a payment exist yet?" check
        below before either commits, and for an online payment, both
        would go on to open a real, separate Razorpay order before the
        database ever resolved which one wins — a wasted, orphaned
        provider-side order even though only one Payment row ever
        survives. Locking here means the provider is only ever called by
        the one caller that's actually going to win."""
        db.scalar(select(Order).where(Order.id == order.id).with_for_update())

        existing = db.query(Payment).filter(Payment.order_id == order.id).first()
        if existing:
            return existing

        if method == _COD_METHOD:
            payment = Payment(
                order_id=order.id, user_id=order.user_id, provider=PaymentProviderEnum.COD, amount=order.total
            )
            db.add(payment)
        else:
            # Idempotent Order Payment Creation (Phase 21) — the insert is
            # flushed *before* the provider is ever called, specifically
            # so a colliding uq_payments_order_id is caught here — by the
            # same try/except this whole block now sits inside — instead
            # of raising uncaught out of db.flush() itself. Before this
            # fix, a race that got past the lock above (e.g. on a
            # database that doesn't honor with_for_update the way
            # Postgres does) surfaced as an unhandled 500 here, never
            # reaching the recovery path below at all.
            provider = self._provider_for(method)
            payment = Payment(
                order_id=order.id, user_id=order.user_id, provider=PaymentProviderEnum.RAZORPAY,
                amount=order.total, payment_status=PaymentStatus.PENDING,
            )
            db.add(payment)
            try:
                db.flush()
            except IntegrityError:
                db.rollback()
                return db.query(Payment).filter(Payment.order_id == order.id).first()

            provider_order = provider.create_order(amount=order.total, currency="INR", receipt=str(order.id))
            payment.razorpay_order_id = provider_order.provider_order_id
            db.add(PaymentAttempt(
                payment_id=payment.id, provider=PaymentProviderEnum.RAZORPAY,
                provider_order_id=provider_order.provider_order_id, amount=order.total, status=PaymentStatus.PENDING,
            ))

        try:
            db.commit()
        except IntegrityError:
            # Two near-simultaneous callers both saw no existing payment
            # above and both tried to insert one — uq_payments_order_id
            # lets exactly one win; the loser rolls back and returns the
            # winner's row instead of raising (matches the retry-tolerant
            # philosophy Phase 3's migration review already established:
            # never let an idempotency race surface as a 500).
            db.rollback()
            return db.query(Payment).filter(Payment.order_id == order.id).first()
        db.refresh(payment)
        return payment

    def verify_payment(
        self, db: Session, *, payment: Payment, provider_order_id: str, provider_payment_id: str, signature: str
    ) -> Payment:
        """Records one PaymentAttempt regardless of outcome (this is
        exactly the history the old single-mutable-row design couldn't
        keep — see Phase 2), then updates the parent Payment only on
        success.

        Payment Signature Verification (Phase 14) / Payment Amount
        Validation (Phase 15) — never trusts a payment_id alone, a
        frontend callback, or a client-supplied status; every one of the
        following must independently agree before this payment is ever
        marked PAID:

        1. Order ID — provider_order_id must be the exact order this
           payment was opened against at creation time
           (payment.razorpay_order_id, fixed then, never reassigned
           here), AND the fetched payment's own order_id (as Razorpay
           itself reports it, not just what the client claimed) must
           agree too. Without the first half, a genuinely-valid signature
           for a *different* real Razorpay transaction (e.g. one this
           same customer legally completed on a cheap, unrelated order)
           could otherwise be replayed against this payment's own verify
           call — the HMAC alone only proves Razorpay signed *some*
           order/payment pair, not that it's *this* payment's pair.
        2. Signature — the HMAC check.
        3. Razorpay payment amount / currency / state — fetch_payment()
           independently confirms the amount and currency Razorpay
           actually captured, and that its own status is "captured" (not
           merely "authorized" — money hasn't actually settled until
           captured) — never inferred from the order/amount link made at
           creation time alone.
        4. Razorpay order amount / currency — fetch_order() re-confirms
           the order's own amount/currency fresh, independently of what
           was recorded once at create_order() time.
        5. Internal payment amount — payment.amount is the reference
           value every other check above is measured against; it is
           itself never taken from this call's arguments.

        Any single disagreement fails the whole verification — never a
        partial success — and is logged as a clear, specific error
        alongside the PaymentAttempt audit row.
        """
        provider = self._provider_for(_ONLINE_METHOD)

        failure_code: str | None = None
        failure_message: str | None = None

        order_matches = payment.razorpay_order_id is not None and provider_order_id == payment.razorpay_order_id
        if not order_matches:
            failure_code = "ORDER_MISMATCH"
            failure_message = "This payment does not belong to the given Razorpay order."

        # Payment Failure & Recovery Testing (Phase 32) — "Order expires".
        # Checked before ever calling the provider at all: no point
        # spending a real network call verifying a signature for a
        # checkout window that's already closed, and an abandoned
        # checkout resumed long after the fact is exactly the case this
        # guards against (see _is_payment_expired's own note).
        expired = order_matches and _is_payment_expired(payment)
        if expired:
            failure_code = "PAYMENT_EXPIRED"
            failure_message = "This payment has expired. Please place a new order."

        is_valid = order_matches and not expired and provider.verify_payment_signature(
            provider_order_id=provider_order_id, provider_payment_id=provider_payment_id, signature=signature
        )
        if order_matches and not expired and not is_valid:
            failure_code = "SIGNATURE_MISMATCH"
            failure_message = "Payment signature verification failed."

        if is_valid:
            try:
                fetched_payment = provider.fetch_payment(provider_payment_id)
                fetched_order = provider.fetch_order(payment.razorpay_order_id)
            except ProviderRequestError:
                is_valid = False
                failure_code = "PROVIDER_UNREACHABLE"
                failure_message = "Could not confirm this payment's details with the provider."
            else:
                if fetched_payment.provider_order_id != payment.razorpay_order_id:
                    is_valid = False
                    failure_code = "ORDER_MISMATCH"
                    failure_message = "The provider's own record of this payment points at a different order."
                elif fetched_payment.status != "captured":
                    is_valid = False
                    failure_code = "PAYMENT_NOT_CAPTURED"
                    failure_message = f"Payment is '{fetched_payment.status}' at the provider, not captured."
                elif fetched_payment.amount != payment.amount or fetched_order.amount != payment.amount:
                    is_valid = False
                    failure_code = "AMOUNT_MISMATCH"
                    failure_message = "The amount confirmed by the provider does not match this order's total."
                elif fetched_payment.currency != payment.currency or fetched_order.currency != payment.currency:
                    is_valid = False
                    failure_code = "CURRENCY_MISMATCH"
                    failure_message = "The currency confirmed by the provider does not match this order's currency."

        # Payment Failure & Recovery Testing (Phase 32) — a transient
        # network/timeout failure reaching the provider is NOT the same
        # fact as a genuine rejection (wrong signature, tampered amount,
        # replayed id, etc.): the payment may well have actually captured
        # at Razorpay, and this backend simply couldn't confirm it right
        # now. Treating it identically to a real rejection — marking the
        # payment FAILED and firing "payment failed" alerts to the
        # customer and an admin — would be a false alarm, and a needless,
        # possibly wrong, terminal state. This case still records its own
        # PaymentAttempt below (the attempt itself genuinely didn't
        # complete), but the parent Payment's own status is left exactly
        # as it already was, and the caller sees a distinct, retryable
        # error instead of a flat rejection.
        provider_unreachable = failure_code == "PROVIDER_UNREACHABLE"

        if not is_valid and not provider_unreachable and not expired:
            # Payment Amount Validation (Phase 15) — a clear, specific log
            # record for every rejection, distinct from the PaymentAttempt
            # audit row and the admin/customer notifications below. Never
            # logs the signature itself (on the never-log list, per Phase
            # 26's own established rule).
            logger.warning(
                "Payment error: verification rejected for payment %s (order %s) — %s: %s",
                payment.id, payment.order_id, failure_code, failure_message,
            )

        attempt = PaymentAttempt(
            payment_id=payment.id, provider=PaymentProviderEnum.RAZORPAY,
            provider_order_id=provider_order_id, provider_payment_id=provider_payment_id,
            amount=payment.amount, status=PaymentStatus.PAID if is_valid else PaymentStatus.FAILED,
            failure_code=failure_code, failure_message=failure_message,
        )
        db.add(attempt)
        try:
            db.flush()
        except IntegrityError:
            # uq_payment_attempts_provider_payment_id (Phase 3) uniquely
            # claims (provider, provider_payment_id) across every payment,
            # not just this one.
            db.rollback()
            existing_attempt = db.scalar(
                select(PaymentAttempt).where(
                    PaymentAttempt.provider == PaymentProviderEnum.RAZORPAY,
                    PaymentAttempt.provider_payment_id == provider_payment_id,
                )
            )
            if existing_attempt is not None and existing_attempt.payment_id == payment.id:
                # Payment Failure & Recovery Testing (Phase 32) — not a
                # replay: this exact payment retrying verification against
                # its own already-recorded (order_id, payment_id) pair —
                # most commonly after a transient PROVIDER_UNREACHABLE
                # attempt (Razorpay never reissues a new payment_id just
                # because this backend couldn't reach it the first time,
                # so a legitimate retry naturally reuses the same id).
                # There's nowhere else for this call's own real outcome to
                # live — (provider, provider_payment_id) can only ever
                # have one row — so the one existing row for this exact
                # pairing is updated to the current, truer outcome rather
                # than a second one being impossible to insert. Still
                # never touched across *different* payments or
                # *different* provider_payment_ids — only this one,
                # narrow, same-pairing-retried-again case.
                existing_attempt.status = PaymentStatus.PAID if is_valid else PaymentStatus.FAILED
                existing_attempt.failure_code = failure_code
                existing_attempt.failure_message = failure_message
                attempt = existing_attempt
            else:
                # A forged/replayed provider_payment_id already recorded
                # against a *different* payment must still resolve to a
                # clean rejection here, not an unhandled 500 crashing the
                # request — the audit-trail row is secondary to that
                # guarantee holding.
                is_valid = False
                failure_code = failure_code or "PROVIDER_ID_ALREADY_USED"
                failure_message = failure_message or "This payment id has already been used for a different payment."

        if not is_valid and provider_unreachable:
            # The attempt row above already records this honestly; the
            # parent Payment is deliberately untouched — no FAILED, no
            # notifications, since neither is a fact this backend actually
            # knows to be true right now.
            db.commit()
            raise ProviderRequestError("Unable to reach the payment provider right now. Please try again.")

        if not is_valid and expired:
            # A closed, terminal state — but a routine one, not an
            # anomaly. No admin/customer "payment failed" alert: an
            # abandoned checkout isn't a rejection or an attack, and
            # paging anyone about it would just be noise.
            payment.payment_status = PaymentStatus.FAILED
            payment.failure_reason = failure_message
            db.commit()
            raise PaymentExpiredError(failure_message)

        if not is_valid:
            payment.payment_status = PaymentStatus.FAILED
            payment.failure_reason = failure_message
            # Same two-sided notification the pre-Phase-5 verify_payment()
            # already sent (Phase 20) — an admin alert plus the customer's
            # own payment_update notification, both flushed before the
            # commit below so they persist atomically with the failure.
            order = db.get(Order, payment.order_id)
            notify_admins(
                db, NotificationType.PAYMENT_FAILURE, "Payment failure",
                f"Payment verification failed for order {payment.order_id}.", order_id=payment.order_id,
            )
            if order:
                notify_customer_payment_failed(
                    db, user_id=payment.user_id, order_id=payment.order_id, order_number=order.order_number
                )
            db.commit()
            raise PaymentVerificationError(failure_message or "Payment verification failed.")

        payment.is_verified = True
        payment.razorpay_payment_id = provider_payment_id
        payment.razorpay_signature = signature
        payment.paid_at = datetime.now(UTC)

        order = db.get(Order, payment.order_id)

        # Payment/Order State Machine (Phase 22) — "do not allow CANCELLED
        # + a newly successful payment without a defined refund/
        # reconciliation workflow." The money genuinely moved at the
        # provider by the time this code runs (every check above already
        # passed) — rejecting the verification here would not un-charge
        # the customer, it would just make this backend deny a real
        # charge ever happened. The defined workflow is: record it
        # honestly as REFUND_PENDING (never a plain PAID, which would
        # look like a normal, resolved success) and raise an urgent admin
        # alert for manual refund/reconciliation, rather than silently
        # marking a dead order's payment as paid or auto-refunding a real
        # charge without human review. The order's own fields are
        # deliberately left untouched — it stays showing exactly the dead
        # state it already had; the anomaly is surfaced through the
        # payment's own status and this alert, not by making the order
        # look paid when it can no longer be fulfilled.
        if order and order.status in (OrderStatus.CANCELLED, OrderStatus.REJECTED):
            payment.payment_status = PaymentStatus.REFUND_PENDING
            logger.warning(
                "Payment error: payment %s for order %s (status %s) was successfully captured "
                "after the order was already %s — flagged for refund/reconciliation, not auto-paid.",
                payment.id, payment.order_id, order.status.value, order.status.value,
            )
            notify_admins(
                db, NotificationType.SYSTEM_ALERT, "Payment succeeded for a cancelled/rejected order",
                f"Order {order.order_number} is {order.status.value}, but its payment (id {payment.id}) "
                f"was just captured for {payment.amount} {payment.currency}. Needs manual refund/reconciliation.",
                order_id=payment.order_id,
            )
            db.commit()
            db.refresh(payment)
            return payment

        payment.payment_status = PaymentStatus.PAID

        # Payment Status Synchronization (Phase 16) — the one, explicit
        # side effect this workflow requires: the order's own payment
        # fields mirror the payment that was just confirmed. Deliberately
        # touches only payment_status/is_paid — never order.status (which
        # stays PLACED, exactly as create_order() left it; the restaurant
        # still separately accepts/rejects through its own normal flow —
        # see accept_order()'s own payment-confirmed gate for online
        # orders), never any Restaurant field, never anything rider-side.
        if order:
            order.payment_status = "paid"
            order.is_paid = True

        db.commit()
        db.refresh(payment)
        return payment

    # Payment Retry (Phase 20) — an order in any of these states is dead
    # or already fulfilled; there is nothing left to pay for. CANCELLED
    # and REJECTED are both non-payable terminal outcomes (a customer
    # cancellation or a restaurant rejection); DELIVERED is a *successful*
    # terminal outcome, called out explicitly by this phase even though
    # accept_order()'s own Phase 16 gate already makes it structurally
    # unreachable for an unpaid razorpay order today — this is the
    # explicit, defense-in-depth version of that same guarantee, not
    # reliant on that other gate continuing to hold forever.
    _NON_PAYABLE_ORDER_STATUSES = (OrderStatus.CANCELLED, OrderStatus.REJECTED, OrderStatus.DELIVERED)

    def retry_payment(self, db: Session, *, payment: Payment) -> Payment:
        """A retry reopens the *same* provider order rather than creating a
        new one — this is how Razorpay's own checkout flow already works
        (the same order id legitimately accepts more than one attempt;
        see Phase 3's own uq_payment_attempts_provider_payment_id
        reasoning), and it avoids an unnecessary second call to the
        provider just to resume something already open there.

        Before retry (Phase 20) — every one of this phase's own named
        conditions is checked here, in the service layer, so this method
        is the single authoritative guard regardless of which caller
        invokes it (never duplicated, and never skippable, at just the
        HTTP layer):
        - Payment must not already be PAID — the caller's own state check
          (_RETRYABLE_STATUSES at the API layer) already keeps a PAID
          payment from reaching this method in the first place; this
          method doesn't re-derive that itself since it has no way to
          know "retryable" beyond what its caller already established,
          but nothing here ever moves a PAID payment either.
        - Order must still be payable — not cancelled, not rejected, not
          delivered.
        No new PaymentAttempt row is created here — an attempt record
        only ever means a real attempt actually happened (see
        verify_payment()); retrying just reopens the door for the next
        real one, which creates its own attempt row when it happens,
        alongside every prior one, never overwriting them."""
        if payment.provider != PaymentProviderEnum.RAZORPAY:
            raise PaymentError("Only online payments can be retried.")
        if not payment.razorpay_order_id:
            raise PaymentError("This payment was never opened with the provider — create a new payment instead.")

        order = db.get(Order, payment.order_id)
        if order and order.status in self._NON_PAYABLE_ORDER_STATUSES:
            raise PaymentError(f"This order is {order.status.value} and can no longer be paid.")

        # Payment Failure & Recovery Testing (Phase 32) — "Order expires",
        # same lazy on-access check verify_payment() applies, so a stale
        # checkout can't be resumed by retrying either — see
        # _is_payment_expired's own note.
        if _is_payment_expired(payment):
            payment.payment_status = PaymentStatus.FAILED
            payment.failure_reason = "This payment has expired. Please place a new order."
            db.commit()
            raise PaymentExpiredError(payment.failure_reason)

        payment.payment_status = PaymentStatus.PENDING
        payment.failure_reason = None
        db.commit()
        db.refresh(payment)
        return payment

    def refund(self, db: Session, *, payment: Payment, amount: Decimal, reason: str | None = None) -> Refund:
        provider = self._providers.get(_ONLINE_METHOD) if payment.provider == PaymentProviderEnum.RAZORPAY else None
        return refund_service.create_refund(db, payment=payment, amount=amount, reason=reason, provider=provider)

    def get_payment_for_order(self, db: Session, order_id: UUID) -> Payment | None:
        return db.query(Payment).filter(Payment.order_id == order_id).first()
