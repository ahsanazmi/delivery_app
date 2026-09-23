# Phase 9 — COD Settlement

## Scope
Integrate COD with the existing Admin Portal. Track expected/collected/
settled/outstanding COD and settlement status:
`COD collected -> Rider ledger -> Settlement -> Admin reconciliation`.
Never simply overwrite a wallet balance — use ledger-style records.

## Finding
Already fully built and already wired end-to-end into the admin-web UI
(`admin-web/src/pages/CODReconciliation.tsx`) — verification only, no
code changes.

`app/services/admin_cod.py` + `/api/v1/admin/cod*`:

- **Collected COD** — summed fresh from `Payment` (`provider=COD`,
  `collected_by_rider_id` set).
- **Expected (settlement)** — what's currently owed = the collected total
  ("Expected settlement" in the UI).
- **Settled COD** — summed from `RiderSettlement` (`REMITTANCE` rows
  only).
- **Outstanding COD** — `collected - settled`, always derived, never
  stored.
- **Settlement status** — `PENDING`/`PARTIAL`/`SETTLED`, computed from
  the above.

`admin_settle_cod()` is strictly append-only: every settlement is a new
`RiderSettlement` INSERT — there is no balance column to overwrite. Row-
locks the rider (`with_for_update()`) before computing outstanding,
closing the double-settlement race two concurrent admin actions could
otherwise cause. Rejects over-settlement and settling with nothing
outstanding.

## Testing
`test_admin_cod_reconciliation.py` (18, including
`test_multiple_partial_settlements_accumulate_via_new_rows_never_overwritten`),
`test_cod_end_to_end.py::test_integration_cod_settlement_and_admin_reconciliation`,
`test_admin_financial_integration.py`, `test_financial_consistency.py` —
31/31 passing.

## Live verification
Drove the full suggested flow against the real dev server: rider
collected a real ₹300 COD order → admin saw `PENDING`,
`cod_collected=300.00`, `outstanding=300.00` → settled ₹150 → `PARTIAL`,
one ledger row → settled the remaining ₹150 → `SETTLED`, outstanding
`0.00`, **two independent ledger rows present, the first untouched** → a
further settlement attempt correctly rejected (409). 20/20 checks passed.
