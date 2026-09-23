# Phase 30 — Financial Ledger Validation

## Scope
Verify: Customer payment → Platform → Restaurant earning / Platform
commission / Rider earning. For COD: Customer cash → Rider → COD ledger
→ Settlement → Platform/restaurant reconciliation. Do not use simple
balance overwrites. Every financial movement should be traceable.

## Audit method
A dedicated research pass traced every money-tracking model in the
codebase (`app/models/`), every write site that touches a financial
field (`app/services/`), and the exact row-by-row chain of what gets
created when one online order and one COD order are placed, paid,
delivered, and (for COD) settled — checking two properties against
every step: **no simple balance overwrites** (a mutable running-total
column, directly incremented/overwritten) and **every financial
movement traceable** (a permanent, attributable record — who/what,
when, how much — not just a status flag flipped in place).

## What was found — solid, no gap
- **No mutable balance column exists anywhere.** Grepped every model in
  `app/models/` for anything resembling `balance`/`wallet`/
  `total_earnings`/`outstanding` as a persisted column: zero matches.
  `Restaurant` and `User` carry no money-tracking column at all.
  `rider_wallet.py`'s `wallet_balance`, `admin_reports.py`'s revenue
  figures, and `admin_cod.py`'s `outstanding_amount` are all computed
  fresh, every call, by summing ledger rows — never read from or written
  to a stored total.
- **Online payment verification** — `PaymentAttempt` (append-only; a new
  row per verification attempt, success or failure, with structured
  failure reasons) already gives a complete audit trail. No gap.
- **Refunds** — `Refund` (append-only, Phase 23/24) already gives a
  complete, per-refund trail, with the parent `Payment`'s own status
  only ever recomputed from genuinely settled `Refund` rows.
- **Rider delivery earning** — `RiderEarning` (append-only; one
  `DELIVERY_FEE` row per delivered order, credited exactly once at
  `complete_delivery()`, confirmed regression-tested against
  double-crediting on a retried completion call). No gap.
- **Platform commission** — `Order.commission_type`/`commission_rate`/
  `commission_amount`, frozen once at order-creation time
  (`compute_effective_commission()`, Admin Portal Phase 17) and never
  re-read afterward. "Total commission" is always a fresh `SUM` over
  this column (`admin_reports.py`), not a separate stored ledger — this
  is sufficient, not a gap: the order-scoped snapshot already is the
  permanent record, and a separate ledger table would just duplicate it.
  Regression-tested: changing today's commission rule never alters a
  historical order's own contribution to reports.
- **Rider settlements (as an insert mechanism)** — `RiderSettlement`
  (append-only; `admin_settle_cod()`'s own docstring already establishes
  "always an INSERT... never an update to some cached balance column").
  No gap in the insert mechanism itself.

## What was found — two real gaps, both around COD (fixed this phase)
1. **COD cash collection had no dedicated ledger row.** `collect_cod_payment()`
   only ever mutated fields (`collected_by_rider_id`, `collected_at`,
   `amount`, `payment_status`) on the single per-order `Payment` row —
   the only trace of "rider X collected cash for order Y at time T" was
   those mutated fields, unlike every other financial movement in this
   codebase, each of which already has its own dedicated, insert-only
   ledger row. Structurally correct *today* (nothing currently
   overwrites those fields again), but not structurally protected the
   way `PaymentAttempt`/`Refund`/`RiderEarning`/`RiderSettlement` all
   already are — and the phase's own flow diagram explicitly names
   "COD ledger" as a distinct step between Rider and Settlement,
   confirming this was meant to be a real, first-class ledger, not an
   implicit side effect of a status mutation.
2. **Settlement had no item-level linkage.** A `RiderSettlement` row
   recorded who/when/how-much at the aggregate rider level (with a full
   audit-log entry — Phase 11), but there was no way, given a
   settlement, to trace back to which specific collected orders/payments
   it actually discharged. A rider's outstanding balance was always
   `collected - settled` in aggregate; a *partial* settlement had no
   record of which order's cash was "still owed" versus "already
   covered."

Both gaps were confirmed with the user before fixing (a deliberate
"how much should this phase fix" checkpoint, given the size of the
change), who chose to fix both.

## What was built

### `CodCollection` — the missing ledger (new model + table)
An append-only row inserted by `collect_cod_payment()` at the exact
moment a rider collects cash, alongside (not instead of) the existing
`Payment` mutation: `payment_id`, `order_id`, `rider_id`, `amount`,
`collected_at`. `UniqueConstraint("payment_id")` makes "never
double-collect the same order's cash" a database-enforced guarantee, not
just something the existing `is_paid` application-level guard happens to
prevent today. The idempotent-retry path (a same-rider retry returning
the existing collection rather than erroring, Phase 28) returns *before*
reaching this insert, so a retry never creates a duplicate row — proven
by a dedicated test, not just asserted.

