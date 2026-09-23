# Testing Summary — Say Hi Chai

This document records every testing effort performed under **Protocol B — End-to-End Integration & System Validation** (Phases 15–29), the phase-by-phase backend/security/quality/performance audit that preceded final system validation (Phase 31). It exists so a reviewer can see what was tested, how, and where the results live, without re-reading every phase's own completion report.

## How to run everything

```bash
# Backend — full suite (SQLite, ~5 minutes, 1029 tests)
cd backend && source .venv/bin/activate && python -m pytest -q

# Backend — the two permanent E2E flows specifically
python -m pytest -q tests/test_e2e_happy_path.py tests/test_e2e_failure_paths.py -v

# Frontend — each app has its own test runner
cd business-web && npm test        # Vitest, 11 tests
cd admin-web && npm test           # Vitest, 6 tests
cd customer-mobile && npm test     # Jest + jest-expo, 9 tests
cd rider-mobile && npm test        # Jest + jest-expo, 8 tests
```

## Backend automated test suite

**1029 tests, 10 intentional skips (self-pair cases in the transition matrix), 0 failures**, spread across ~140 test files under `backend/tests/`. Built incrementally across every phase below; each phase's own tests remain in the suite and run on every future session.

| Category | Representative files | What's covered |
|---|---|---|
| Authentication | `test_security.py`, `test_rider_auth.py`, `test_logging.py` | Login/register/refresh, expired/forged/malformed tokens, password hashing, JWT algorithm pinning, production config guards (JWT secret, DEBUG) |
| Authorization / role isolation | `test_security_idor_final_sweep.py`, `test_rider_security_audit.py`, `test_restaurant_security_audit.py` | Every role boundary (customer/rider/owner/admin), a forged `role` claim in an otherwise-valid JWT is never trusted (role is always re-read from the DB) |
| Customer ordering | `test_customer_orders.py`, `test_customer_checkout.py`, `test_integration_customer_restaurant_order_flow.py` | Cart, checkout validation, order placement, cancellation, reorder |
| Restaurant lifecycle | 18 files under `test_restaurant_*.py` | Menu/category/product CRUD, order accept/reject/preparing/ready, operating hours, dashboard |
| Rider assignment | `test_rider_accept_reject_delivery.py`, `test_rider_assignment_state_machine.py` | Accept/reject/arrived/pickup/start/complete, the full `DeliveryAssignment` state machine |
| Order transitions | `test_order_transition_matrix.py` (Phase 27) | **Exhaustive**: every one of the 10×10 `OrderStatus` pair combinations, asserting `transition_order_status()` allows a move if and only if `VALID_TRANSITIONS` says so |
| Payments | `test_customer_payments.py`, `test_admin_payments.py` | Signature verification success/failure, retry-after-failure on the same payment row, idempotent payment-record creation |
| COD | `test_cod_flow.py`, `test_cod_end_to_end.py`, `test_rider_cod_collection.py`, `test_admin_cod_reconciliation.py` | Collection, settlement, over-settlement rejection, the Phase 24 concurrent-double-settlement fix |
| Admin actions | `test_admin_intervention_audit_coverage.py`, `test_admin_riders.py`, `test_admin_restaurants.py` | Every named intervention (order cancel, restaurant/rider approve/suspend, COD settle) produces exactly one audit-log entry with the correct admin id and reason |
| Concurrency | `test_rider_concurrency_and_failure_handling.py`, `test_rider_performance.py`, plus live threaded proofs (see below) | Double place-order, double rider-accept, double delivery-complete, double COD-settle — deterministic SQLite reproductions plus genuinely threaded live proofs against Postgres |
| IDOR | `test_security_idor_final_sweep.py` | Cross-customer, cross-rider, cross-restaurant, admin-only-API-vs-every-other-role, modified request body can't reassign ownership |
| Logging & error handling | `test_logging.py` | One test per failure category (auth, authz, order, payment, assignment conflict, COD, admin action, unexpected exception) proving both that a log record is produced *and* that no password/token/secret ever appears in it |
| Performance | `test_rider_performance.py`, `test_customer_orders.py`, plus direct query-count assertions | N+1 fixes verified by asserting a fixed, non-scaling query count (not wall-clock timing) |
| Complete happy path (Phase 28) | `test_e2e_happy_path.py` | All 24 named steps, customer → restaurant → rider → delivered, financial consistency checked at the end |
| Complete failure paths (Phase 29) | `test_e2e_failure_paths.py` | All 11 named failure scenarios, each checked from every affected role's own view |

