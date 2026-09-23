# Phase 24 — Razorpay Refund

## Scope
Implement refund through the provider abstraction: Admin → Refund Request
→ PaymentService → RazorpayProvider → Razorpay Refund → Refund Record →
Payment State. Do not mark a refund as completed solely because the
refund API request was accepted — track the provider refund state.

## What was found
`refund_service.create_refund()` (Phase 23) already called
`provider.initiate_refund()` for online payments, but treated any
non-raising response as `COMPLETED`. Real Razorpay refunds don't work
that way: the initiate-refund API accepting the request only means
Razorpay *started* processing it. Its own refund object reports a
distinct `status` — confirmed against Razorpay's docs — of `"processed"`
(genuinely settled), `"pending"` (accepted, still being processed by the
bank/network, not yet final), or `"failed"` (accepted, then rejected,
sometimes only discovered later). The code was silently coercing
`"pending"` to `COMPLETED`, exactly the gap this phase's own instructions
called out.

`_sum_refunds`-style amount bookkeeping (Phase 23) only ever summed
`COMPLETED` refunds when deciding what remained refundable — meaning a
refund left genuinely in flight wouldn't count against the captured
amount at all, letting a second refund request pass a check it should
have failed.

## What was built

### Honest status mapping in `create_refund()`
`provider_result.status` is now mapped explicitly:
- `"processed"` → `Refund.status = COMPLETED`
- `"failed"` → `Refund.status = FAILED`
- anything else (in practice, `"pending"`) → `Refund.status = PROCESSING`

The parent `Payment`'s own status (`recompute_payment_refund_status()`)
only ever reflects genuinely *settled* refunds — a refund recorded
`PROCESSING` leaves `Payment.payment_status` exactly where it already
was (still `PAID`/`PARTIALLY_REFUNDED`), never prematurely advanced.

### Two refund "committed" tiers, not one
`refund_service.py` now distinguishes:
- `_SETTLED_REFUND_STATUSES = (COMPLETED,)` — used by
  `recompute_payment_refund_status()`, the only thing that ever moves
  `Payment.payment_status`.
- `_COMMITTED_REFUND_STATUSES = (COMPLETED, PROCESSING)` — used by the
  amount-availability check in `create_refund()`, so a refund still being
  processed by Razorpay is just as "spoken for" as one that's already
  settled. Without this, two refunds could each independently pass the
  `amount <= remaining` check while only one has actually settled, and
  together exceed what was ever captured once both eventually resolve.

### Webhook resolution — `refund.processed` finishes the job
`_handle_refund_processed()` (Phase 17/18) now, after marking the
`Refund` row `COMPLETED`, fetches the parent `Payment` and calls
`recompute_payment_refund_status()` — so a refund that started
`PROCESSING` (because Razorpay hadn't confirmed settlement at
`create_refund()` time) correctly advances `Payment.payment_status` once
Razorpay's own webhook later confirms it did settle. Previously this
function only ever touched the `Refund` row in isolation.

### New `refund.failed` webhook handling
Razorpay can report a refund failure asynchronously, after having
initially accepted it (`PROCESSING`). A new `_handle_refund_failed()`
handler, wired into `process_webhook_event()`'s dispatch
(`elif event_type == "refund.failed":`), marks the `Refund` row `FAILED`
— idempotent against replay (already-`FAILED` is a no-op) and safe
against a late/out-of-order delivery arriving after the refund is somehow
already `COMPLETED` (ignored, same reasoning as `payment.failed`'s own
`ignored_already_paid` case: a later-arriving failure must never
downgrade an already-settled outcome). Deliberately never touches
`Payment.payment_status` — a `PROCESSING` refund was never counted as
settled in the first place, so a failure simply leaves nothing to undo;
the amount becomes refundable again automatically, since a `FAILED`
refund is excluded from `_COMMITTED_REFUND_STATUSES`.

