# Phase 27 — Admin Payment Management

## Scope
Admin should be able to view: Payment ID, Order ID, Customer, Amount,
Payment method, Provider, Payment status, Provider reference, Created
time, Paid time, Refund status. Support filters: Status, Method, Date
range, Order ID, Customer. Do not expose Razorpay secrets.

## A scope conflict, resolved before writing code
The phase command said "Integrate with: `business-web/`". This
codebase's own established architecture puts the Admin Portal in a
separate `admin-web` app — confirmed not just by a standing rule from an
earlier session, but by `admin-web` already having a working, partially
built `src/pages/Payments.tsx` (list, search, method/status/date
filters, pagination) wired to a real backend admin payments API, while
`business-web` is scoped to `RESTAURANT_OWNER` only (its own README says
so). Building admin functionality into `business-web` would have mixed
an ADMIN-only surface into the restaurant-owner app. Confirmed with the
user before writing any code: **target `admin-web`**, not `business-web`.

## What was found
`admin-web/src/pages/Payments.tsx` and `PaymentDetails.tsx` already
existed (from an earlier, separate admin-web phase sequence) and already
covered most of this phase's list fields and three of its five filters.
Three real gaps:

1. **Missing fields** — `paid_at` didn't exist anywhere in the admin
   payment API response at all (list or detail); `provider` didn't exist
   as its own field (only the combined `method`); the list view had no
   refund-status column at all.
2. **A dead field** — `AdminPaymentDetail.refund_status` read
   `Payment.refund_status`, a raw string column no code path in this
   entire codebase has ever written to (confirmed via grep) — always
   `null` in practice. `PaymentDetails.tsx` already had a conditionally
   rendered "Refund status" card for it, which could never actually
   render.
3. **Stale filter options** — `admin-web`'s own `AdminPaymentStatusValue`
   type and `STATUS_OPTIONS` list were missing `PROCESSING` and
   `PARTIALLY_REFUNDED` — two real, already-filterable backend statuses
   added by the Payment System protocol's own Phase 23 — meaning an
   admin could never actually select either one from the Status filter,
   even though payments could genuinely be in those states.

## What was built

### Backend
- `AdminPaymentSummary` (the shape both the list and detail responses
  share) gained three fields: `provider` (the external gateway —
  `"Razorpay"` for an online payment, `null` for COD, since cash has no
  external provider at all — deliberately distinct from `method`, which
  is the customer's own cod/online choice, not the gateway that
  processed it), `paid_at` (from `Payment.paid_at`, distinct from
  `created_at`), and `latest_refund_status` (the most recent real
  `Refund` row's own status — pending/processing/completed/failed — or
  `null` if this payment has never had a refund attempted).
- `latest_refund_status` **replaces** the dead `refund_status` read in
  `get_admin_payment_detail()` — computed fresh from the real,
  append-only `Refund` history every time, the same principle
  `refund_service.py`'s own `recompute_payment_refund_status()` already
  applies to the parent `Payment`'s own status, never a stale/unwritten
  column.
- List view: batched, not per-row — one extra query for the whole page
  (`Refund.payment_id, Refund.status` for every payment id on the page,
  reduced in Python to "most recent per payment") rather than an N+1
  lazy-load of `payment.refunds` per row, the same reasoning
  `list_user_orders`'s own `selectinload` already applies elsewhere.
