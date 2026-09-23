# Phase 32 — Payment Failure & Recovery Testing

## Scope
Test: internet disconnect during checkout; app closed during payment;
payment succeeds but callback is lost; webhook arrives before frontend
verification; frontend verification arrives before webhook; webhook
arrives multiple times; payment provider temporarily unavailable;
payment remains pending; customer retries; customer cancels; order
expires. The final backend state must remain consistent.

## Method
A dedicated research pass traced all eleven scenarios against the
existing codebase before writing any code, specifically to find real
gaps rather than assume everything already worked. It found two:

1. **A transient provider outage during `/verify` was treated
   identically to a genuine rejection** — marking the payment `FAILED`
   and firing false "payment failed" alerts to the customer and an
   admin, even though the payment may well have actually captured at
   Razorpay and this backend simply couldn't confirm it. Unambiguous,
   fixed regardless of any further decision.
2. **"Order expires" (scenario 11) didn't exist as any mechanism at
   all** — no scheduler/cron infrastructure exists anywhere in this
   codebase, so a payment a customer abandons mid-checkout stayed
   `PENDING` and fully retryable forever, with no cutoff. Confirmed with
   the user before building anything (a real architectural choice: lazy
   on-access expiry vs. a real background job vs. documentation only) —
   chose **lazy expiry on access**: no new infrastructure, checked the
   moment anyone next tries to act on a stale payment.

Everything else — webhook idempotency (Phase 18), dead-order handling
(Phase 22), retry (Phase 20) — was already correct; this phase adds
explicit, canonical tests proving each scenario, consolidated in one
file, the same pattern Phase 31 established.

## What was built

### Fix 1 — provider-unreachable-during-verify is no longer a false failure
`PaymentService.verify_payment()`: when `provider.fetch_payment()`/
`fetch_order()` raise `ProviderRequestError` (a network/timeout failure,
not a rejection), the parent `Payment` is now left completely
untouched — no `FAILED`, no admin/customer "payment failed"
notifications. A `PaymentAttempt` row still records the attempt
honestly (`PROVIDER_UNREACHABLE`), and the caller gets a distinct,
retryable `ProviderRequestError` → `502` (matching the 502
`create_payment_for_order()` already returns for the identical
underlying exception at payment-creation time), rather than a flat
`400 "Payment verification failed"` indistinguishable from a genuine
signature/amount rejection.

