# Phase 7 — COD Payment Architecture

## Scope
Verify: `Customer -> Checkout -> Order created -> Payment method = COD ->
Payment status = PENDING`. The payment must not become PAID merely
because the order was created.

## Finding
Already fully built and correct across earlier work (Phases 2, 6, and
pre-existing Phase 14/16/20/24/27 infrastructure) — this phase was
verification-only, no code changes.

- `Payment.payment_status` defaults to `PENDING` at the model level
  (`app/models/payment.py`).
- `Order.payment_status`/`is_paid` default to `"pending"`/`False`
  (`app/models/order.py`).
- `create_order()` never touches `Payment` at all; `is_paid=False`
  explicitly.
- `PaymentService.create_payment_for_order`'s COD branch sets no status
  override, so it lands on the `PENDING` default.
- Exactly three code paths in the entire backend can ever mark a COD
  payment PAID, all legitimate: `_settle_cod_payment_on_delivery()`
  (fired only from a rider-driven `DELIVERED` transition — no customer or
  admin path reaches `DELIVERED`), the rider's explicit
  `collect_cod_payment()`, and `verify_payment()` (razorpay-only, 400s
  against a COD payment).

## Testing
Existing coverage re-run fresh: `test_cod_flow.py` (5),
`test_cod_end_to_end.py` (3), `test_customer_payments.py` (8),
`test_checkout_payment_decision.py` (9) — 25/25 passing, including tests
directly asserting this phase's claim (`test_order_starts_as_cod_pending`,
`test_payment_stays_pending_before_delivery`,
`test_customer_cannot_mark_cod_payment_paid_via_online_verification`).

## Live verification
Placed a real COD order against the real dev server:
`order.payment_status == "pending"`, `is_paid == False` immediately on
creation; the resulting `Payment` record is `status == "pending"`,
`method == "cod"`.
