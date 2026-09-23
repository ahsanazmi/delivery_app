# Phase 33 — Complete COD E2E Test

## Scope
Run: Customer → COD Checkout → Order → Restaurant → Rider → Delivery →
COD Collection → Rider Ledger → Settlement → Admin Reconciliation.
Verify every database record.

## Method
One new, canonical, comprehensive test
(`test_complete_cod_flow_every_database_record_verified`) drives the
exact eleven-step flow this phase diagrams entirely through the real
HTTP API (never calling a service function directly), and — after
every single step — queries the database directly and asserts on the
actual rows produced, not just the API's own JSON response. Every table
this flow touches gets its own explicit assertion block: `orders`,
`order_items`, `order_status_history`, `delivery_assignments`,
`payments`, `cod_collections` (Phase 30), `rider_earnings`,
`rider_settlements`, `cod_settlement_allocations` (Phase 30), and
`admin_audit_logs` — plus the admin reconciliation and reports
endpoints, cross-checked against those same rows.

## What was verified, stage by stage

1. **Customer → COD Checkout → Order** — `POST /customer/orders`
   produces one `Order` row (status `PLACED`, `payment_method="cod"`,
   correct `subtotal`/`delivery_fee`/`total`, the commission snapshot
   frozen at this exact moment), one `OrderItem` row, and the order's
   first `OrderStatusHistory` row.
2. **Restaurant** (accept → preparing → ready) — three more
   `OrderStatusHistory` rows append in order (`CONFIRMED`, `PREPARING`,
   `READY_FOR_PICKUP`); `Order.status` tracks each transition.
3. **Rider** (accept → pickup → start) — one `DeliveryAssignment` row
   (`ACCEPTED`), `Order.rider_id` set, `Order.status` progressing
   through `RIDER_ASSIGNED` → `OUT_FOR_DELIVERY`.
4. **Delivery → COD Collection** — one `Payment` row (`provider=COD`,
   `payment_status=PAID`, `amount` exactly the order's own total,
   `collected_by_rider_id`/`collected_at` set) and its own independent
   `CodCollection` ledger row (Phase 30) — the same amount, never
   derived from the mutable `Payment` row alone.
5. **Delivery completed → Rider Ledger** — `Order.status = DELIVERED`,
   exactly one `RiderEarning` row (`DELIVERY_FEE`, amount equal to the
   restaurant's own `delivery_fee`, never the full COD amount), and the
   real `GET /rider/wallet` response's `wallet_balance` correctly
   reflects a rider holding customer cash they don't own
   (`earnings − cod_collected`, negative until settled).
6. **Settlement** — two admin settlements (a deliberate partial, then
   the remainder) produce two `RiderSettlement` rows, and — the
   traceability Phase 30 built — two `CodSettlementAllocation` rows
   that together sum to exactly the full collected amount, plus two
   `AdminAuditLog` rows each recording the correct before/after
   outstanding figure.
7. **Admin Reconciliation** — `GET /admin/cod/{rider_id}` shows
   `SETTLED`, zero outstanding, both settlements with their own
   itemized allocations; `GET /admin/reports/overview` shows the full
   reconciliation identity holding exactly:
   `restaurant_earnings + platform_commission + rider_earnings == revenue`.
   `Payment.amount` is checked one final time at the very end of the
   whole eleven-step flow and is still exactly what it was at
   collection — never overwritten by anything downstream, consistent
   with Phase 25's own "never overwrite the original payment amount"
   guarantee.

No gaps were found — every table was already correctly populated by
existing code from Phases 8/9 (COD), 16/17 (order lifecycle), 19
(delivery lifecycle), 23/24 (rider earnings), and 30 (the ledger this
phase's own "Rider Ledger" step names). This phase's contribution is
the single, canonical, whole-flow-at-once test proving it, plus a live
run against the real database.

## Files created
- `backend/tests/test_complete_cod_e2e.py`
- `docs/payments/phase-33-complete-cod-e2e-test.md`

## Testing
- New: 1 comprehensive test, exercising all eleven diagrammed stages
  and asserting on ten distinct database tables plus two admin API
  responses. Passed on the second attempt — the first failure was a
  test-authoring misunderstanding of `RiderWalletRead.settlement_due`'s
  actual meaning (it mirrors `wallet_balance`, not
  `total_cod_collected`), not a product bug.
- Full backend suite: **1227 passed, 10 skipped, 0 failed** (baseline
  1226 + 1 new) — no regressions.

## Live verification (real dev server)
Drove the identical eleven-stage flow against the real running server
and real Postgres — registering a genuine customer, restaurant owner,
rider, and admin, placing a real ₹560 COD order (2× ₹260 item +
₹40 delivery fee, 10% commission), and carrying it all the way through
delivery, COD collection, a two-part settlement, and reconciliation.
Cross-checked every table directly via `psql` afterward: `orders`
(delivered, paid, correct totals/commission), `order_items`,
`order_status_history` (all 8 real transitions in order),
`delivery_assignments`, `payments`, `cod_collections`, `rider_earnings`
(₹40, `DELIVERY_FEE`), `rider_settlements` (₹560, `REMITTANCE`),
`cod_settlement_allocations` (₹560, fully allocated), and
`admin_audit_logs` (`cod.settle`, final outstanding `0.00`) — every
single row matched what the test itself asserts, against genuinely
different (live) data.

While setting this up, found the project's Postgres container
(`backend-postgres-1`, port 5433) had stopped (exited some time
earlier, unrelated to this phase's own work) — restarted it before
proceeding; noted here since it briefly blocked the live run.

All live test data cleaned up afterward (`psql`, FK-dependency order,
verified zero rows remaining).

## Known limitations
This test uses the same `DeliveryPartner`-direct-insert shortcut for
rider onboarding that `test_admin_financial_integration.py` already
established (bypassing the full document-upload/verification HTTP
flow) — that flow is exercised by its own dedicated rider-onboarding
tests elsewhere, not re-proven here, to keep this phase's own test
focused on the money/record flow it's named for.