- Two new, dedicated filters — `order_number` (partial match against
  `Order.order_number`) and `customer` (partial match against
  `Order.customer_name` or `customer_email`) — added **alongside** the
  existing, already-tested `search` param (unchanged; it still covers
  transaction-reference lookups these two don't), not replacing it.
- `AdminPaymentStatusValue` already included `PROCESSING` and
  `PARTIALLY_REFUNDED` since Phase 23 — backend-side filtering by either
  was already correct; verified with a new test.

### admin-web
- `Payments.tsx`: two new filter inputs ("Order ID", "Customer"),
  wired to the new backend params; `STATUS_OPTIONS` and the frontend's
  own `AdminPaymentStatusValue` type extended with `PROCESSING` and
  `PARTIALLY_REFUNDED` (the actual bug fix — these are real payment
  states an admin previously had no way to filter by); table gained
  Provider, Paid, and Refund status columns; the existing "Transaction
  ref" column relabeled "Provider reference" to match this phase's own
  vocabulary (same underlying field, `transaction_reference`).
- `PaymentDetails.tsx`: added Provider and Paid-at stat cards, relabeled
  "Transaction reference" the same way, and fixed the existing (already
  built, previously dead) Refund status card to read the new, real
  `latest_refund_status` field instead of the always-null one.
- `adminApi.ts`: `AdminPaymentSummary`/`AdminPaymentDetail` types and
  `AdminPaymentListParams`/`getAdminPayments()` updated to match.

### Explicitly not built
A refund action (button/form) in `admin-web` — the backend refund
endpoint (`POST /admin/payments/{id}/refund`, Phase 23) has existed for
a while but was never wired into any admin-web UI at all. This phase's
own scope is view fields and filters, not actions; adding a refund
button would be scope creep beyond what was asked. Left as a known,
still-open gap below.

## Files modified
- `backend/app/schemas/admin.py`
- `backend/app/services/admin_payments.py`
- `backend/app/api/v1/admin/payments.py`
- `backend/tests/test_admin_payments.py`
- `admin-web/src/services/api/adminApi.ts`
- `admin-web/src/services/api/adminApi.test.ts`
- `admin-web/src/pages/Payments.tsx`
- `admin-web/src/pages/PaymentDetails.tsx`

## Files created
- `docs/payments/phase-27-admin-payment-management.md`

## Testing
- Backend: 4 new tests in `test_admin_payments.py` (list includes
  provider/paid_at/latest_refund_status; list and detail both reflect
  the real latest refund status, not the dead column; the new
  order_number/customer filters; PROCESSING/PARTIALLY_REFUNDED are
  filterable). `test_admin_payments.py`: 30/30 passing (26 pre-existing +
  4 new). Full backend suite: **1184 passed, 10 skipped, 0 failed**
  (baseline 1180 + 4 new) — no regressions.
- admin-web: 1 new test in `adminApi.test.ts` confirming the new
  `order_number`/`customer` query params are actually sent. Full
  admin-web suite: 7/7 passing. `npx tsc --noEmit`: clean. `npm run
  build` (which runs `tsc` first): clean production build.

## Live verification (real dev server)
Seeded a real admin, a real online (Razorpay) payment genuinely in
`PARTIALLY_REFUNDED` with a real `PROCESSING` `Refund` row attached, plus
a `razorpay_signature` value deliberately planted to prove it never
leaks, then drove the real HTTP endpoints:
- `GET /admin/payments?order_number=...` → the seeded payment, with
  `provider: "Razorpay"`, `paid_at` populated, `latest_refund_status:
  "processing"`.
- `GET /admin/payments?customer=...` → same payment, confirming the new
  customer filter.
- `GET /admin/payments?status=PARTIALLY_REFUNDED` → same payment,
  confirming the previously-unselectable status is genuinely filterable.
- `GET /admin/payments/{id}` (detail) → the same fields, plus the real
  `refunds` array showing the `PROCESSING` refund; grepped the full
  response text for the planted signature and for the string
  `razorpay_signature` — zero matches either way.
- Unauthenticated request → `401`.

All live test data cleaned up afterward (`psql`, FK-dependency order,
verified zero rows remaining).

## Known limitations
No refund action exists anywhere in `admin-web` yet — the backend
capability (Phase 23) has been live for a while, but the UI to actually
issue a refund from the admin panel was never built and remains out of
this phase's own view-only scope. `search` and the new `order_number`/
`customer` filters can be combined in the same request (ANDed) but the
admin-web UI doesn't currently surface that as an intentional combined
search — a minor UX nicety, not a correctness gap.
