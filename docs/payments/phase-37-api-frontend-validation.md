# Phase 37 — API & Frontend Validation

## Scope
Verify all payment APIs (URL, HTTP method, request, response,
authentication, authorization, error handling, loading/success/
failure/retry state). Customer UI must clearly distinguish: payment
successful, payment failed, payment pending, payment cancelled,
refund pending, refund completed.

## Method
Two passes: a static inventory + re-verification of every
payment-related backend endpoint's auth gate and error-handling
contract (no backend behavior was found to be wrong — this pass is
confirmation, matching Phase 31's "verification-only" pattern), and a
frontend audit (via an Explore subagent) of how `customer-mobile`
renders each of the 8 real `PaymentStatusValue`s across every screen
that shows one. The frontend audit found real gaps; this phase's
actual code changes are all in `customer-mobile`.

## Backend API inventory

| Endpoint | Method | Auth | Ownership check | Error handling |
|---|---|---|---|---|
| `/customer/payment-methods` | GET | `require_customer` | n/a | — |
| `/customer/payments` | GET | `require_customer` | scoped to `current_user` (Phase 26) | — |
| `/customer/orders/{order_id}/payment` | POST | `require_customer` | `_get_owned_order_or_404` | 404 if not owned |
| `/payments/create` | POST | `require_customer` | `_get_owned_order_or_404` | 404/409 |
| `/payments/order/{order_id}` | GET | `require_customer` | `_get_owned_order_or_404` | 404 |
| `/payments/{payment_id}` | GET | `require_customer` | owned via order | 404 |
| `/payments/{payment_id}/verify` | POST | `require_customer` | `_get_owned_payment_or_404` | 400 (verification failed), 409 (already resolved), 410 (expired), 502 (provider unreachable) |
| `/payments/{payment_id}/retry` | POST | `require_customer` | `_get_owned_payment_or_404` | 400/409/410/502 as above |
| `/payments/webhooks/razorpay` | POST | none (HMAC signature) | n/a — identifies payment/order from the verified event body | 400 (missing/invalid signature), 503 (webhook secret not configured); never 4xx for a well-formed but unactionable event (Phase 17/18) |
| `/admin/payments` | GET | `require_admin` | n/a (platform-wide) | filters: status/method/date range/order id/customer |
| `/admin/payments/{payment_id}` | GET | `require_admin` | n/a | 404 |
| `/admin/payments/{payment_id}/refund` | POST | `require_admin` | n/a | 400/404/409 |
| `/rider/earnings`, `/rider/earnings/summary` | GET | `require_rider` | scoped to `current_rider` (Phase 29) | — |
| `/rider/deliveries/{order_id}/cod-collect` | POST | `require_rider` | scoped to rider's own assignment | 400/404/409 |
| `/restaurant/orders/*` (earning/commission fields) | GET | restaurant-owner auth | scoped to owned restaurant (Phase 28) | 404 |

No `RAZORPAY_KEY_SECRET`, `RAZORPAY_WEBHOOK_SECRET`, JWT secret, or
database credential is present in any response model across these
endpoints — re-confirmed by grepping every `schemas/*.py` payment
model, consistent with Phase 31's original audit.

## Frontend gaps found and fixed

`customer-mobile` is the only client with a customer-facing payment
status UI (business-web/admin-web/rider-mobile show payment data but
were already covered by Phases 27-29's own visibility rules). An
Explore subagent's audit of all three screens that render a payment
status (`app/checkout.tsx`, `app/orders/[id].tsx`,
`app/payments.tsx`) found:

1. **No shared status mapping.** Three to four independent,
   disagreeing implementations existed. `orders/[id].tsx`'s own
   `paymentStateLabel()` only had cases for `paid`/`failed`/
   `processing` — the other four real statuses (`cancelled`,
   `refund_pending`, `partially_refunded`, `refunded`) all silently
   fell through to a generic "Payment pending" orange badge, and a
   "Complete Payment" retry button showed even for a fully refunded
   payment (mislabeled — refunds aren't retryable).
2. **`razorpay-flow.ts` folded genuine "pending" into "failed".**
   `RazorpayFlowOutcome` had only `paid`/`failed`/`unavailable`/
   `unknown`; a payment that was neither confirmed paid nor confirmed
   failed (e.g. still settling) was reported to the customer as
   "Payment not completed" — a false failure for an unresolved state.

**Fix — one shared source of truth.** New
`customer-mobile/utils/paymentStatus.ts`:
- `paymentStatusMeta(status)` — the single label/color/background for
  all 8 statuses (`pending`, `processing`, `paid`, `failed`,
  `cancelled`, `refund_pending`, `partially_refunded`, `refunded`),
  each visually distinct (refund states each get their own color, not
  a shared "refund" bucket, so a customer can tell "refund pending"
  from "refund completed" at a glance).
- `isPaymentActionable(status)` — true only for `null`/`undefined`
  (no payment started yet), `pending`, `processing`, `failed`; never
  true for `paid` or any refund-related state.

`app/orders/[id].tsx`: adopted both helpers, removed the old
`paymentStateLabel()`, added a refund-pending explanatory line, and
gave the payment card a static title ("Online payment" /
"Payment not started") separate from the status badge — avoids
showing the same status text twice in one card.

`features/payments/razorpay-flow.ts`: added a genuine `"pending"`
variant to `RazorpayFlowOutcome`; the post-checkout refetch now
returns `paid`/`failed`/`pending` as three distinct, independently
decided outcomes (only a caught exception during the refetch itself
still maps to `"unknown"`). Propagated into both call sites —
`checkout.tsx`'s `placeOrder()` and `orders/[id].tsx`'s
`handlePaymentAction()` — each now shows a distinct, non-alarming
"still processing" message for `"pending"` instead of falling into
the generic "Payment not completed" branch.

`app/payments.tsx`: replaced its own separate `statusLabel()`/
`statusStyle()` functions with `paymentStatusMeta()`, so all three
screens now agree on every status's label and color.

## A real bug found while fixing the above
`isPaymentActionable()`'s first draft only recognized `pending`/
`processing`/`failed`, so a customer with no payment record at all
(status `undefined`) lost the "Complete Payment" button entirely —
caught by the existing `order-detail.payment-retry.test.tsx` suite,
which still asserted the original behavior. Fixed by treating
`null`/`undefined` as actionable too.

## Files created
- `customer-mobile/utils/paymentStatus.ts`
- `docs/payments/phase-37-api-frontend-validation.md`

## Files modified
- `customer-mobile/app/orders/[id].tsx`
- `customer-mobile/features/payments/razorpay-flow.ts`
- `customer-mobile/app/checkout.tsx`
- `customer-mobile/app/payments.tsx`
- `customer-mobile/app/__tests__/order-detail.payment-retry.test.tsx` (updated two label assertions to match the new, clearer labels)
- `customer-mobile/app/__tests__/payments.screen.test.tsx` (same)

No backend files were changed — the API inventory pass confirmed
every endpoint's auth/ownership/error-handling contract was already
correct.

## Testing
- `npx tsc --noEmit` in `customer-mobile`: clean, no errors.
- Full `customer-mobile` Jest suite: **6 suites, 25 tests, all
  passing** (was 4 failing before the label/actionability fixes
  above — all four were genuine gaps: two outdated test expectations
  updated to match clearer new labels, and one real
  `isPaymentActionable` bug fixed).
- Backend: full `pytest` suite re-run to confirm the dev server/DB
  state is still healthy after this phase (no backend files touched)
  — **1232 passed, 10 skipped, 0 failed**, unchanged from baseline.

## Live verification
Backend endpoint inventory and auth dependencies re-confirmed by
grepping the running codebase directly (`require_customer`/
`require_admin`/`require_rider` on every route, ownership checks via
`_get_owned_order_or_404`/`_get_owned_payment_or_404`), matching
Phase 31's original security audit with no drift found.

## Known limitations
This phase's frontend fixes are code-level and test-verified only —
there is no device/emulator/screenshot capability in this
environment, so the 6 required visual states were confirmed via
Jest/RTL text assertions per state, not a rendered screenshot.
