# Phase 28 — Restaurant Payment Visibility

## Scope
Restaurant Owner should see appropriate financial information: Order
amount, Restaurant earning, Commission, Net amount, Payment method,
Payment status. Do not expose: Customer payment credentials, Razorpay
secret, Internal payment security data. Historical financial values must
remain stable.

## What was found
Everything the four money figures needed already existed, just not
exposed to the restaurant owner:

- `CommissionRule` (Admin Portal Phase 17) and `compute_effective_commission()`
  (`app/services/commissions.py`) — the platform's commission concept,
  already correctly snapshotted once, at order-creation time, onto
  `Order.commission_type`/`commission_rate`/`commission_amount`. Its own
  docstring already states the exact invariant this phase's "historical
  values must remain stable" requirement asks for: *"Nothing in this
  codebase ever re-reads a CommissionRule to recompute a historical
  order's already-stored commission."* Nothing needed to change here —
  just be careful to never violate that invariant while building this.
- `Order.subtotal`/`total`/`payment_method`/`payment_status` — already
  real columns, already returned by the shared `OrderRead` schema, just
  never consumed by `business-web`'s `OrderDetails.tsx` (`payment_status`
  was fetched into the TS object but never actually rendered anywhere).
- No "restaurant earning" / "net amount" concept existed anywhere as a
  named field — both are simple, derivable-on-read values from the
  already-frozen `subtotal`/`commission_amount` columns, not something
  that needed a new ledger table (unlike rider earnings, this isn't a
  running balance — it's a per-order figure the existing admin financial
  reports (`app/services/admin_reports.py`) already compute the same way
  platform-wide, confirming the formula).

## A schema-sharing risk, caught before writing the endpoint code
`OrderRead` — the schema `GET /restaurant/orders/{id}` returns — is the
**same** schema the customer's own `GET /customer/orders/{id}`, the
rider's, and part of the admin's order endpoints all return. Adding
`restaurant_earning`/`commission`/`net_amount` directly to `OrderRead`
would have leaked the platform's commission structure to customers and
riders, neither of whom have any reason to see it. Built a separate
`RestaurantOrderDetailRead(OrderRead)` instead, used only by the
`restaurant/orders` router — the shared `OrderRead` itself is completely
untouched.

## What was built

