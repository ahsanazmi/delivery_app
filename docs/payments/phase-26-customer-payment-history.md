# Phase 26 — Customer Payment History

## Scope
Customer should be able to view: Payment, Order, Amount, Payment method,
Status, Date. Customer must only see their own payments. Add/refine
`customer-mobile/` payment history, only if not already available.

## What was found
No payment history list existed anywhere in this codebase. The customer
payments API (`app/api/v1/customer/payments.py`) only supported
`GET /payment-methods` and `POST /orders/{order_id}/payment` (create/fetch
a single order's own payment); the generic `/api/v1/payments/*` router
only supported per-id/per-order lookups (`GET /{payment_id}`,
`GET /order/{order_id}`), never a list of everything a customer has ever
paid for. `customer-mobile` had no payment-related screen at all — no
route, no API call, no entry point.

## What was built

### Backend
`GET /api/v1/customer/payments` (`app/api/v1/customer/payments.py`),
admin-portal-style pagination (`page`/`limit`, same convention as
`GET /customer/orders`). Delegates to a new
`list_customer_payments(db, user_id, *, offset, limit)`
(`app/services/payments.py`):

- **Own payments only** — the query filters on `Payment.user_id ==
  user_id` directly; a customer can only ever construct a query scoped to
  themselves, never a check applied after the fact.
- **Order** — `_to_customer_payment()` (already used by the existing
  `record_order_payment()`) now also includes `order_number`, the
  order's human-readable reference, not a raw UUID. `payment.order` is
  always present (`order_id` is a NOT-NULL FK with `ON DELETE CASCADE` —
  a `Payment` never outlives its `Order`) and reached via
  `joinedload(Payment.order)` to avoid an N+1 across a full page of
  results.
- **Amount / Payment method / Status / Date** — the existing
  `_to_customer_payment()` shape already carried all four
  (`amount`, `method`, `status`, `created_at`), unchanged.

`CustomerPaymentRead` (the response schema, already used by
`record_order_payment`'s own response) gained the new `order_number:
str` field; both endpoints on this router now return it.

### customer-mobile
- New screen: `app/payments.tsx` — a paginated list (`listPaymentHistory`
  in `services/api/paymentsApi.ts`, mirroring `orders.tsx`'s own
  load-first-page / load-more / pull-to-refresh pattern), each row
  showing the order number, amount, method (Cash on delivery / Paid
  online), status, and date; tapping a row opens that order's existing
  detail screen (`/orders/[id]`, already showing the same payment's full
  detail). Registered in `app/_layout.tsx`.
- Entry point: a new "Payment history" row on the profile screen
  (`app/profile.tsx`), next to Sign out — this app has no shared bottom
  navigation bar, so the profile screen is where every other
  account-level link (edit profile, sign out) already lives.

## Files modified
- `backend/app/services/payments.py`
- `backend/app/schemas/payment.py`
- `backend/app/api/v1/customer/payments.py`
- `backend/tests/test_customer_payments.py`
- `customer-mobile/app/_layout.tsx`
- `customer-mobile/app/profile.tsx`
- `customer-mobile/services/api/paymentsApi.ts`
- `customer-mobile/app/__tests__/profile.protected-route.test.tsx` (its
  `expo-router` mock needed `useRouter` once `profile.tsx` started using
  it for the new navigation link)

## Files created
- `customer-mobile/app/payments.tsx`
- `customer-mobile/app/__tests__/payments.screen.test.tsx`
- `docs/payments/phase-26-customer-payment-history.md`

## Testing
- Backend: 4 new tests in `test_customer_payments.py` (expected fields +
  newest-first ordering; never returns another customer's payments;
  pagination; the real HTTP endpoint scoped to the caller, including an
  unauthenticated 401/403 check). Full backend suite: **1180 passed, 10
  skipped, 0 failed** (baseline 1176 + 4 new).
- Frontend: 5 new tests in `payments.screen.test.tsx` (protected route;
  renders order number/amount/method/status; COD vs. online rendered
  distinctly; empty state; backend error surfaced, not a crash). Full
  `customer-mobile` suite: **25/25 passing** (21 pre-existing + 5 new — 1
  pre-existing test's `expo-router` mock needed updating, not a
  behavioral regression). `npx tsc --noEmit`: clean.

## Live verification (real dev server)
Seeded a real customer, restaurant, product, and a real COD order/payment
directly through the same service layer the app uses (via the existing
address service-area validation, using the one currently-configured
serviceable postal code), then drove the real HTTP endpoint:
- `GET /api/v1/customer/payments` with no token → `401`.
- The owning customer → `200`, exactly one row, with `order_number`,
  `amount`, `method: "cod"`, `status: "pending"`, and timestamps all
  matching the real order/payment just created.
- A second, unrelated customer (freshly registered, no orders) →
  `200`, `[]` — never the first customer's payment.
- A third, brand-new customer with genuinely zero payments → `200`, `[]`
  (the honest empty-state case, not an error).

All test data cleaned up afterward (`psql`, FK-dependency order,
verified zero rows remaining).

## Known limitations
No filtering/search on the history list (by date range, status, or
method) — the phase's own scope only asked for the six listed fields;
filtering wasn't requested and wasn't built. Razorpay online payments
still show `razorpay_key_id` in the raw API response (harmless — it's
Razorpay's own public identifier, already returned by every other
payment response in this codebase) but the mobile list screen doesn't
use it, since there's no checkout action on a history row.