## Frontend automated tests (new in Phase 27)

No frontend test infrastructure existed before Phase 27. All four apps now have a working test runner and real, passing tests.

| App | Runner | Tests | Covers |
|---|---|---|---|
| `business-web` | Vitest + React Testing Library | 11 | Protected routes / role routing (`RestaurantOwnerRoute`), critical API integration (`apiClient`), restaurant order management (`Orders` page) |
| `admin-web` | Vitest + RTL | 6 | Protected routes / role routing (`AdminRoute`), admin actions (exact request shape sent for rider approval and COD settlement) |
| `customer-mobile` | Jest + jest-expo + RNTL | 9 | Protected routes (`profile` screen redirect), order screens (`orders` list), critical API integration |
| `rider-mobile` | Jest + jest-expo + RNTL | 8 | Protected routes + role routing (rider group layout), rider delivery flow (`delivery/[id]` screen actions), critical API integration (including the app's GET-retry-on-network-failure behavior) |

A real dependency conflict was found and fixed while setting this up: `@testing-library/react-native@14.x`'s bundled renderer requires React ≥19.3.0, but both mobile apps are pinned to React 19.2.3 (an Expo SDK 57 constraint) — pinned to `@testing-library/react-native@13.3.3` instead, which resolves cleanly.

## Live proofs against the real backend

Several classes of bug are only observable against a real, genuinely concurrent Postgres backend — SQLite's single-writer model can't demonstrate them. Each of these was proved live (seed real data via script, fire real simultaneous HTTP requests via `httpx` + `threading.Barrier`, verify the outcome, clean up the data afterward) at least once, in addition to a deterministic SQLite reproduction kept in the permanent suite:

- Two simultaneous "place order" calls for the same cart → exactly one order (Phase 16, re-verified Phase 24 after a structural fix)
- Two simultaneous rider-accept calls for the same delivery → exactly one winner (Phase 16, re-verified Phase 24)
- Two simultaneous "complete delivery" calls → exactly one `RiderEarning` row, not a double credit (Phase 24 — a genuine bug found and fixed)
- Two simultaneous admin COD-settlement calls → never settles more than was actually outstanding (Phase 24 — a genuine bug found and fixed)
- The complete 24-step happy path (Phase 28) — every step through the real endpoint each portal's frontend actually calls
- All 11 failure-path scenarios (Phase 29) — 43 checks, each verified from every affected role's own view

## Bugs found and fixed during this testing effort

These were genuine defects discovered *because* of this testing work, not pre-existing known issues:

1. **`create_order()` atomicity** (Phase 24) — a premature commit inside the Phase 16 concurrency fix could leave a cart permanently unusable if anything failed later in the same request.
2. **`transition_order_status()` race** (Phase 24) — no guard against two genuinely concurrent transitions of the same order; live-proved to double-credit a rider's delivery-fee earning. Fixed with the same atomic conditional-`UPDATE` pattern already used elsewhere in the codebase.
3. **`admin_settle_cod()` race** (Phase 24) — no guard against two concurrent settlements together exceeding what was actually outstanding. Fixed with a `SELECT ... FOR UPDATE` row lock.
4. **Missing composite indexes** on `orders` for `(restaurant_id, created_at)` and `(status, created_at)` (Phase 25) — used by "Restaurant orders", the admin dashboard, and every admin report.
5. **N+1 queries** in the customer order list and the legacy rider order list (Phase 25) — both eager-loaded now.
6. **Unpaginated queries** in the legacy rider order list and the available-deliveries list (Phase 25) — both capped.
7. **Zero backend logging infrastructure** (Phase 26) — no logging existed at all before this phase; added a global exception handler and category-specific logging for every named failure type, verified to never log a password/token/secret.
8. **`.env.development` files not gitignored** in the two mobile apps (Phase 31) — no secret was ever actually committed, but the exposure path existed; closed.

## What's intentionally *not* covered

Documented, deliberate scope exclusions (each was an explicit judgment call, not an oversight):

- **Stuck order after a rider is suspended mid-delivery** (Phase 15) — a rider suspended after `PICKED_UP` leaves that order permanently unprogressable through any existing endpoint. The user explicitly chose "document only" over building a recovery mechanism.
- **No restaurant-facing notification channel** (Phase 15) — same "document only" decision.
- **No server-side token revocation** — logout is client-side only; mitigated by a 15-minute access-token lifetime. Not flagged as a defect, since this is a common, deliberate tradeoff, but worth knowing before scaling to a threat model that requires instant revocation.
