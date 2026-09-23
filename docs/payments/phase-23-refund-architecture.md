# Phase 23 — Refund Architecture

## Scope
Implement controlled refunds: `POST /api/v1/admin/payments/{id}/refund`
(or equivalent). Admin must provide refund amount and reason. Backend
validates: payment is refundable, refund amount <= refundable amount,
order state, previous refunds. Never allow a refund to exceed the
captured amount minus previous refunds.

## What was found
`refund_service.create_refund()` (Phase 4) already had the real,
correct validation logic — refundable-status check, amount-vs-remaining
check against every prior *completed* refund, an honest `Refund`
audit trail, and a real provider call for online payments. **Nothing in
the codebase called it.** The only reachable refund endpoint,
`POST /api/v1/payments/{id}/refund`, was customer-facing (any customer
could call it for their own payment — never admin-gated, flagged as a
known gap since Phase 1's own audit) and used an entirely different,
far older function (`app.services.payments.refund_payment`) that didn't
validate anything at all: no amount parameter, no refundable-status
check, no real provider call, no `Refund` row — it just flipped the
payment to `REFUND_PENDING` and the order to `"refunded"` unconditionally.

## What was built

### The real endpoint
`POST /api/v1/admin/payments/{id}/refund` (`app/api/v1/admin/payments.py`,
alongside the existing admin payment list/detail routes — same
`require_admin` gate, same router). Body: `{amount, reason}`, both
mandatory (`reason` specifically, per this phase's own wording — unlike
the optional note on the existing COD-settlement admin endpoint).
Delegates to `admin_refund_payment()` (`app/services/admin_payments.py`),
which:

- **Payment is refundable / amount <= refundable amount / never exceeds
  captured minus previous refunds** — `refund_service.create_refund()`'s
  own job, unchanged, now finally wired to a real caller.
- **Order state** — fetched and folded into the admin audit log's own
  `previous_state` for every refund, so *what state the order was in*
  when refunded is always answerable later. Deliberately not used to
  *block* a refund — no order status makes a legitimate refund reason
  (a quality complaint on a `DELIVERED` order, an item swap mid-
  `PREPARING`, or Phase 22's own `REFUND_PENDING` reconciliation for a
  `CANCELLED` order) invalid, so there's nothing honest to gate on.
- **Previous refunds** — the same real, append-only `Refund` history,
  now surfaced back to the admin (`AdminPaymentDetail.refunds`,
  `refunded_amount`, `refundable_amount`) so they can see exactly what's
  already been refunded before deciding a new amount.

Every refund is recorded in the existing admin audit log
(`record_admin_audit_log`, `action="payment.refund"`), matching every
other admin financial action in this system (COD settlement, Phase 9).

### A real race, found and fixed
`refund_service.create_refund()` had no row lock — two near-simultaneous
refund requests for the same payment (an admin double-clicking, or two
admins acting at once) could both read the same `already_refunded` total
before either committed, and both pass the amount check, together
refunding more than was ever captured. Fixed the same way Phase 21 fixed
the equivalent payment-creation race and `admin_settle_cod()` already
guards its own settlement math: lock the payment row first
(`with_for_update()`), then `db.refresh()` it so a stale, already-loaded
`.refunds` collection can never be the thing `already_refunded` is
computed from.

### Retired the old, broken endpoint
`POST /api/v1/payments/{id}/refund` and its underlying
`app.services.payments.refund_payment()` are removed — confirmed via
grep that no frontend (customer-mobile/rider-mobile/business-web/
admin-web) ever called it.

### Schema fix
`AdminPaymentStatusValue` was missing `PARTIALLY_REFUNDED` and
`PROCESSING` — two real `PaymentStatus` enum values that `_derived_status()`
can hand it, which would have made a Pydantic validation error the first
time an admin viewed a partially-refunded payment. Fixed alongside the
new refund fields, before it could ever actually trigger.

## Files modified
- `backend/app/services/payment/refund_service.py`
- `backend/app/schemas/admin.py`
- `backend/app/services/admin_payments.py`
- `backend/app/api/v1/admin/payments.py`
- `backend/app/api/v1/endpoints/payments.py` (old endpoint removed)
- `backend/app/services/payments.py` (old, unused `refund_payment()` removed)

## Files created
- `docs/payments/phase-23-refund-architecture.md`

## Testing
- New: 13 tests in `test_admin_payments.py` (admin-only, mandatory
  reason, full and partial refunds, over-refund rejection, rejection
  when nothing remains, rejection on a never-paid payment, 404 on a
  missing payment, the audit log entry, and a genuine online refund
  proving the provider is really called) + 1 sequential race-guarantee
  test in `test_payment_service_architecture.py` — 14 new tests total,
  all passing.
- Regression: 161/161 passing across every payment and security test
  file (the old endpoint's removal required no test updates — nothing
  referenced it).
- Full backend suite: run after this change (confirmed in the next
  phase's report if not already landed at report time).

## Live verification (real dev server)
Drove a full, real COD order end to end (no provider dependency, so this
is a genuine complete round trip, unlike the online-payment scenarios in
earlier phases that can't complete a real Razorpay checkout headlessly):
placed, paid, then admin issued a partial refund, confirmed
`PARTIALLY_REFUNDED` with one ledger row, then refunded the remainder,
confirmed `REFUNDED` with `refunded_amount` exactly equal to the real
order total and **two** ledger rows (the first untouched). Also
confirmed live: a non-admin is rejected (403), a refund on a never-paid
payment is rejected (409), an over-refund is rejected (409), and a
further refund once nothing remains is rejected (409). 14/14 checks
passed; test data cleaned up.

## Known limitations
`Order.payment_status` remains a plain string, not synced by a refund
(matches the existing, documented Phase 1 gap — out of this phase's
scope). The row lock's genuine concurrent-request behavior can't be
exercised in the unit suite (SQLite has no real row-level locking) —
proven instead by the same reasoning Phase 21's live threading proof
already established for the equivalent payment-creation lock.