### A staleness bug, found and fixed
While building this, `recompute_payment_refund_status()` (and the
now-removed `_already_refunded()` helper) were found to iterate the
in-memory `payment.refunds` relationship collection — which had already
been loaded/cached by the `db.refresh(payment)` call done earlier for the
row lock, *before* the new `Refund` row was created. A plain
`db.add(refund); db.flush()` does not automatically refresh other
already-loaded relationship collections in the same session, so the sum
was computed against a stale, pre-refund picture. Caught by a new test in
this phase (5 failures on first run). Fixed by refactoring `_sum_refunds`
to query the `Refund` table directly (`select(func.sum(...)).where(...)`)
instead of relying on the relationship — a fresh `SELECT` within the same
transaction always sees the just-flushed row, sidestepping the whole
class of staleness bug.

## Files modified
- `backend/app/services/payment/refund_service.py`
- `backend/app/services/payment/webhook_service.py`

## Files created
- `docs/payments/phase-24-razorpay-refund.md`

## Testing
- New: 4 tests in `test_payment_service_architecture.py` (pending →
  `PROCESSING` not `COMPLETED`; failed-without-raising → `FAILED`; a
  `PROCESSING` refund blocks a second refund for more than what remains;
  a `PROCESSING` refund resolving to `COMPLETED` via
  `recompute_payment_refund_status()` correctly updates `Payment`) + 5
  tests in `test_payment_webhooks.py` (`refund.processed` propagating a
  `PROCESSING` → `COMPLETED` refund to the parent `Payment`'s status;
  `refund.failed` marking a refund `FAILED`; never downgrading an
  already-`COMPLETED` refund; idempotent replay; unknown refund handled,
  not crashed) — 9 new tests total, all passing.
- Regression: one pre-existing test's exact-id assertion was updated
  after `FakeProvider.initiate_refund()` was changed to generate a
  distinct id per call (matching real Razorpay, which never reuses a
  refund id across multiple partial refunds of the same payment — the
  old fake generator collided on a payment's second refund, which the
  real `provider_refund_id` uniqueness constraint correctly rejected).
- `test_payment_webhooks.py` + `test_payment_service_architecture.py` +
  `test_admin_payments.py`: 72/72 passing.
- Full backend suite: 1176 passed, 10 skipped, 0 failed (baseline 1167 +
  9 new Phase 24 tests) — no regressions.

## Live verification (real dev server)
No real captured online payment exists in this environment to refund
(same recurring constraint as every online-payment phase since 14 — a
genuine Razorpay checkout needs a browser). What was verified live
instead, against the real dev server and the real Razorpay test API:

- `RazorpayProvider.initiate_refund()` called for real against Razorpay's
  live test API for a nonexistent payment id — a genuine network call,
  correctly returning a real `404`, correctly translated into a
  `ProviderRequestError` (matching Phase 11's own "real network call,
  real error, correctly translated" proof pattern, and exactly the path
  `create_refund()`'s own `except Exception` branch is built to catch).
- The live webhook endpoint's new `refund.failed` event type: an
  unsigned request is honestly rejected (`400`); a forged-signature
  request is honestly rejected (`503`, since no `RAZORPAY_WEBHOOK_SECRET`
  is configured in this dev environment — an honest "can't verify"
  failure, never a silent accept). Confirmed no `WebhookEvent` row was
  created from either rejected request.
- COD refunds (the `provider=None` branch) are untouched by this phase's
  edits — Phase 23's own live verification already proved a full COD
  refund round trip end to end, and the full regression suite confirms
  no behavior changed there.

## Known limitations
The genuine `PROCESSING` → `COMPLETED`/`FAILED` async resolution path can
only be proven against SQLite-backed unit tests and the real network's
honest-rejection behavior here — a true end-to-end proof (a real online
payment refunded, genuinely landing in `PROCESSING`, then resolved by a
real Razorpay-signed `refund.processed`/`refund.failed` webhook) needs a
browser-completed checkout and a configured `RAZORPAY_WEBHOOK_SECRET`,
neither available in this environment — same class of limitation
documented in Phases 14/15/17/18/22. `Order.payment_status` remains
unsynced by refunds (Phase 1's original, still-open gap, out of this
phase's scope).
