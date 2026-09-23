# Phase 35 — Duplicate Payment Test

## Scope
Test: Customer taps PAY twice. Expected: one logical order, no
duplicate successful payment, no duplicate financial ledger entry.
Also test: webhook arrives twice. Expected: one financial state
transition.

## Method
Most of the underlying guarantees were already built by earlier phases
— Idempotent Order Payment Creation (Phase 21) for payment creation,
Webhook Idempotency (Phase 18) for redelivery — and are proven again
here under this exact vocabulary, in one canonical file
(`test_duplicate_payment.py`). This phase's own genuinely new
contribution is applying "tap PAY twice" to **verification**, not just
creation: `PaymentService.verify_payment()` takes no row lock at all
(unlike `create_payment_for_order()`, which locks the order row
specifically for this class of race) — most of the session's earlier
"real concurrency" proofs (Phase 21) exercised the locked path, never
this one. This phase proves the *unlocked* path is still safe, and
proves it with genuinely concurrent threads against real Postgres, not
just sequential requests against SQLite.

## What was verified

### "Customer taps PAY twice" — payment creation
`POST /customer/orders/{id}/payment`, tapped twice back to back:
one logical order (obviously — nothing creates a second `Order`), and
exactly one `Payment` row — the second tap finds the first tap's row
already there (via `uq_payments_order_id`) and returns it unchanged,
never opening a second real Razorpay order at the provider either.
Already Phase 21's own guarantee; reconfirmed here under this phase's
own wording.

### "Customer taps PAY twice" — payment verification (the new case)
Two identical `POST /payments/{id}/verify` calls (same
`provider_order_id`/`provider_payment_id`/`signature` — the same real
Razorpay callback data, submitted twice):

- **Sequential** (the common real case — a UI double-tap or a network
  retry where the second request starts only after the first already
  committed): the endpoint's own `_VERIFIABLE_STATUSES` gate excludes
  `PAID`, so the second tap is honestly rejected with `409` before ever
  reaching the service layer again — no duplicate successful payment,
  exactly two `PaymentAttempt` rows total (order-open + the one genuine
  verification), never a third.
- **Genuinely concurrent** (both requests racing, both reading
  `PENDING` before either commits — proven with real threads against
  real Postgres, not SQLite, since SQLite can't exercise real
  transaction isolation): both requests succeed (confirming an
  already-genuinely-successful payment twice is not itself an error —
  no money moves twice, verification is a read-only confirmation, not a
  charge), the payment ends in `PAID` exactly once, and — the specific
  guarantee this race actually threatens — **exactly one
  `PaymentAttempt` row exists for this event**, not two. This is thanks
  to Phase 32's own same-payment collision-recovery fix to
  `uq_payment_attempts_provider_payment_id`'s handling: when two
  concurrent attempts for the *same* payment race to insert a row with
  the *same* `provider_payment_id`, the loser updates the winner's row
  in place rather than either failing or creating a duplicate. Without
  that fix (i.e., before Phase 32), this exact race would have thrown
  the collision-recovery's old code down its "replay against a
  different payment" branch and incorrectly rejected the second,
  entirely legitimate racing request.

### Webhook arrives twice
Two deliveries of the identical `event_id` → the event-id gate
(Phase 18) recognizes the redelivery before any parsing/dispatch at
all, returning the original stored event unchanged: one financial
state transition (`payment_status` moves `PENDING` → `PAID` exactly
once, `paid_at` set once and never re-stamped by the redelivery — the
concrete, observable proof that the second delivery genuinely did
nothing), one `WebhookEvent` row, `Order.is_paid` correctly `True`
either way.

No new backend code was needed — this phase's own scope was entirely
verification, and every property it names held, including under
genuine concurrency for the one previously-unexercised path
(`verify_payment()`'s own lock-free design).

## Files created
- `backend/tests/test_duplicate_payment.py`
- `docs/payments/phase-35-duplicate-payment-test.md`

## Testing
- New: 3 tests — payment-creation double-tap (one order, one payment,
  provider called once), sequential verification double-tap (second tap
  honestly `409`-rejected, exactly two `PaymentAttempt` rows total), and
  webhook-arrives-twice (one `WebhookEvent`, one state transition,
  `paid_at` never re-stamped). All 3 passed on the first attempt.
- Full backend suite: **1231 passed, 10 skipped, 0 failed** (baseline
  1228 + 3 new) — no regressions.

## Live verification (real dev server + genuine concurrency)
The SQLite-based tests above prove the *sequential* double-tap case
completely, but SQLite can't exercise real transaction isolation for
the genuinely-concurrent case. Wrote a standalone script that seeds a
real `Payment` in real Postgres, then fires **two genuinely concurrent
Python threads**, each with its own real database session, both
calling `PaymentService.verify_payment()` with the identical real
callback data at the same moment:

```
RESULTS: ['paid', 'paid']
ERRORS: []
FINAL PAYMENT STATUS: PaymentStatus.PAID
PAYMENT_ATTEMPT COUNT: 1
```

Both racing threads succeeded (correctly — neither move money, both are
honestly confirming the same real event), the payment settled on
exactly one final `PAID` state, and — the property this phase actually
puts to the test — **only one `PaymentAttempt` row exists**, proving
the "no duplicate financial ledger entry" guarantee holds under a real
race condition against a real database, not just in a controlled
sequential test.

All live test data cleaned up afterward (`psql`, FK-dependency order,
verified zero rows remaining).

## Known limitations
The genuine-concurrency proof above uses a `FakeRazorpay` stand-in at
the service layer (real Postgres, real threads, real transaction
isolation — only the provider network call itself is faked), the same
recurring limitation as every online-payment phase since 11: a real
Razorpay checkout can't be driven concurrently, or at all, without a
browser.
