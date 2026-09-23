# Phase 16 — Payment Status Synchronization

## Scope
After verification: Payment → PAID → Order.payment_status = PAID. Update
order state only according to established business rules — never
accidentally change order status, restaurant status, or rider status
unless the payment workflow explicitly requires it. Explicitly: decide
and document whether a restaurant receives an online-paid order
immediately or only after payment confirmation.

## What was found — a real, live gap
`PaymentService.verify_payment()`'s success path (the actual, reachable
production path via `POST /api/v1/payments/{id}/verify`) marked
`Payment.payment_status = PAID` but **never touched `Order` at all**. A
customer could genuinely pay online and their order would sit at
`payment_status: "pending"`, `is_paid: false` forever — the exact
synchronization this phase asks for was simply missing from the live code
path. (The old, pre-Phase-5 `app.services.payments.verify_payment()` did
have this sync, but that function isn't reachable from any real endpoint
any more — see Phase 5's own notes — so it wasn't actually protecting
anything.)

## The business rule this phase asked for a decision on
**Decision: an online (razorpay) order is not shown to the restaurant, and
cannot be accepted by the restaurant, until its payment is confirmed
(`is_paid = true`). A Cash on Delivery order is completely unaffected —
it remains visible and acceptable immediately, exactly as before.**

Rationale: preparing food for an order whose payment hasn't actually
settled is a real, avoidable business risk — if the payment then fails or
is never completed, the restaurant has wasted kitchen time and ingredients
with no way to recover the cost. COD carries no such risk (cash is
collected on delivery, independent of any gateway), so it keeps its
existing, immediate-visibility behavior. This mirrors standard practice at
comparable food-delivery platforms.

Investigation before implementing confirmed this rule was easy to enforce
cleanly: `create_order()` never notifies the restaurant directly (only the
customer, via `notify_order_placed`), and nothing restaurant-facing
broadcasts at order-creation time — the restaurant only ever learns about
an order by querying its own order list or dashboard. That meant the rule
could be implemented as two straightforward layers, with no changes
needed to notifications, the order state machine, or anything rider-side:

1. **Visibility** — `list_restaurant_orders()` and the dashboard's pending
   query/count both exclude an order when (and only when) it is
   `status == PLACED`, `payment_method == "razorpay"`, and `is_paid ==
   False`. Scoped specifically to PLACED — a CANCELLED/REJECTED order in
   this same state is left visible (it's a dead, informational record;
   there's nothing to protect the restaurant from acting on), and no
   order can reach CONFIRMED or later without `is_paid` already being
   true, so the condition is structurally never true past PLACED anyway.
2. **Enforcement** — `accept_order()` itself now refuses
   (`409 Conflict`) to move a `razorpay` order to `CONFIRMED` while
   `is_paid` is still false. This is the real guard, not just a UX
   convenience — it holds even against a stale or otherwise-obtained
   order id, independent of whatever the restaurant's own order list
   currently shows.

## What was built
- `PaymentService.verify_payment()`'s success path now syncs
  `order.payment_status = "paid"` and `order.is_paid = True` —
  deliberately nothing else. `order.status` stays exactly where
  `create_order()` left it (`PLACED`); no `Restaurant` field is touched;
  no rider/`DeliveryAssignment` field is touched.
- `accept_order()` gains the payment-confirmed gate described above.
- `list_restaurant_orders()` and `get_restaurant_dashboard()`'s pending
  query/count gain the same visibility exclusion.

## Files modified
- `backend/app/services/payment/payment_service.py`
- `backend/app/services/orders.py`
- `backend/app/services/restaurant_dashboard.py`

## Files created
- `backend/tests/test_payment_status_synchronization.py` (6 tests)

## Testing
- New: 6/6 passing — a successful verification syncs only
  `payment_status`/`is_paid` (order status, `Restaurant.is_active`, and
  `rider_id` all proven untouched); an unpaid online order is hidden from
  both the order list and the dashboard's pending count; accepting it
  directly by id is blocked (409) and leaves `status` at `PLACED`; once
  paid, the same order becomes visible and acceptable; a COD order is
  completely unaffected throughout.
- Regression: restaurant order/dashboard suites (115 tests across
  `test_restaurant_incoming_orders.py`, `test_restaurant_order_decisions.py`,
  `test_restaurant_order_lifecycle_boundary.py`,
  `test_restaurant_order_preparation.py`, `test_orders.py`,
  `test_customer_orders.py`, and the Phase 6/12/14/15 payment suites) —
  all passing.
- Full backend suite: run after this change (confirmed in the next
  phase's report if not already landed at report time).

## Live verification (real dev server)
Created a real online order against the real running backend: confirmed
it was absent from the restaurant's real pending list and dashboard, and
that `POST /restaurant/orders/{id}/accept` returned 409. `verify_payment`'s
own sync logic can't be exercised against a genuinely captured payment
headlessly (same constraint noted in Phases 14/15), so its *result* was
applied directly to the same real order (`payment_status='paid'`,
`is_paid=true`) to prove the second half of the gate: the order then
correctly appeared in the pending list and accept succeeded, moving it to
`confirmed`. 11/11 checks passed across both parts. Live test data cleaned
up.

## Known limitations
Unchanged from prior phases — the unguarded legacy `/payments/{id}/refund`
endpoint and `Order.payment_status` being a plain string remain open.
