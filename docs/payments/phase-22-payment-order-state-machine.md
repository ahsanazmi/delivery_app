# Phase 22 — Payment/Order State Machine

## Scope
Define clear relationships between order state and payment state. Do not
allow DELIVERED + PAYMENT FAILED, unless business rules explicitly allow
an unresolved payment state. Do not allow CANCELLED + a newly successful
payment without a defined refund/reconciliation workflow.

## The state machine, as it actually exists

```
ORDER PLACED
   │
   ├── COD
   │     ↓
   │   Payment created PENDING (record_order_payment)
   │     ↓
   │   DELIVERED → _settle_cod_payment_on_delivery() → Payment PAID, Order.is_paid=true
   │   (rider-only trigger; no other path can reach DELIVERED)
   │
   └── ONLINE (razorpay)
         ↓
      Payment created PENDING, real Razorpay order opened (create_payment_for_order)
         ↓
      PENDING ──verify──▶ PAID  (Payment Status Synchronization, Phase 16: Order.is_paid/payment_status sync)
         │                  │
         │                  └─ accept_order() now allowed → CONFIRMED → ... → DELIVERED
         └──verify (bad)──▶ FAILED ──retry──▶ PENDING (same provider order reopened, Phase 20)

Terminal, non-payable: CANCELLED, REJECTED — reachable from PLACED/CONFIRMED
(customer or admin/restaurant action), independent of payment state.
```

Two invariants this phase named, checked against that machine:

### Invariant 1 — DELIVERED + PAYMENT FAILED: already structurally impossible
`accept_order()` (Phase 16) already refuses to move a razorpay order to
`CONFIRMED` — the one and only step on the path to `DELIVERED` — while
`is_paid` is false. A `FAILED` payment is unpaid by definition, so a
`FAILED` payment can never coexist with `DELIVERED`: the order simply
never leaves `PLACED` until the payment actually succeeds. Verified with
two new tests (a `FAILED` payment blocks `accept_order()`; walking a
payment through to genuine `PAID` is the only way past it) — no code
change needed, since the existing Phase 16 gate already covers this
completely.

### Invariant 2 — CANCELLED + a newly successful payment: a real gap, now fixed
Neither `PaymentService.verify_payment()` (the client-driven path) nor
`_handle_payment_captured()` (the webhook path) checked the order's own
status before marking a payment `PAID`. A customer could open Razorpay
checkout, have the order cancelled out from under them (by an admin, a
restaurant rejection, or their own second device) while the checkout
sheet was still open, then complete the payment — resulting in a real
charge landing on a dead order, with the payment silently looking like a
normal, resolved success.

**The defined workflow**, implemented identically in both paths: the
verification/capture is still **accepted** — denying it wouldn't un-charge
the customer, it would just make this backend deny a real charge
happened — but the payment is marked `REFUND_PENDING` (an existing,
already-modeled status; never a plain `PAID`) instead, and an urgent
`SYSTEM_ALERT` admin notification is raised naming the order and the
amount, for manual refund/reconciliation. The order's own
`is_paid`/`payment_status` fields are deliberately left untouched — the
order keeps showing exactly the dead state it already had; the anomaly
is visible through the payment's own status and the alert, not by making
a cancelled order look paid. The underlying `PaymentAttempt` row still
honestly records `PAID` — it reflects what genuinely happened at the
gateway; the parent `Payment`'s status reflects the business-level
resolution, and the two are intentionally allowed to differ.

Scoped to `CANCELLED`/`REJECTED` specifically, not `DELIVERED` — a
late-arriving genuine payment for an order that was *actually fulfilled*
isn't an anomaly (the customer did receive their food), so that case is
correctly left to resolve as a normal `PAID` payment (and is, in any
case, already unreachable per Invariant 1's own reasoning).

## Files modified
- `backend/app/services/payment/payment_service.py`
- `backend/app/services/payment/webhook_service.py`

## Files created
- `backend/tests/test_payment_order_state_machine.py` (6 tests)
- `backend/tests/test_payment_webhooks.py` (+1 test, the webhook-path
  equivalent of the same scenario)

## Testing
- New: 7 tests — both invariants proven for the client-driven path
  (parametrized over `CANCELLED`/`REJECTED`) and the webhook path,
  confirming `REFUND_PENDING`, untouched order fields, exactly one admin
  alert, and the `PaymentAttempt`'s own honest `PAID` record; plus a
  confirmation that an ordinary payment on a still-live order is
  completely unaffected.
- Regression: 114/114 passing across every payment test file.
- Full backend suite: run after this change (confirmed in the next
  phase's report if not already landed at report time).

## Live verification (real dev server)
A genuinely *captured* payment can't be produced headlessly (same
constraint as Phases 14/15/17/18 — completing a real Razorpay checkout
needs a browser), so the `REFUND_PENDING` path itself is covered by the
realistic `FakeProvider`-based unit tests, which model Razorpay's actual
response shape precisely. What was verified live: a real order was
cancelled while its payment was still open, and a subsequent
forged/uncaptured verification attempt against that same payment was
still correctly rejected exactly as before — confirming this phase's new
order-status check sits cleanly alongside the existing checks rather than
interfering with them. 4/4 checks passed; test data cleaned up.

## Known limitations
Unchanged from prior phases — the unguarded legacy `/payments/{id}/refund`
endpoint and `Order.payment_status` being a plain string remain open.
There is no admin-web view yet specifically for `REFUND_PENDING`
payments (the `SYSTEM_ALERT` notification is the only surfaced signal
today) — a natural candidate for a future phase, not built here since
this phase's own scope is the state machine's correctness, not a new
admin UI.
