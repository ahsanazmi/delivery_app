"""Payment System Phase 4 / Razorpay Refund (Phase 24) — orchestrates one
refund event against an existing Payment: validates the payment is
actually in a refundable state, checks the requested amount against what
Razorpay has already accepted, records a Refund row, calls the provider
(if this was an online payment — COD has no gateway to call back), and
updates both the Refund and the parent Payment's own status.

Deliberately does not decide *who* may call this or *when* — that's the
admin-gated flow's job (app/services/admin_payments.py, wired in Phase
23); this function trusts its caller has already established that.

Phase 24 — never marks a refund COMPLETED solely because Razorpay's API
accepted the initiate-refund request. Razorpay's own refund object has a
real, distinct status (confirmed against its docs): "processed" means
genuinely settled; "pending" means accepted but still being processed by
the bank/network, not yet final; "failed" is also possible, sometimes
returned only later. This module tracks that distinction end to end —
see create_refund()'s status mapping below and
webhook_service.py::_handle_refund_processed()/_handle_refund_failed()
for how a "pending" refund is later resolved to its real final state via
Razorpay's own refund.processed/refund.failed webhooks (the
provider-recommended, authoritative source for the final status, per
Razorpay's own docs)."""

from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.payment import Payment, PaymentStatus
from app.models.refund import Refund, RefundStatus
from app.services.payment.exceptions import RefundError
from app.services.payment.provider import PaymentProvider

_ZERO = Decimal("0.00")

_REFUNDABLE_STATUSES = (PaymentStatus.PAID, PaymentStatus.PARTIALLY_REFUNDED)
# Genuinely settled — money has actually moved back to the customer.
_SETTLED_REFUND_STATUSES = (RefundStatus.COMPLETED,)
# "Spoken for" — either settled or still being processed by Razorpay.
# Used for the amount-availability check so a second refund can never be
# accepted while an earlier one for the same payment is still in flight,
# even though it hasn't (yet) actually completed — otherwise both could
# independently pass the "amount <= remaining" check and, once both
# eventually settle, together exceed what was ever captured.
_COMMITTED_REFUND_STATUSES = (RefundStatus.COMPLETED, RefundStatus.PROCESSING)


def _sum_refunds(db: Session, payment_id, statuses: tuple[RefundStatus, ...]) -> Decimal:
    """Queried directly against the database rather than iterating
    payment.refunds — a relationship collection loaded earlier in the
    same session (e.g. by this same function's own caller, before a new
    Refund row was flushed) can go stale without an explicit refresh, and
    a figure this consequential (it decides whether a refund is even
    allowed, and what the parent Payment's own status becomes) must never
    risk working off a cached picture that's missing a row that
    genuinely already exists."""
    return db.scalar(
        select(func.coalesce(func.sum(Refund.amount), _ZERO)).where(
            Refund.payment_id == payment_id, Refund.status.in_(statuses)
        )
    ) or _ZERO


def recompute_payment_refund_status(db: Session, payment: Payment) -> None:
    """Payment/Order State Machine's own principle (Phase 22), applied to
    refunds: the parent Payment's status only ever reflects genuinely
    *settled* money, never an in-flight request. Safe to call any time a
    Refund's status changes to/from COMPLETED — from create_refund()
    itself when Razorpay confirms instantly, or later from the
    refund.processed webhook when it doesn't."""
    settled = _sum_refunds(db, payment.id, _SETTLED_REFUND_STATUSES)
    if settled <= _ZERO:
        return
    payment.payment_status = PaymentStatus.REFUNDED if settled >= payment.amount else PaymentStatus.PARTIALLY_REFUNDED


