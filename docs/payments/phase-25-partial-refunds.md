# Phase 25 — Partial Refunds

## Scope
Support partial refunds if the business model requires them. Example:
Order = ₹500, Refund = ₹150, Remaining captured amount = ₹350. Track
all refunds separately. Never overwrite the original payment amount.

## What was found
Partial refunds were already fully built — `refund_service.create_refund()`
(Refund Architecture, Phase 23) already accepts any amount up to what
remains refundable, `Refund` (Phase 2) is already an append-only ledger
(one row per refund event), and `Payment.amount` is never assigned
anywhere in the codebase outside its original capture (confirmed by a
whole-codebase grep — the one hit, `rider_deliveries.py`'s
`collect_cod_payment()`, sets it once, at first capture, never again).
On paper, and against every existing unit test (SQLite, `Session(engine)`
default settings), this phase's own requirements were already fully
satisfied.

## A real, previously-invisible production bug, found via live verification
Live-testing this phase's own named example against the real dev server
and real Postgres — not just the test suite — surfaced a genuine bug:
issuing a real ₹150 refund against a real ₹500 `Payment` created the
`Refund` row correctly (amount, status, reason all correct), but
`Payment.payment_status` **never advanced** from `PAID` to
`PARTIALLY_REFUNDED`. `refunded_amount`/`refundable_amount` (both
derived independently, by iterating `payment.refunds`) were correct;
only the `payment_status` column itself silently stayed wrong.

**Root cause**: `app/db/session.py`'s `SessionLocal` — the session every
real request in this application actually uses — is configured with
`autoflush=False`. Inside `create_refund()`, `refund.status` is
reassigned from `PENDING` to `COMPLETED` *after* an earlier
`db.flush()` had already persisted it as `PENDING`. The very next step,
`recompute_payment_refund_status()`, runs a fresh `SELECT SUM(...)`
query (`_sum_refunds()`) to decide the payment's new status. With
`autoflush=True` (SQLAlchemy's own default), that query would
automatically flush the pending `refund.status = COMPLETED` change
first, so the SUM would see it. With `autoflush=False`, it does not —
the SUM query saw only the stale, already-flushed `PENDING` value, so
`_sum_refunds()` found `settled = 0`, and `recompute_payment_refund_status()`
returned immediately without ever touching `payment.payment_status`.

**Why every test passed anyway**: every test file in this entire
backend suite constructs its own database session via a bare
`Session(engine)` (SQLite, in `conftest.py` and every test file's own
fixture) — SQLAlchemy's own default, `autoflush=True`. That default
happened to auto-flush the pending reassignment before the SUM query
ran, completely masking the bug in every single test, including all of
Phase 23/24's own refund tests. Only a session configured exactly like
the real application's own `SessionLocal` — which nothing in the test
suite ever uses — could have caught this. It took driving the exact
same code path against the real running server, with the real session
configuration, to surface it.

## What was built
One line: an explicit `db.flush()` in `refund_service.create_refund()`,
immediately after `refund.status` is set to its final value and
immediately before `recompute_payment_refund_status()` is called —
making the correctness of this specific status transition no longer
depend on the session's own `autoflush` setting at all, rather than
relying on an implicit default that the real application doesn't
actually use.

## Files modified
- `backend/app/services/payment/refund_service.py`

## Files created
- `backend/tests/test_partial_refunds.py`
- `docs/payments/phase-25-partial-refunds.md`

## Testing
- New: 7 tests in `test_partial_refunds.py` — the phase's own exact
  named example (Order 500 / Refund 150 / Remaining 350) both at the
  service layer and through the real admin HTTP endpoint; multiple
  partial refunds each tracked as their own separate `Refund` row (never
  merged or overwritten); a refund can fully exhaust the remaining
  captured amount across several partial refunds; `Payment.amount`
  proven unchanged through any number of partial refunds, even a fully
  refunded one; an over-refund attempt correctly rejected and leaves no
  trace; each partial refund gets its own admin audit-log entry with its
  own accurate before/after state. All 7 pass.
- Full backend suite: **1226 passed, 10 skipped, 0 failed** (baseline
  1219 + 7 new) — no regressions.

## Live verification (real dev server) — where the real bug was actually found
Seeded a real ₹500 COD order/payment directly in Postgres, then issued a
real ₹150 refund through the real `POST /admin/payments/{id}/refund`
endpoint:
- **Before the fix**: response showed `refunded_amount: "150.00"`,
  `refundable_amount: "350.00"`, one real `Refund` row — but
  `status: "PAID"` (should have been `PARTIALLY_REFUNDED`). Confirmed
  directly via `psql`: `payments.payment_status = 'paid'`,
  `payments.updated_at` unchanged since the payment's own original
  creation — proof the row was never actually re-written.
- Reproduced in an isolated script calling `PaymentService().refund()`
  directly against the real `SessionLocal`/Postgres (bypassing HTTP
  entirely) — same result, confirming the bug lived in the service
  layer, not the endpoint or serialization.
- **After the fix**: same reproduction script → `payment.payment_status`
  correctly `PARTIALLY_REFUNDED`, confirmed both within the same session
  and from a completely fresh session/connection (ruling out any
  session-local caching artifact).

All live test/debug data cleaned up afterward (`psql`, FK-dependency
order, verified zero rows remaining).

## Known limitations / recommendation
The root cause — `SessionLocal`'s `autoflush=False` silently hiding a
mutate-then-aggregate-query bug that every test's own session
configuration masks — is a systemic risk, not unique to refunds. Any
other code path with the same shape (mutate an ORM attribute, then run
a fresh SELECT/SUM/COUNT query in the same function without an explicit
flush between them) could have the identical class of bug, invisible to
this test suite for the same structural reason. This phase fixed the
one instance its own scope named (refund status recomputation) and
flags the pattern itself as a candidate for a dedicated future audit
phase, rather than unilaterally re-auditing every service module under
this phase's own, narrower "partial refunds" scope.
