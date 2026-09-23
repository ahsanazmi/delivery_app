# Phase 15 — Payment Amount Validation

## Scope
When verifying a payment, check: internal payment amount, Razorpay order
amount, Razorpay payment amount, currency, order ID, payment state — all
must be consistent. If an amount mismatch occurs, never mark the payment
PAID; create a clear error and audit/log record.

## What was found
Phase 14 had already added order-id and payment-amount checks, but three
of this phase's six required checks were still missing entirely:

- **Currency** was silently dropped — `ProviderPayment` had no `currency`
  field at all; `RazorpayProvider.fetch_payment()` never even parsed it
  out of Razorpay's response.
- **Payment state** was never inspected — `fetch_payment()`'s own
  `status` field (Razorpay distinguishes `authorized` from `captured`;
  only `captured` means money has actually settled) was fetched but never
  checked. A payment merely *authorized*, not yet captured, would have
  passed every existing check.
- **Razorpay order amount** was never independently re-confirmed at
  verification time — only checked once, implicitly, when the order was
  first created. There was no `fetch_order()` at all.

## What was built
- `PaymentProvider`/`RazorpayProvider` gained `fetch_order()` (real
  `GET /v1/orders/{id}`), mirroring `fetch_payment()` for the order side.
- `ProviderPayment` gained a `currency` field, now populated from
  Razorpay's real response.
- `PaymentService.verify_payment()` now runs, after the order-id and
  signature checks from Phase 14: fetch the payment **and** the order
  from Razorpay, then check — in order — that the fetched payment's own
  reported `order_id` matches (catching a case the client-submitted
  order-id check alone wouldn't), that the payment's `status ==
  "captured"`, that both the payment's and the order's amounts equal
  `payment.amount`, and that both currencies equal `payment.currency`.
  Any single disagreement rejects the whole verification — never a
  partial success — with a specific `failure_code`
  (`PAYMENT_NOT_CAPTURED`, `AMOUNT_MISMATCH`, `CURRENCY_MISMATCH`, or a
  reinforced `ORDER_MISMATCH`).
- Added a `logger.warning(...)` call for every rejection — a clear,
  specific log record distinct from the `PaymentAttempt` audit row and
  the existing admin/customer notifications, per this phase's explicit
  "audit/log record" requirement. Never logs the signature (on the
  never-log list per the established Phase 26 rule).

## Files modified
- `backend/app/services/payment/provider.py`
- `backend/app/services/payment/razorpay_provider.py`
- `backend/app/services/payment/payment_service.py`
- `backend/tests/test_payment_service_architecture.py` (`FakeProvider`
  extended with `fetch_order` and per-field overrides for currency/state/
  order-id, matching the interface's new shape)
- `backend/tests/test_payment_signature_verification.py`
  (`RealisticFakeProvider` extended the same way)

## Testing
- New: 5 additional tests in `test_payment_signature_verification.py`
  (10 total in that file now) covering payment-vs-order amount
  disagreement, currency mismatch, not-yet-captured state, the provider's
  own order-id cross-check, and an explicit proof that a mismatch both
  leaves `payment.payment_status != PAID` and produces a `WARNING`-level
  log record.
- Regression: `test_payment_service_architecture.py` (41, including a new
  `fetch_order` mock test) and `test_payment_api.py` (19) — all passing.
- Full backend suite: run after this change (see next phase's report for
  confirmation if not already landed at report time).

## Live verification (real dev server + real Razorpay test API)
`fetch_order()` proven against the real API for the first time — a real
order's amount/currency read back correctly. The full verify chain
(order-id → signature → payment fetch+state → order fetch) run end to end
against the real API for an order that was never actually paid through
Razorpay's checkout: still correctly rejected (400), payment status never
flipped to paid. 5/5 checks passed. Live test data cleaned up.

## Known limitations
Unchanged from prior phases — the unguarded legacy `/payments/{id}/refund`
endpoint and `Order.payment_status` being a plain string remain open.