**A follow-on bug found while testing this fix**: retrying `/verify`
with the exact same `(provider_order_id, provider_payment_id)` pair
after a `PROVIDER_UNREACHABLE` attempt hit
`uq_payment_attempts_provider_payment_id` — the very first
`PaymentAttempt` row (from the failed attempt) already claimed that
`provider_payment_id` globally, so a legitimate retry against the exact
same Razorpay payment (Razorpay never reissues a new `payment_id` just
because this backend couldn't reach it) was wrongly rejected as
`PROVIDER_ID_ALREADY_USED` — the same code path meant for catching a
genuinely replayed id across two *different* payments. Fixed: the
collision-recovery path now checks whether the existing attempt row
belongs to *this same payment* — if so, it's a legitimate retry of the
identical pairing, and that one row is updated in place with the new,
truer outcome (the only narrow exception to `PaymentAttempt`'s
append-only design, since `(provider, provider_payment_id)` can only
ever have one row by construction); a collision against a genuinely
*different* payment is still rejected exactly as before.

### Fix 2 — lazy payment/order expiry
New `_PAYMENT_EXPIRY_WINDOW = timedelta(minutes=30)` (a documented,
adjustable business rule, same pattern as `COD_SETTLEMENT_DUE_THRESHOLD`)
and `_is_payment_expired(payment)`, checked at the top of both
`verify_payment()` (before ever calling the provider — no point spending
a real network call on a closed checkout window) and `retry_payment()`.
An expired payment is resolved to a clean, terminal `FAILED` with a
clear failure reason ("This payment has expired. Please place a new
order.") — but, unlike a genuine rejection, **no admin/customer alert
fires**: an abandoned checkout is routine, not an anomaly worth paging
anyone about. New `PaymentExpiredError` exception, surfaced as a
distinct `410 Gone` at both the `/verify` and `/retry` endpoints.

## Scenario-by-scenario result

| # | Scenario | Result |
|---|---|---|
| 1 | Internet disconnect during checkout | A payment left `PENDING` with zero calls made is safe, uncorrupted, and still normally actionable later. |
| 2 | App closed during payment | Same guarantee as #1 — nothing about an abandoned in-progress checkout corrupts state. |
| 3 | Payment succeeds, callback lost | The webhook alone, with **no** `/verify` call ever made, correctly resolves the payment to `PAID`. |
| 4 | Webhook before frontend verification | Webhook marks `PAID` first; the endpoint's own `_VERIFIABLE_STATUSES` gate excludes `PAID`, so a late `/verify` is safely rejected before touching anything; a second webhook-shaped event is `duplicate_ignored`, never re-timestamped. |
| 5 | Frontend verification before webhook | `/verify` marks `PAID` first; the later genuine webhook for the same event resolves to `duplicate_ignored`, `paid_at` untouched. |
| 6 | Webhook arrives multiple times | Three deliveries of the identical `event_id` → one `WebhookEvent` row, one `PAID` transition, verified live against the real database. |
| 7 | Payment provider temporarily unavailable | **Fixed this phase** (see Fix 1) — payment stays `PENDING`, no false alerts, distinct `502`, genuinely retryable once reachable again. |
| 8 | Payment remains pending | A fresh `PENDING` payment (within the expiry window) is completely unaffected by the new expiry check — verifies normally. |
| 9 | Customer retries | Retry reopens the same provider order (never a new `Payment` row); both the failed and the eventually-successful attempt keep their own distinct `PaymentAttempt` rows. |
| 10 | Customer cancels | `cancel_order()` leaves an in-flight `Payment` completely untouched; a later webhook reporting capture for the now-cancelled order is correctly flagged `REFUND_PENDING` with an admin alert (Phase 22), never silently marked `PAID`. |
| 11 | Order expires | **Built this phase** (see Fix 2) — a stale `PENDING` payment past the window is rejected with `410 Gone` on the next `/verify` or `/retry` attempt, resolved to a clean terminal `FAILED`, no false alerts. |

## Files modified
- `backend/app/services/payment/payment_service.py`
- `backend/app/services/payment/exceptions.py`
- `backend/app/api/v1/endpoints/payments.py`

## Files created
- `backend/tests/test_payment_failure_recovery.py`
- `docs/payments/phase-32-payment-failure-recovery-testing.md`

## Testing
- New: 11 tests in `test_payment_failure_recovery.py`, one per named
  scenario, all passing. Two test-authoring bugs were found and fixed
  while writing them (a mismodeled webhook-idempotency assertion; a
  phone-number fixture collision) — neither was a product bug.
- Regression: 122 tests across every payment-adjacent test file
  (signature verification, retry, webhooks, idempotency, security audit,
  ledger validation, COD end-to-end) — all still passing after both
  fixes, confirming the `PaymentAttempt` collision-recovery change in
  particular didn't disturb any existing replay/duplicate-detection
  guarantee.
- Full backend suite: **1219 passed, 10 skipped, 0 failed** (baseline
  1208 + 11 new). One unrelated, pre-existing flaky test
  (`test_admin_authentication.py::test_admin_with_a_tampered_token_is_rejected`)
  failed on the first full-suite run and passed both in isolation and on
  a second full run — its own tamper method (flipping only the JWT's
  very last base64 character) can, for specific token values, land on a
  base64 padding bit that decodes to the identical signature bytes,
  making the "tampered" token accidentally still valid. Unrelated to any
  change in this phase; not touched, since it belongs to a different
  phase's own test file and scope.

## Live verification (real dev server)
Seeded a real order with a `Payment` row whose `created_at` was
deliberately backdated two hours (well past the 30-minute expiry
window) directly in the real Postgres database, then drove the real
HTTP endpoints:
- `POST /payments/{id}/verify` → `410 Gone`,
  `"This payment has expired. Please place a new order."`
- Confirmed via direct `psql` query: `payment_status = 'failed'`,
  `failure_reason` set to the expiry message — and confirmed **no**
  `payment_failure`-type notification was created for this order (only
  the routine `order_placed` one), proving the "no false alarm for a
  routine expiry" guarantee holds against the real database, not just a
  unit test assertion.
- `POST /payments/{id}/retry` on that same now-`FAILED` payment → also
  `410 Gone` — confirming expiry is enforced consistently across both
  entry points, not just the one first hit.

All live test data cleaned up afterward (`psql`, FK-dependency order,
verified zero rows remaining).

## Known limitations
Scenario 7's live proof is necessarily limited to the unit-level
`FakeProvider`/`_ScriptedProvider` substitution — genuinely forcing a
real network-level failure against Razorpay's live API on demand isn't
producible headlessly, the same class of limitation documented since
Phase 11. The 30-minute expiry window is a fixed constant, not yet
configurable via admin settings — a reasonable future extension if the
business wants to tune it, not something this phase's own scope asked
for.
