# Phase 29 — Rider Payment/COD Visibility

## Scope
Rider should see only: Delivery earning, COD amount to collect, COD
collected status, Settlement information relevant to rider. Rider must
never see: Razorpay secret, another rider's financial information,
another restaurant's financial information, customer payment
credentials.

## What was found
This phase's entire "must show" list and all four "must never show"
constraints were already correctly built at the backend, and mostly
wired up in `rider-mobile` already, from earlier (separate) rider-portal
phases:

- **Delivery earning** — `GET /api/v1/rider/earnings/summary`
  (Today/Week/Month totals + a delivery_fee/incentive/bonus/adjustment
  breakdown) and `GET /api/v1/rider/dashboard`'s `today_earnings`, both
  already rendered on `rider-mobile`'s dedicated `earnings.tsx` and
  `index.tsx` (dashboard) screens.
- **COD amount to collect / COD collected status** —
  `RiderDeliveryDetailRead.cod_amount`/`is_paid` (`GET
  /rider/deliveries/{id}`) and the dedicated `CodCollectionRead` response
  from `POST /deliveries/{id}/cod-collect`, both already fully wired into
  `delivery/[id].tsx` — an amber "Cash to Collect" box, a confirmation
  alert quoting the exact amount, a "✓ Cash Collected" badge, and
  "MARK DELIVERED" disabled until COD is actually collected.
- **Scoping / the three "never see" data-isolation constraints** — every
  route under `app/api/v1/rider/` uses `require_rider` (JWT-derived,
  never a client-supplied id) and every service function additionally
  re-filters by `rider_id`/`rider.id` at the query level. No endpoint
  anywhere takes a rider_id/user_id path or query parameter at all. No
  rider response schema anywhere serializes a `Payment` ORM object or its
  `razorpay_*` fields, and no rider schema touches a restaurant's own
  commission/earning fields (those live only on
  `RestaurantOrderListItem`/`RestaurantOrderDetailRead`, from Phase 28,
  never returned to a rider).

**The one genuine gap**: "Settlement information relevant to rider" was
only partially visible. `GET /api/v1/rider/wallet` already surfaced the
two summary figures (`settlement_due`, `total_settled`) on the wallet
screen, but the real, itemized settlement history — `GET
/rider/wallet/settlements` (`RiderSettlementRead`: type, amount, note,
date) — had a working backend endpoint **and** a working frontend API
function (`walletApi.ts::listRiderSettlements`) that no screen actually
called. A rider could see *how much* was due/settled, but never the
individual PAYOUT/REMITTANCE events behind those totals.

## What was built
Entirely frontend — no backend model, schema, or endpoint needed
changing; the correct, already-scoped endpoint just needed a UI.

- `rider-mobile/services/api/walletApi.ts::listRiderSettlements` — added
  `page`/`limit` options (the backend endpoint already accepted them;
  the frontend function simply never passed any).
- `rider-mobile/app/(rider)/wallet.tsx` — new "Settlement history"
  section below the existing summary cards: each settlement shown as its
  type ("Paid out to you" / "Remitted to platform"), a signed amount
  (`+`/`-`), the date, and its note if any — paginated with the same
  load-first-page / Load More pattern `history.tsx` already established.
  Pull-to-refresh now reloads both the wallet summary and the settlement
  list together.
- `rider-mobile/services/api/deliveriesApi.ts::CodCollection.payment_status` —
  widened to match the backend's full `PaymentStatus` enum (was missing
  `processing`/`cancelled`/`partially_refunded`). Not currently
  reachable (`collect_cod_payment()` only ever returns `paid`), but this
  is literally the type for "COD collected status" — one of this phase's
  four required fields — so it was worth tightening while in this file,
  rather than leaving a type that would silently go stale if that ever
  changes.

### Explicitly not built
An itemized, per-delivery earnings ledger screen (`GET /rider/earnings` +
`earningsApi.ts::listRiderEarnings`, also already built and unused). The
phase's own wording is "Delivery earning" — already fully and adequately
shown via the existing Today/Week/Month summary + type breakdown on
`earnings.tsx`. Adding a second, raw-ledger view wasn't asked for and
would be scope creep beyond what this phase's field list names.

## Files modified
- `rider-mobile/services/api/walletApi.ts`
- `rider-mobile/services/api/deliveriesApi.ts`
- `rider-mobile/app/(rider)/wallet.tsx`

## Files created
- `rider-mobile/app/__tests__/wallet.settlements.test.tsx`
- `docs/payments/phase-29-rider-payment-cod-visibility.md`

## Testing
- rider-mobile: 4 new tests in `wallet.settlements.test.tsx` (renders
  each settlement's type/amount/date/note; empty state when there are
  none yet; the backend's own error message surfaced, not a crash; a
  regression guard confirming the screen makes exactly the two calls it
  should, nothing broader that could pull in unrelated data). Full
  rider-mobile suite: 12/12 passing (8 pre-existing + 4 new).
  `npx tsc --noEmit`: clean.
- Backend: unchanged, so no new backend tests — the existing rider
  scoping/authorization test coverage (confirmed via the research pass
  behind this phase, not re-audited here) already covers the endpoint
  this phase's UI now actually uses.

## Live verification (real dev server)
Seeded two real riders directly via the service layer, each with their
own real `RiderSettlement` rows, then drove the real HTTP endpoint:
- Rider A's own token → exactly Rider A's 2 settlements (PAYOUT 500,
  REMITTANCE 120) — never Rider B's.
- Rider B's own token → exactly Rider B's 1 settlement (PAYOUT 999) —
  never Rider A's. Confirms the "another rider's financial information"
  constraint holds against genuinely different riders, not just a mocked
  test.
- `?page=1&limit=1` → exactly 1 row, confirming pagination works
  end-to-end against the real database.
- Unauthenticated request → `401`.

All live test data cleaned up afterward (`psql`, verified zero rows
remaining).

## Known limitations
The itemized earnings ledger (`GET /rider/earnings`) remains unused by
any rider-mobile screen — a deliberate scope decision (see above), not
an oversight; the endpoint and its frontend API function both already
exist and are ready to wire up in a future phase if a per-delivery
earnings breakdown is wanted beyond the current daily/weekly/monthly
summary.