def create_refund(
    db: Session,
    *,
    payment: Payment,
    amount: Decimal,
    reason: str | None = None,
    provider: PaymentProvider | None,
) -> Refund:
    # Refund Architecture (Phase 23) — lock the payment row first (same
    # with_for_update() pattern admin_settle_cod() and
    # create_payment_for_order() already use for the same reason): two
    # near-simultaneous refund requests against the same payment (an
    # admin double-clicking "Refund," or two admins acting at once) would
    # otherwise both read the same already_refunded total before either
    # commits, and both could pass the amount <= remaining check —
    # together refunding more than was ever actually captured. A second,
    # truly concurrent call blocks here until the first resolves, then
    # correctly recomputes against the now-updated total.
    db.scalar(select(Payment).where(Payment.id == payment.id).with_for_update())
    # The lock query above only guarantees the *row* is now safe to act
    # on — this session's own in-memory `payment` object could still be
    # stale if it was fetched before the lock was acquired. Refreshing
    # forces its own columns to be re-read fresh once the lock is held
    # (the amount-availability check itself queries Refund directly, see
    # _sum_refunds's own note, so it's never at risk of this same kind of
    # staleness regardless).
    db.refresh(payment)

    if payment.payment_status not in _REFUNDABLE_STATUSES:
        raise RefundError(f"Cannot refund a payment in status '{payment.payment_status.value}'.")
    if amount <= _ZERO:
        raise RefundError("Refund amount must be greater than zero.")

    # Refund Architecture (Phase 23) / Razorpay Refund (Phase 24) — a
    # refund still being processed by Razorpay (PROCESSING) is just as
    # "spoken for" as one that's already settled; both count against the
    # captured amount so a second refund can never be accepted while an
    # earlier one is still in flight.
    committed = _sum_refunds(db, payment.id, _COMMITTED_REFUND_STATUSES)
    remaining = payment.amount - committed
    if amount > remaining:
        raise RefundError(f"Cannot refund {amount} — only {remaining} remains refundable on this payment.")

    refund = Refund(
        payment_id=payment.id, order_id=payment.order_id, amount=amount, reason=reason, status=RefundStatus.PENDING
    )
    db.add(refund)
    db.flush()

    if provider is not None:
        # Online payment — a real refund has to actually be issued at the
        # gateway. If the provider call fails, the Refund row is kept as a
        # FAILED record (never silently deleted) so there's a visible
        # trail of the attempt, and the exception propagates so the caller
        # knows this refund did not succeed.
        try:
            provider_result = provider.initiate_refund(
                provider_payment_id=payment.razorpay_payment_id, amount=amount, notes={"reason": reason or ""}
            )
        except Exception:
            refund.status = RefundStatus.FAILED
            db.commit()
            raise
        refund.provider_refund_id = provider_result.provider_refund_id
        # Phase 24 — never assume COMPLETED just because the API request
        # was accepted. Razorpay's own refund.status is the actual source
        # of truth here: "processed" is genuinely settled; anything else
        # ("pending", most commonly) means Razorpay accepted the request
        # but the bank/network hasn't confirmed it yet — recorded as
        # PROCESSING and left to the refund.processed webhook (Razorpay's
        # own recommended, authoritative final-status source) to resolve
        # later, exactly like a "failed" response would be recorded
        # honestly as FAILED rather than silently coerced to COMPLETED.
        if provider_result.status == "processed":
            refund.status = RefundStatus.COMPLETED
        elif provider_result.status == "failed":
            refund.status = RefundStatus.FAILED
        else:
            refund.status = RefundStatus.PROCESSING
    else:
        # COD — there is no gateway to call back; a COD refund is a manual,
        # offline cash handback that an admin records after the fact, so
        # it's considered complete the moment it's recorded.
        refund.status = RefundStatus.COMPLETED

    # Partial Refunds (Phase 25) — a real, previously-hidden bug: this
    # session (app/db/session.py's own SessionLocal) is configured with
    # autoflush=False, so the refund.status reassignment just above was
    # never actually visible to the SELECT-based SUM inside
    # recompute_payment_refund_status()'s own _sum_refunds() call below
    # — it would only ever see this refund's *original* flush, from the
    # db.flush() above, while it was still PENDING. The payment's own
    # status silently never advanced to PARTIALLY_REFUNDED/REFUNDED on
    # a real refund, in production, despite every test in this suite
    # passing — every test session in this codebase is a plain
    # Session(engine) (autoflush=True by default), which happened to
    # flush this same reassignment automatically before its own queries,
    # masking the bug completely. An explicit flush here makes the fix
    # correct regardless of either session's autoflush setting, rather
    # than depending on it.
    db.flush()

    # The payment's own status only ever reflects genuinely *settled*
    # refunds (Phase 24) — a PROCESSING or FAILED refund leaves it exactly
    # where it already was; recompute_payment_refund_status() is a no-op
    # unless this refund just became COMPLETED.
    recompute_payment_refund_status(db, payment)
    db.commit()
    db.refresh(refund)
    return refund
