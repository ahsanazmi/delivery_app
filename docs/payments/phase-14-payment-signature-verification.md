# Phase 14 — Payment Signature Verification

## Scope
Implement server-side verification of Razorpay payment signatures per
Razorpay's own API requirements: verify signature → validate expected
order → validate expected amount → update payment. Never trust a
payment_id alone, a frontend success callback alone, or a client-provided
status. A successful UI callback is never sufficient to mark an order
paid.

## What was found (a real gap, not a rebuild)
`PaymentService.verify_payment()` (built in Phase 4/5) already did the
signature check, but skipped the other two steps the phase explicitly
names:

- **No "validate expected order" check.** The method accepted whatever
  `provider_order_id` the client sent, verified the HMAC for that exact
  pair, and — if valid — **unconditionally overwrote**
  `payment.razorpay_order_id` with it. A genuinely-valid Razorpay
  signature only proves Razorpay signed *some* order/payment pair, not
  that it's *this* payment's pair. A customer who legitimately completed
  one cheap payment could replay that real, correctly-signed triple
  against a different, more expensive payment they also owned. This was
  only accidentally not catastrophic because of an unrelated Phase 3
  database constraint (`uq_payments_provider_order_id`) — and even that
  "protection" surfaced as an **unhandled `IntegrityError` crashing the
  request with a 500**, not a clean rejection.
- **No "validate expected amount" check at all.** Nothing independently
  confirmed with Razorpay what amount was actually captured; the amount
  was only ever implicitly trusted via the order-id link made at
  creation time — which, as above, wasn't itself being validated.

## What was built
`PaymentService.verify_payment()` now runs three independent checks, in
order, before a payment can ever be marked `PAID`:

1. **Validate expected order** — `provider_order_id` must equal
   `payment.razorpay_order_id`, set once at payment-creation time and
   never reassigned here. A mismatch fails immediately with
   `ORDER_MISMATCH`, before the signature is even checked.
2. **Verify signature** — the existing HMAC check, unchanged.
3. **Validate expected amount** — a real call to
   `RazorpayProvider.fetch_payment()`, independently confirming the
   amount Razorpay actually captured equals `payment.amount`. A mismatch
   fails with `AMOUNT_MISMATCH`; an unreachable provider fails with
   `PROVIDER_UNREACHABLE` (never fabricates success when the provider
   can't be asked). This is real defense in depth — it's what would have
   caught the missing order-id check above even without that fix.

## A second bug found while fixing the first
Recording the rejected verification as a `PaymentAttempt` row can itself
collide with `uq_payment_attempts_provider_payment_id` (Phase 3) — the
exact same replayed `provider_payment_id` may already be legitimately
recorded against a *different* payment's successful attempt. This crashed
with an unhandled `IntegrityError` too. Fixed by catching it around the
attempt insert: on collision, roll back just that insert and still
resolve to a clean rejection (`PROVIDER_ID_ALREADY_USED`) — the audit
row is secondary to the security guarantee holding.

## Files modified
- `backend/app/services/payment/payment_service.py`
- `backend/tests/test_payment_service_architecture.py` (`FakeProvider.fetch_payment`
  updated to echo the order's own amount by default, with an override for
  deliberately simulating a mismatch — it previously hardcoded `0.00`,
  which would have failed every real call after this phase's amount check)

## Files created
- `backend/tests/test_payment_signature_verification.py` (5 tests)

## Testing
- New: 5/5 passing, including the exact replay attack this phase's audit
  found (`test_validates_expected_order_rejects_a_genuinely_valid_signature_for_a_different_payment`)
  proving it now resolves to a clean rejection instead of a crash.
- Regression: `test_payment_service_architecture.py` (39) — all passing.
- Full backend suite re-run after this change (in progress at report
  time; will be confirmed in the next phase's inspection if not already
  landed).

## Live verification (real dev server + real Razorpay test API)
Using genuinely-computed HMAC signatures (the real key_secret) against
two real Razorpay orders: a genuinely-valid signature for order X applied
to order Y's payment was rejected (400) before ever reaching
`fetch_payment`; a correctly order-matched, correctly-signed pair for a
real order that was never actually paid through Razorpay's checkout was
still rejected once `fetch_payment` found nothing captured — proving the
amount-confirmation step is a real network call, not a rubber stamp, and
that nothing is ever fabricated as paid without genuine provider
confirmation. 4/4 checks passed. Live test data cleaned up.

## Known limitations
Unchanged from prior phases — the unguarded legacy `/payments/{id}/refund`
endpoint and `Order.payment_status` being a plain string remain open.