### `CodSettlementAllocation` — the missing item-level link (new model + table)
A many-to-many join between `RiderSettlement` and `CodCollection`, with
its own `amount_allocated` (a single collection can be split across more
than one settlement if settled partially; a single settlement can cover
more than one collection). `admin_settle_cod()` now allocates FIFO —
oldest unallocated `CodCollection` first — walking this rider's
collections in `collected_at` order, taking `min(remaining_on_this_collection,
remaining_to_allocate)` from each until the settlement's full amount is
placed. This always succeeds without running short: since every
collection is ledgered exactly once and every past settlement was itself
always fully allocated the same way, the sum of every unallocated
remainder for a rider is always exactly equal to that rider's own
`outstanding` figure — which `amount <= outstanding` already validates
before allocation begins.

### Backfill (data migration, not just schema)
Two real COD collections already existed in the dev database from
earlier phases' work, predating this table. The migration backfills a
`CodCollection` row for every existing `Payment` with
`provider='cod' AND collected_by_rider_id IS NOT NULL`, so the FIFO
allocation invariant above holds for 100% of existing collected cash
from the moment this migration lands, not just for collections made
afterward.

### Traceability surfaced to the admin
`AdminCODSettlementRecord` (the settlement history already shown on the
admin COD reconciliation page) gained `allocations: list[...]` — each
entry names the exact order, how much of that order's cash this
settlement covers, and when it was originally collected. `admin-web`'s
COD Reconciliation page now shows this itemization under each settlement
row.

## Files modified
- `backend/app/services/rider_deliveries.py`
- `backend/app/services/admin_cod.py`
- `backend/app/models/__init__.py`
- `backend/app/schemas/admin.py`
- `backend/tests/test_admin_cod_reconciliation.py`
- `admin-web/src/services/api/adminApi.ts`
- `admin-web/src/pages/CODReconciliation.tsx`

## Files created
- `backend/app/models/cod_collection.py`
- `backend/app/models/cod_settlement_allocation.py`
- `backend/alembic/versions/20261003_44_create_cod_collections_and_allocations.py`
- `backend/tests/test_financial_ledger_validation.py`
- `docs/payments/phase-30-financial-ledger-validation.md`

## Testing
- New: 2 comprehensive end-to-end tests in
  `test_financial_ledger_validation.py` — two real COD orders delivered
  by the same rider, a single settlement smaller than the combined total
  correctly allocates FIFO (fully discharging the older collection,
  partially discharging the newer one, provably never split evenly or
  reversed), a second settlement correctly resumes against the *same*
  partially-covered collection's own remaining balance, every collected
  rupee is accounted for exactly once at the end (`total_collected ==
  total_allocated`), and a further over-settlement attempt is correctly
  rejected; plus a dedicated idempotent-retry test confirming a retried
  `cod-collect` call never inserts a second `CodCollection` row for the
  same payment.
- Updated `test_admin_cod_reconciliation.py`'s own COD-collection test
  fixture to also create a matching `CodCollection` row (previously it
  bypassed `collect_cod_payment()` entirely and only mutated `Payment`
  directly) — a small fixture correction, not a behavioral change to any
  existing assertion — plus one new assertion on the existing settle
  test confirming its response's `allocations` sums to the settled
  amount. All 18 tests in that file still pass unchanged otherwise.
  Full backend suite: **1194 passed, 10 skipped, 0 failed** (baseline
  1192 + 2 new) — no regressions.
- Migration round-trip (`alembic downgrade -1` / `upgrade head`):
  clean, both directions.
- admin-web: `npx tsc --noEmit` clean, `npm run build` clean, full
  vitest suite 7/7 passing (unaffected by this phase — no existing test
  covers the COD Reconciliation page).

## Live verification (real dev server)
Registered a real customer, rider, restaurant owner, and admin, and
drove two real COD orders through the entire delivery lifecycle (accept
→ preparing → ready → rider accept → pickup → start → cod-collect →
complete) against the real Postgres database — never a mock. Then
settled ₹150 against the rider's real ₹200 outstanding balance (two
₹100 collections):
- The live response's `settlements[0].allocations` showed exactly
  ₹100.00 allocated to the first (older) order and ₹50.00 to the second
  (newer) order — genuine FIFO behavior, not something asserted only in
  an isolated unit test.
- Queried `cod_collections`/`cod_settlement_allocations` directly via
  `psql`: confirmed the first collection shows `collected=100.00,
  allocated=100.00` (fully discharged) and the second shows
  `collected=100.00, allocated=50.00` (half discharged) — matching the
  ₹50 still outstanding exactly.
- Confirmed the pre-existing backfill worked: two real COD collections
  from earlier phases' live-testing work (predating this migration) now
  each have their own `CodCollection` row.

All live test data cleaned up afterward (`psql`, FK-dependency order,
verified zero rows remaining).

## Known limitations
`CodSettlementAllocation` allocation order is strictly FIFO by
`collected_at` — an admin cannot currently choose to settle a
*specific* order's cash out of order (e.g. to close out one particular
delivery's books first); this wasn't asked for and FIFO is the more
defensible default (oldest cash accounted for first) absent a specific
reason to deviate. `PAYOUT`-type settlements (the platform paying a
rider their own earnings, a separate concern from COD debt) are
unaffected by any of this phase's changes — they were never linked to
`CodCollection` and still aren't, correctly, since they don't discharge
COD debt at all.
