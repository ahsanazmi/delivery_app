# Phase 6 — Checkout Payment Decision

## Scope
Integrate payment selection into checkout. Customer selects COD or online
payment; the backend validates restaurant/product/amount/address/payment
method server-side and never trusts a client-supplied total, discount,
tax, or delivery fee.

## What was built
- `CustomerOrderCreate.payment_method` widened from `Literal["cod"]` to
  `Literal["cod", "razorpay"]` (`app/schemas/order.py`).
- `create_order()` gains one new gate: refuses to open a `"razorpay"`
  order if `RAZORPAY_KEY_ID`/`SECRET` aren't configured, raising
  `ValueError` → 422 (`app/services/orders.py`), checked before
  `validate_checkout()`.
- `record_order_payment()` (behind the real, already-used
  `POST /customer/orders/{id}/payment` endpoint) rewritten to delegate to
  `PaymentService.create_payment_for_order` instead of its old hand-rolled
  COD-only insert — this is the change that actually makes online payment
  selection work end-to-end.

## Verified, not rebuilt
Confirmed the existing `checkout.py::_checkout_issues()`/
`validate_checkout()`/`calculate_cart_totals()` already fully implement
restaurant availability (active/approval/hours), product availability
(`sync_cart_with_catalog`), minimum order amount, and address ownership/
serviceability — and that `CustomerOrderCreate` never accepted
`client_total`/`client_discount`/`client_tax`/`client_delivery_fee` in the
first place, so there was nothing to stop trusting.

## Bug found and fixed in this phase
Delegating to `PaymentService.create_payment_for_order` dropped the
atomic race-recovery the old `record_order_payment` had (catch
`IntegrityError` on `uq_payments_order_id`, roll back, return the
winner's row) — two near-simultaneous calls would have 500'd. Fixed at
the source: `PaymentService.create_payment_for_order` itself now catches
`IntegrityError` and recovers, so both call sites
(`/api/v1/payments/create` and `record_order_payment`) get the guarantee.

## Testing
`tests/test_checkout_payment_decision.py` (9 tests, new) — schema
validation, the razorpay-availability gate on/off, COD unaffected,
server-authoritative totals, real online-payment creation via a mocked
Razorpay transport, COD flow unchanged.

## Live verification
Placed a real order with `payment_method="razorpay"` against the real dev
server; the real `/customer/orders/{id}/payment` call returned a genuine
`order_...` Razorpay order id. COD flow unaffected. A tampered request
body with extraneous `client_total`/`client_discount`/etc. fields was
silently ignored — the server computed its own total regardless.
12/12 live checks passed.
