# Phase 19 — Payment Failure Handling

## Scope
Support a clear customer-facing state for: payment failed, payment
cancelled, payment expired, payment pending, network timeout, provider
unavailable, invalid signature, amount mismatch, duplicate payment.
Example: "Payment Failed [Retry Payment]". Never automatically create a
second order when payment fails; the same eligible order should be
retryable where business rules permit.

## How each of the nine scenarios is actually represented

Most of these already had real backend representation from earlier
phases; this phase's job was making sure each one reaches the customer as
a clear, specific state, and that a real UI gap (no payment section at
all for online orders) didn't leave several of them invisible.

| Scenario | Backend representation | Customer-facing state |
|---|---|---|
| Payment failed | `Payment.payment_status = FAILED` (Phase 14) | "Payment Failed" + the specific `failure_reason` + **Retry Payment** |
| Invalid signature | `failure_code = SIGNATURE_MISMATCH` (Phase 14) | Same — `failure_reason` is the human-readable message |
| Amount mismatch | `failure_code = AMOUNT_MISMATCH` (Phase 15) | Same |
| Duplicate payment | `409` from `/verify` and `/retry` on an already-PAID payment (Phase 5) | The retry button is never even shown once `status === "paid"` — prevented at the UI layer, not just rejected at the API |
| Payment pending | `Payment.payment_status = PENDING` (default) | "Payment pending" + **Complete Payment** (not "Retry" — nothing has failed yet) |
| Payment cancelled | No backend state of its own — Razorpay never calls `/verify` at all for a checkout the customer simply closed without attempting payment; the `Payment` row stays `PENDING` | Same "Payment pending" / Complete Payment state; the immediate in-checkout alert uses Razorpay's own `description` for the specific cancellation message |
| Payment expired | Same as cancelled — Razorpay Standard Checkout has no server-side order expiry to track for this flow; a stale open checkout surfaces as the SDK's own rejection if it ever occurs | Same "Payment pending" / Complete Payment state — retry always reopens the same, still-valid provider order regardless of how much time has passed |
| Network timeout | `httpx.TimeoutException` is an `httpx.HTTPError` subtype, already caught and raised as `ProviderRequestError` → `502` (Phase 4/5) | Same "Payment not completed" path as any other provider-side rejection; Razorpay SDK-side timeouts surface via its own `description` |
| Provider unavailable | `ProviderNotConfiguredError` → `503` (Phase 4/5) | See the real gap fixed below |

## A real gap found and fixed
`orders/[id].tsx` — the screen a customer actually lands on after
checkout, and the one they'd return to later to retry — rendered a
payment section **only for COD** (`order.payment_method === "cod"`).
An online order's payment state was completely invisible there: no
"Payment Failed," no "Retry Payment," nothing. Separately,
`checkout.tsx`'s error handling wrapped the *entire* `placeOrder()` call
in one try/catch, so if `recordOrderPayment()` itself failed (e.g. a
genuinely `503 provider unavailable`) *after* the order had already been
successfully created, the customer saw "Order failed" — a message that
could plausibly lead them to place a second order, believing the first
never went through, which is exactly what this phase says never to let
happen.

## What was built
- **Backend**: `PaymentResponse` (and `_to_payment_response`) gained
  `failure_reason`, previously exposed only on the older, unused
  `PaymentRead` schema — the real `/api/v1/payments/*` responses never
  carried it before this phase.
- **`features/payments/razorpay-flow.ts`** (new) — the open-Razorpay-
  then-verify-then-refetch flow (Phase 13's steps 3-6), extracted out of
  `checkout.tsx` into a shared module so the order detail screen's retry
  button reuses the exact same, already-proven logic rather than a second
  copy of it.
- **`checkout.tsx`** — `recordOrderPayment()` now has its own try/catch:
  a failure there tells the customer plainly that their order *was*
  placed and payment can be retried from the order, instead of "Order
  failed." The failed/unknown-outcome alerts now include the specific
  `failure_reason` when one is available, and point the customer at the
  order (where they actually *can* retry) rather than dead-ending.
- **`orders/[id].tsx`** — a real payment section for non-COD orders,
  covering four states: no payment record yet ("Payment not started" +
  **Complete Payment**, which safely calls `record_order_payment()`
  again — idempotent, so it either creates the missing record or returns
  the existing one, never a duplicate), pending ("Payment pending" +
  **Complete Payment**), failed ("Payment Failed" + the specific reason +
  **Retry Payment**, which calls `/retry` first to reopen the *same*
  provider order before reopening checkout), and paid ("Paid," no action
  at all). The retry/complete button is hidden entirely once the order
  reaches a terminal status (cancelled/rejected/delivered) or the payment
  is already paid — the same "never show an action that shouldn't be
  taken" principle as the COD card's own existing paid/pending badge.

## Files created
- `customer-mobile/features/payments/razorpay-flow.ts`
- `customer-mobile/app/__tests__/order-detail.payment-retry.test.tsx` (5 tests)

## Files modified
- `backend/app/schemas/payment.py`, `app/api/v1/endpoints/payments.py`
- `backend/tests/test_payment_api.py` (2 new tests)
- `customer-mobile/app/checkout.tsx`
- `customer-mobile/app/orders/[id].tsx`
- `customer-mobile/services/api/paymentsApi.ts` (`failure_reason` field,
  `getPaymentByOrder`, `retryPayment`)

## Testing
- Backend: 2 new tests (`failure_reason` exposed on `GET`, cleared by
  `retry`) — passing. Full backend suite run after this change.
- Frontend: 5 new tests — a failed payment shows the specific reason and
  a Retry button; a pending payment shows Complete Payment, not Retry; no
  payment record shows "Payment not started" and starting one reuses the
  same order (never calls `createOrder` again); retrying a failed payment
  calls `/retry` before reopening checkout and reuses the same provider
  order; an already-paid payment shows no action button at all.
  `npx tsc --noEmit` clean; full frontend suite (20 tests) passing.

## Live verification (real dev server)
Forged a genuine signature-mismatch failure against a real order, then
confirmed: `GET /payments/{id}` returns `status: "failed"` with a
specific, real `failure_reason`; `POST /payments/{id}/retry` resets to
`pending`, clears the reason, and — critically — returns the **exact
same** `provider_order_id` as before, never a new one; and the order/
payment count for that order stayed at exactly one throughout. 10/10
checks passed. Live test data cleaned up.

## Known limitations
Unchanged from prior phases — the unguarded legacy `/payments/{id}/refund`
endpoint and `Order.payment_status` being a plain string remain open. Not
run on an actual device/emulator — TypeScript + test coverage is the bar,
consistent with this project's established precedent for frontend-only
work without a device.
