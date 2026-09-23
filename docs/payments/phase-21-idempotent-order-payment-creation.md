# Phase 21 — Idempotent Order Payment Creation

## Scope
Prevent a double tap, a network retry, an app restart, or a repeated
checkout request from creating duplicate payment orders. Use an
idempotency mechanism where appropriate: for order X, payment
initialization checks for an existing active payment and returns it
rather than creating a new one.

## What was found
`PaymentService.create_payment_for_order()` already implemented exactly
this conceptual flow since Phase 6 — "existing payment? return it; else
create one" — with `uq_payments_order_id` as the database-level
guarantee and an `IntegrityError`-catch-and-recover fallback for a race
on the final commit. `Order.id` is itself the natural idempotency key
here (one order can only ever have one payment, enforced at the schema
level), so no separate client-supplied idempotency-key header mechanism
was needed — the existing design already used the right key.

Two real gaps remained, both only reachable through concurrency (never
exercised by the sequential tests that existed before this phase):

1. **No lock before calling the provider.** Two genuinely overlapping
   requests for the same order could both pass the "does a payment exist
   yet?" check before either committed — for an *online* payment, both
   would then go on to call `provider.create_order()`, opening two real,
   separate Razorpay orders (one orphaned) even though only one `Payment`
   row would ultimately survive. Wasteful, and exactly what this phase's
   own wording ("prevent... duplicate **payment orders**") names.
2. **An uncaught `IntegrityError`.** The online branch's `db.flush()`
   (needed right after `db.add(payment)` to get `payment.id` for the
   `PaymentAttempt` foreign key, before the provider is ever called) can
   itself raise `IntegrityError` on a `uq_payments_order_id` collision —
   and this was **not** wrapped in the existing recovery's `try/except`,
   which only covered the later `db.commit()`. A race that got past
   whatever serializes it would have surfaced as an unhandled `500`,
   never reaching the recovery path at all. Found directly by writing
   this phase's own race-simulation test, using the same
   monkeypatch-the-existence-check technique already established in
   Phase 6/14/18.

## What was built
- `create_payment_for_order()` now locks the order row first
  (`db.scalar(select(Order).where(Order.id == order.id).with_for_update())`
  — the same pattern `admin_settle_cod()` already uses for the same
  reason): a second, genuinely concurrent call for the same order blocks
  here until the first either commits or rolls back, so the provider is
  only ever actually called by the one request that's going to win.
- The online branch's `db.flush()` is now inside its own
  `try/except IntegrityError`, with the same rollback-and-return-existing
  recovery the final commit already had — closing the uncaught-500 gap
  even for a race that somehow gets past the lock (a database that
  doesn't honor `with_for_update`, or any other unforeseen path).

## Files modified
- `backend/app/services/payment/payment_service.py`

## Files created
- `backend/tests/test_idempotent_payment_creation.py` (3 tests)

## Testing
- New: repeated *sequential* calls (the practical shape of a double tap,
  network retry, app restart, or repeated checkout request) never call
  the provider more than once and always return the same provider order
  id; a simulated race that gets past the lock still resolves to exactly
  one `Payment` row via the newly-fixed recovery path. Genuine row-lock
  semantics can't be exercised in SQLite (no real row-level locking), so
  that guarantee is proven live instead (below), not in the unit suite.
- Regression: 107/107 passing across every payment test file.
- Full backend suite: run after this change (confirmed in the next
  phase's report if not already landed at report time).

## Live verification (real dev server + real Postgres, genuine concurrency)
Fired 8 truly concurrent HTTP requests (real threads, a `threading.Barrier`
lining them up to fire as close to simultaneously as possible) at
`POST /customer/orders/{id}/payment` for the same real order. All 8
returned `200` with the **exact same** `payment_id` and the **exact
same** real Razorpay `provider_order_id`. Queried Postgres directly
afterward: exactly one `Payment` row and exactly one `PaymentAttempt`
row exist — proving `provider.create_order()` was genuinely invoked only
once across all 8 concurrent requests, not just that the database
constraint cleaned up duplicates after the fact. 5/5 checks passed; live
test data cleaned up.

## Known limitations
Unchanged from prior phases — the unguarded legacy `/payments/{id}/refund`
endpoint and `Order.payment_status` being a plain string remain open.
