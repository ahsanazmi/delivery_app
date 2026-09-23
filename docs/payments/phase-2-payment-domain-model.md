# Phase 2 — Payment Domain Model

## Scope
Create or improve the payment domain model: `Payment`, `PaymentAttempt`,
`Refund`. Explicitly excluded `CODCollection` and `Settlement` as separate
models since the existing architecture already covers those roles
(`Payment.collected_by_rider_id` and `RiderSettlement` respectively) —
reused rather than duplicated, per the phase's own instruction to use only
models actually required.

## What was built
- **`PaymentStatus` enum extended** (`app/models/payment.py`): original five
  values (`PENDING`, `PAID`, `FAILED`, `CANCELLED`, `REFUND_PENDING`) kept
  unchanged; three added — `PROCESSING` (a Payment row between "checkout
  opened" and "Razorpay responded"), `PARTIALLY_REFUNDED` (now that a
  `Refund` can represent more than one refund against the same payment),
  `CANCELLED` closing a gap admin-web's own type already had.
- **`Payment.paid_at`** — new nullable timestamp column, distinct from
  `created_at` (set when the row is first opened) and `updated_at` (moves
  on any change, e.g. a failed verification attempt).
- **`PaymentAttempt`** (`app/models/payment_attempt.py`) — one row per
  attempt to pay (create/verify), not one row per Payment: `provider`,
  `provider_order_id`, `provider_payment_id`, `amount`, `status`,
  `failure_code`, `failure_message`.
- **`Refund`** (`app/models/refund.py`) — own `RefundStatus` enum
  (`PENDING`/`PROCESSING`/`COMPLETED`/`FAILED`), `provider_refund_id`,
  `reason`, denormalized `order_id` alongside `payment_id`.
- All monetary fields use `Numeric(10,2)`/`Decimal`, never float, per the
  phase's explicit instruction.

## Testing
`tests/test_payment_domain_model.py` (13 tests): enum coverage, default
values, relationship cascades, non-negative amount constraints.

## Result
Purely additive — nothing in this phase touched any existing endpoint or
service; the new models weren't wired into any request path yet (that
happened in Phase 4/5).