### Backend
- `app/services/orders.py::compute_restaurant_financials(order)` — a
  pure function reading only `order.subtotal` and
  `order.commission_amount` (never calling `compute_effective_commission()`
  or touching `CommissionRule` again):
  - `restaurant_earning` = `order.subtotal` (the gross food-sale amount —
    what the restaurant would keep with no platform commission at all;
    delivery fee and tax are never the restaurant's own money).
  - `commission` = `order.commission_amount`, or `0.00` if it was never
    recorded (orders placed before the commission concept existed at
    all — treated as zero, never recomputed from today's rule, the same
    "old orders keep whatever they actually recorded" principle used
    everywhere else in this codebase).
  - `net_amount` = `restaurant_earning - commission` — what the
    restaurant actually nets.
- `RestaurantOrderListItem` (the incoming-orders list, already
  restaurant-owner-only) gained `payment_status`, `restaurant_earning`,
  `commission`, `net_amount` directly.
- New `RestaurantOrderDetailRead(OrderRead)` — adds the same three
  financial fields on top of the shared `OrderRead` shape, used only by
  the restaurant router.
- **Every** restaurant order endpoint that hands back an order —
  `GET /orders/{id}` and the four action endpoints (`accept`, `reject`,
  `preparing`, `ready`) — now returns `RestaurantOrderDetailRead`, not
  just the initial GET. `business-web`'s `OrderDetails.tsx` replaces its
  entire local order state with whatever an action endpoint returns
  (`setOrder(updated)`); if only the initial GET had these fields, the
  owner's earnings display would go blank the moment they accepted or
  progressed an order. A shared `_to_detail()` helper keeps all five
  endpoints' conversion identical.
- "Order amount" is the existing `total` field (already present on both
  schemas) — not duplicated under a new name, just labeled "Order
  amount" in the UI. "Payment method" and "Payment status" are the
  existing `Order.payment_method`/`payment_status` columns — never a
  join against the `Payment` model at all, so there is no code path by
  which `razorpay_signature`, `razorpay_order_id`, `razorpay_payment_id`,
  or any provider secret could end up in a restaurant-owner response.

### business-web
- `ordersApi.ts` — `OrderListItem`/`OrderDetail` types extended with the
  four new fields.
- `Orders.tsx` — the incoming-orders list row now shows Net amount and
  Payment method · Payment status.
- `OrderDetails.tsx` — Payment method line now shows the real payment
  status (previously always "Paid"/"Pending" from `is_paid`, which
  couldn't distinguish e.g. a failed or refunded payment); a new "Your
  earnings" section shows Order amount, Restaurant earning, Commission,
  and Net amount, right after the existing Bill summary.

## Files modified
- `backend/app/services/orders.py`
- `backend/app/schemas/order.py`
- `backend/app/api/v1/restaurant/orders.py`
- `business-web/src/services/api/ordersApi.ts`
- `business-web/src/pages/restaurant/Orders.tsx`
- `business-web/src/pages/restaurant/OrderDetails.tsx`
- `business-web/src/pages/restaurant/Orders.test.tsx`

## Files created
- `backend/tests/test_restaurant_payment_visibility.py`
- `business-web/src/pages/restaurant/OrderDetails.test.tsx`
- `docs/payments/phase-28-restaurant-payment-visibility.md`

## Testing
- Backend: 8 new tests in `test_restaurant_payment_visibility.py` —
  zero-commission fallback, correct derivation from a real
  `CommissionRule`, **the core stability guarantee** (changing a
  commission rate after an order is placed never changes that order's
  own reported figures), list/detail include all six required fields,
  no payment secret ever appears in either response's raw text,
  cross-owner isolation (404, not another owner's data), and the accept
  action endpoint keeps returning the financial fields. All 8 passed
  on the first run. Full regression sweep across every test file
  touching restaurant order endpoints (19 files, 116 tests): unaffected.
  Full backend suite: **1192 passed, 10 skipped, 0 failed** (baseline
  1184 + 8 new) — no regressions.
- business-web: 1 new test file (`OrderDetails.test.tsx`, 2 tests) plus
  2 new assertions added to the existing `Orders.test.tsx` (its own mock
  order object needed the new required fields, or `rupees()`/`.replace()`
  would throw on `undefined` — not a behavioral regression, just the
  mock catching up to the real response shape). Full suite: 13/13
  passing. `npx tsc --noEmit`: clean. `npm run build`: clean production
  build.

## Live verification (real dev server)
Seeded a real restaurant with its own 12% `CommissionRule` override and a
real ₹200-subtotal COD order through the actual service layer, then
drove the real HTTP endpoints as the restaurant owner:
- List and detail both returned `restaurant_earning: 200.00`,
  `commission: 24.00`, `net_amount: 176.00`, `payment_method: "cod"`,
  `payment_status: "pending"` — correct.
- **The core proof**: updated that same `CommissionRule` live (via
  `psql`) from 12% to 50%, then re-fetched the order's detail through the
  real HTTP endpoint — `commission`, `restaurant_earning`, and
  `net_amount` all came back byte-for-byte identical to before the rate
  change, confirming the "historical values must remain stable"
  requirement holds against a genuine, live rate change, not just a unit
  test.
- Grepped the full detail response for `razorpay_signature`,
  `razorpay_key`, and `password` — no matches.
- Unauthenticated request → `401`.

All live test data cleaned up afterward (`psql`, FK-dependency order,
verified zero rows remaining).

## Known limitations
The restaurant dashboard's own `today_sales`/`pending_earnings`
(`RestaurantDashboardResponse`) still report gross `subtotal` sums with
no commission subtraction — out of this phase's scope (it asked for
per-order visibility, not a dashboard-level net-earnings rollup); a
natural candidate for a future phase if wanted.
