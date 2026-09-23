# Phase 3 — Database Migrations

## Scope
Real Alembic migrations for the Phase 2 schema changes: foreign keys,
indexes, unique constraints, check constraints, timestamps — with explicit
care not to create unique constraints that would block legitimate retry
attempts.

## What was built
- **`20260929_40_payment_domain_model.py`** — extends the `payment_status`
  Postgres enum with the three new values, adds `payments.paid_at`, creates
  the `payment_attempts` and `refunds` tables with their FKs/indexes/check
  constraints.
- **`20260930_41_payment_provider_id_uniqueness.py`** — adds four unique
  constraints:
  - `UniqueConstraint("provider", "razorpay_order_id")` and
    `UniqueConstraint("provider", "razorpay_payment_id")` on `Payment` —
    scoped by `(provider, id)` rather than the id alone, so a future second
    online provider's id namespace can't collide with Razorpay's.
  - `UniqueConstraint("provider", "provider_payment_id")` on
    `PaymentAttempt` — deliberately **not** constraining
    `provider_order_id` on this table, since one order can legitimately
    have multiple attempts.
  - `UniqueConstraint("provider_refund_id")` on `Refund`.
- Standard SQL (Postgres and SQLite both) treats `NULL` as distinct from
  every other `NULL` in a unique constraint, so none of this ever blocks
  two COD rows or two not-yet-verified Razorpay rows — it only ever blocks
  a real provider id being reused (replay protection).

## Testing
`tests/test_payment_domain_model.py` extended with: a NULL-safe COD
collision test, a replay-protection test (same id can't be claimed twice),
a legitimate-retry-sharing-provider-order-id test, and duplicate
`provider_payment_id`/`provider_refund_id` rejection tests.

## Verification
Both migrations applied to the live dev Postgres database and round-trip
tested: `alembic downgrade` → verified the new tables/constraints were
gone → `alembic upgrade head` → back to a clean head.

## Result
Schema-only phase — no service or endpoint code changed.
