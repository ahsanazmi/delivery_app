# Phase 20 — Payment Retry

## Scope
Implement `POST /api/v1/payments/{id}/retry` (or equivalent). Before
retry: the order must still be payable, the payment must not already be
PAID, the order must not be cancelled, the order must not be delivered.
Create a new payment attempt if required; never overwrite historical
payment attempts.

## What was found
`POST /api/v1/payments/{id}/retry` already existed (Phase 5, refined in
Phase 19) and already enforced "payment must not already be PAID" (via
`_RETRYABLE_STATUSES` at the API layer). It never checked the **order's**
own state at all — a customer whose order had been cancelled (or, in
principle, delivered or rejected) while their payment was still
PENDING/FAILED could still call `/retry` and go on to pay for an order
that no longer existed to be paid for. `accept_order()`'s own Phase 16
gate already makes an *unpaid* razorpay order structurally unable to
reach DELIVERED, but nothing made that guarantee explicit at the retry
call site itself, and nothing at all protected against CANCELLED or
REJECTED.

## What was built
`PaymentService.retry_payment()` now fetches the order and refuses
(`PaymentError` → `409`, the same translation the endpoint already had in
place) when it's `CANCELLED`, `REJECTED`, or `DELIVERED` — checked in the
service layer itself, so the guarantee holds for any caller, not just
this one HTTP endpoint. No other behavior changed: a still-payable order
(`PLACED`, `CONFIRMED`, `PREPARING`, ...) continues to retry normally,
reopening the exact same provider order.

## Verified, not rebuilt
- **"Create a new payment attempt if required"** — already correct by
  construction: `retry_payment()` itself creates no `PaymentAttempt` row
  (there's nothing to record yet — no real attempt has happened at retry
  time); a genuinely new attempt is recorded the moment the customer
  actually retries and calls `/verify` again, exactly like any other
  attempt.
- **"Do not overwrite historical payment attempts"** — already correct:
  every `verify_payment()` call always `INSERT`s a new `PaymentAttempt`
  row, never updates an existing one. Confirmed with a dedicated test and
  live, directly against the `payment_attempts` table.

## Files modified
- `backend/app/services/payment/payment_service.py`

## Files created
- `backend/tests/test_payment_retry.py` (7 tests)
- `backend/tests/test_payment_api.py` (+5 tests)

## Testing
- New: 12 tests total — retry rejected for cancelled/rejected/delivered
  orders (both at the service layer, parametrized, and through the real
  HTTP API), retry still succeeds for every genuinely payable order
  status, and a fail → retry → fail-again → retry → succeed cycle proves
  every `PaymentAttempt` row survives untouched while a new one is
  created only when a real attempt actually happens (3 attempts total:
  the creation-time PENDING row, the first FAILED row, the final PAID
  row — none merged, none overwritten).
- Regression: 91/91 passing across every other payment test file.
- Full backend suite: run after this change (confirmed in the next
  phase's report if not already landed at report time).

## Live verification (real dev server)
Forged a signature failure on a real order, cancelled that same order as
the customer, then confirmed `/retry` refuses with 409 and a message
naming the cancelled status. A second real order proved the happy path
still works unchanged. Queried `payment_attempts` directly in Postgres
afterward and confirmed both the original creation-time row and the
failed-verification row exist as two separate, untouched records. 7/7
live checks passed; test data cleaned up.

## Known limitations
Unchanged from prior phases — the unguarded legacy `/payments/{id}/refund`
endpoint and `Order.payment_status` being a plain string remain open.
