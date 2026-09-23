# Phase 12 — Razorpay Order Creation

## Scope
When a customer chooses online payment:
`Customer -> Checkout -> Backend -> Validate order/payment -> Create
Razorpay order -> Store provider order ID -> Return checkout
information`. The Razorpay order amount must be generated from the
backend's authoritative order amount — never accepted as an arbitrary
amount from the mobile application.

## Finding
The core flow was already built in Phase 6 (checkout selection) and
Phase 4/5 (`PaymentService`/`RazorpayProvider`):
`record_order_payment()` → `PaymentService.create_payment_for_order()` →
`RazorpayProvider.create_order(amount=order.total, ...)` →
`payment.razorpay_order_id` stored → `CustomerPaymentRead` returned as
checkout information. `order.total` is fixed once, server-side, at
order-creation time (`create_order()`) and never re-derived from client
input anywhere in this path.

## Gap found and fixed
The returned "checkout information" was missing the one thing a mobile
Razorpay Checkout SDK actually needs to open the payment sheet: the
public `key_id`. (`key_id` is Razorpay's own public identifier — safe to
return to the client, unlike `key_secret`, which no response in this
codebase has ever included or now includes.) Added `razorpay_key_id` to:

- `CustomerPaymentRead` (`app/schemas/payment.py`) — populated in
  `_to_customer_payment()` (`app/services/payments.py`) from
  `settings.RAZORPAY_KEY_ID`, `None` for COD or when unconfigured.
- `PaymentResponse` (`app/schemas/payment.py`) — same, populated in
  `_to_payment_response()` (`app/api/v1/endpoints/payments.py`).

## Files modified
- `app/schemas/payment.py`
- `app/services/payments.py`
- `app/api/v1/endpoints/payments.py`

## Files created
- `tests/test_razorpay_order_creation.py` (4 tests)

## Testing
New: 4/4 passing — server-authoritative amount reaches Razorpay in
paise exactly, provider order id is stored on the `Payment` row, checkout
information includes `razorpay_key_id` but never the secret, COD checkout
information has `razorpay_key_id: null`.

Regression: `test_customer_payments.py`, `test_payment_api.py`,
`test_checkout_payment_decision.py` — 36/36 passing (additive field,
default `None`, no existing response shape broken).

## Live verification
Against the real dev server + real Razorpay test API: placed an order
with a tampered body (`amount`, `total`, `client_total` all spoofed to
`"1.00"`) — server ignored all of it and computed its own total; the
resulting payment's `transaction_reference` is a genuine `order_...` id;
`razorpay_key_id` in the response matches the real public key, and the
real key secret appears nowhere in the response; **cross-checked
Razorpay's own stored order record directly** (`GET
https://api.razorpay.com/v1/orders/{id}`) and confirmed the amount
Razorpay itself recorded matches the server's authoritative total exactly,
in paise. 9/9 checks passed.

## Known limitations
Unchanged from prior phases — the unguarded legacy `/payments/{id}/refund`
endpoint and `Order.payment_status` being a plain string remain open,
pre-existing gaps outside this phase's scope. The mobile app itself
(`customer-mobile/`) doesn't yet call the Razorpay Checkout SDK or offer
online payment as a UI choice (`checkout.tsx` still hardcodes
`payment_method: "cod"`) — that's a separate, not-yet-requested phase.
