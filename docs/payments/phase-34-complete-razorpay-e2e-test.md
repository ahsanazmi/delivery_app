# Phase 34 — Complete Razorpay E2E Test

## Scope
Run: Customer → Checkout → Online Payment → Backend Creates Razorpay
Order → Razorpay Checkout → Payment → Frontend Callback → Backend
Verification → Webhook → Payment PAID → Order Payment Status Updated →
Restaurant → Rider → Delivery → Admin. Verify: Order, Payment,
PaymentAttempt, Provider Order, Provider Payment, WebhookEvent,
Restaurant earning, Commission, Rider earning are consistent.

## Method
One new, canonical, comprehensive test
(`test_complete_razorpay_flow_every_record_consistent`) drives the
exact flow this phase diagrams entirely through the real HTTP API. Only
the Razorpay gateway itself is faked (a minimal `FakeRazorpay` standing
in for the real network calls to `api.razorpay.com`) — every line of
this backend's own code (`PaymentService`, the `/verify` endpoint,
`process_webhook_event()`, order/restaurant/rider/admin flows) runs for
real, unmocked. This mirrors Phase 33's own approach for the COD flow,
adapted for the two things COD doesn't have: a real provider round trip
and a webhook.

## What was verified, stage by stage

1. **Customer → Checkout → Online Payment (Order placed)** —
   `POST /customer/orders` with `payment_method="razorpay"` produces an
   `Order` row only; no `Payment` yet (Checkout Payment Decision,
   Phase 6, deliberately separates the two).
2. **Backend Creates Razorpay Order** —
   `POST /customer/orders/{id}/payment` calls the (faked) provider's
   `create_order()`, producing one `Payment` row (`PENDING`,
   `razorpay_order_id` set to the provider's own order id) and its
   first `PaymentAttempt` row (`PENDING`) — `Order.is_paid` still
   `False` at this point, correctly.
3. **Razorpay Checkout → Payment → Frontend Callback → Backend
   Verification** — `POST /payments/{id}/verify` with a genuinely
   matching `(provider_order_id, provider_payment_id, signature)`
   triple runs the real three-way check (Phase 14/15: order-id match,
   signature, provider-confirmed amount/currency/capture state) and
   marks the `Payment` `PAID`, syncs `Order.is_paid`/`payment_status`
   (Phase 16), and records a **second**, distinct `PaymentAttempt` row
   (`PAID`) — both attempts kept, neither overwritten.
4. **Webhook → Payment PAID → Order Payment Status Updated** — a
   genuinely HMAC-signed `payment.captured` webhook for the exact same
   event, arriving *after* verification already settled everything
   (this phase's diagram order), resolves to `duplicate_ignored` — one
   `WebhookEvent` row, correctly linked to this exact `Payment`, with
   nothing re-mutated (Phase 18's own idempotency guarantee, now proven
   in the same flow as a real verification, not in isolation).
5. **Restaurant → Rider → Delivery** — accept/preparing/ready,
   accept/pickup/start/complete all succeed normally (an online-paid
   order is confirmable immediately, per Phase 16); no COD-collection
   step exists in this path at all — already paid. `Order.status`
   reaches `DELIVERED`, and exactly one `RiderEarning` row is credited
   (the restaurant's own `delivery_fee`, never the full order total).
6. **Admin** — `GET /admin/payments/{id}` shows the correct amount,
   status, and provider name; `GET /admin/reports/overview` shows the
   full reconciliation identity holding exactly:
   `restaurant_earnings + platform_commission + rider_earnings == revenue`.

### The nine named records, cross-checked directly against each other
- **Order ↔ Payment** — `Payment.order_id` matches, `Payment.amount`
  equals `Order.total` exactly.
- **Payment ↔ Provider Order / Provider Payment** — `Payment.razorpay_order_id`
  matches the fake gateway's own order record; `Payment.razorpay_payment_id`
  matches the id the simulated checkout produced.
- **Payment ↔ PaymentAttempt** — both attempt rows reference this exact
  payment, one per real interaction with the provider (order-open,
  verify), neither ever mutated to represent a different event.
- **Payment ↔ WebhookEvent** — the event's own `payment_id` and
  `provider_payment_id` both correctly point back to this same payment.
- **Order ↔ Commission** — `Order.commission_amount` is still exactly
  what it was frozen to at order-creation time, untouched by anything
  downstream.
- **Order ↔ Rider earning** — the `RiderEarning` row's `order_id`
  matches, amount is exactly the delivery fee.

No gaps were found — every record was already correctly produced by
existing code from Phases 4/5/6 (payment creation), 14/15/16 (signature/
amount verification and status sync), 17/18 (webhooks and idempotency),
and 23/28 (commission and rider earning). This phase's contribution is
the single, canonical, whole-flow-at-once test proving all nine records
agree with each other, plus a live proof of the one genuinely
network-dependent step (opening a real Razorpay order).

## Files created
- `backend/tests/test_complete_razorpay_e2e.py`
- `docs/payments/phase-34-complete-razorpay-e2e-test.md`

## Testing
- New: 1 comprehensive test, exercising the full 13-stage flow and
  cross-checking all nine named records. Passed on the first real
  attempt (after removing some leftover draft-editing cruft caught
  before running, not a test failure).
- Full backend suite: **1228 passed, 10 skipped, 0 failed** (baseline
  1227 + 1 new) — no regressions.

## Live verification (real dev server)
The one step in this flow that genuinely talks to a real third-party
service — "Backend Creates Razorpay Order" — was proven against the
**real** Razorpay test-mode API, not the fake: placed a real order,
called the real `POST /customer/orders/{id}/payment`, and got back a
genuine Razorpay order id (`order_TfYnNIdv28iKnD`-shaped, Razorpay's
own real format) with the public `razorpay_key_id` correctly included
and no secret anywhere in the response. Confirmed via direct `psql`
query that both the `Payment` row and its first `PaymentAttempt` row
correctly reference that exact real provider order id.

All live test data cleaned up afterward (`psql`, FK-dependency order,
verified zero rows remaining).

## Known limitations
Completing a genuinely *captured* payment (the checkout-sheet-to-capture
step) can't be produced headlessly — the same constraint documented
since Phase 11/14: a real Razorpay checkout needs a browser. The
verification/webhook/downstream-consistency stages are therefore proven
against a faithful `FakeRazorpay` stand-in rather than a live capture;
only the order-creation step (the one step this environment *can*
complete against the real gateway) was live-proven end to end.
