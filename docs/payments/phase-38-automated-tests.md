# Phase 38 — Automated Tests

## Scope
Create/expand backend tests for: payment creation, payment amount
validation, payment verification, signature verification, webhook
verification, webhook idempotency, payment retry, refund, partial
refund, COD collection, COD settlement, authorization, IDOR, duplicate
payment, concurrency. Frontend tests where practical: checkout,
payment selection, payment success, payment failure, retry, payment
history, admin payment management.

## Method
This backend already carries 1232 passing tests accumulated across 37
phases, so the first step was a precise gap analysis — not "does a
file with a plausible name exist" — dispatched to an Explore subagent
against the ~30 existing payment-related test files, verdict per
topic: WELL COVERED (cite the exact tests) or GAP (the specific
missing scenario). New tests were written only for genuine gaps; nine
of the fifteen backend topics needed nothing at all.

## Backend gap analysis — verdicts

| # | Topic | Verdict |
|---|---|---|
| 1 | Payment creation | GAP: nonexistent order id — fixed |
| 2 | Amount validation | No genuine gap (zero-total orders are already blocked at cart validation, before a payment is ever reachable) |
| 3 | Payment verification | Well covered |
| 4 | Signature verification | GAP: missing signature field at `/verify` — fixed |
| 5 | Webhook verification | GAP: malformed body over the real HTTP endpoint with a *valid* signature — fixed |
| 6 | Webhook idempotency | Well covered |
| 7 | Payment retry | Well covered |
| 8 | Refund | Well covered |
| 9 | Partial refund | Well covered |
| 10 | COD collection | Well covered |
| 11 | COD settlement | Well covered |
| 12 | Authorization | Well covered (every role gate already has a dedicated test) |
| 13 | IDOR | No genuine gap on inspection — rider earnings/wallet have no by-id endpoint at all (list-only, always scoped to the caller), so a direct-object-reference probe doesn't apply there the way it does for payments |
| 14 | Duplicate payment | Well covered; strengthened further by the new real-concurrency test below |
| 15 | **Concurrency** | **GAP — the significant one.** Every existing "race" test in the suite is an explicitly sequential, deterministic simulation (each one's own docstring says so) because the shared SQLite test fixture (`StaticPool`, one physical connection) cannot host two independent concurrent transactions at all. Zero genuinely multi-threaded tests existed anywhere. Fixed. |

## The concurrency fix
New `backend/tests/test_payment_concurrency_real_threads.py`. Instead
of `:memory:` SQLite (which forces every session onto one shared
connection via `StaticPool`, making real concurrent transactions
impossible to host), it uses a **file-backed** SQLite database per
test, so each thread gets a genuinely separate connection and
transaction. `PRAGMA busy_timeout` lets a blocked writer wait instead
of erroring, and a `BEGIN IMMEDIATE` event listener makes each
transaction take SQLite's write lock at transaction start — the
closest a file-backed SQLite database can get to Postgres's real row
lock, and enough to genuinely exercise the app's own check-then-act
logic under real, non-deterministic thread interleaving rather than a
monkeypatched simulation.

Three tests, each converting an existing *sequential* simulation into
a *real* one:
1. **Duplicate payment creation** — 8 real threads race
   `create_payment_for_order()` for the same order; exactly one
   Payment row survives, every thread resolves to it, none raise.
2. **Concurrent refunds never exceed the captured amount** — two real
   threads each try to refund ₹70 of a ₹100 payment at once; exactly
   one is accepted, the total committed never exceeds ₹100. (Without
   the `BEGIN IMMEDIATE` fix, this test genuinely failed on the first
   run — both threads read the pre-refund total before either
   committed and both succeeded, over-refunding to ₹140 — confirming
   this is a real gap the existing sequential test couldn't catch.)
3. **Delivery accept race** — two real riders race
   `accept_delivery()` for the same order; exactly one is assigned,
   the other gets the real 409.

This does **not** replace this project's standing practice, going
back to Phase 21, of proving Postgres's specific
`SELECT ... FOR UPDATE` row-locking behavior via live verification
against the real dev database outside the automated suite — SQLite
has no row-level locking to exercise regardless of these fixes, and
the automated suite must never depend on network/live infrastructure
to pass (an existing rule already stated in `conftest.py`). What this
phase adds is a permanent, CI-safe, genuinely-threaded check that the
*application-level* invariants (unique constraints + IntegrityError
recovery, atomic conditional UPDATEs, check-then-act guarded by a
write lock) hold under real concurrent execution — closing the gap
between "proven once, live, by hand" and "verified on every run."

## Other backend additions
- `test_payment_api.py`: `test_create_payment_for_a_nonexistent_order_is_404_not_500`, `test_verify_rejects_a_request_missing_the_signature_field`.
- `test_payment_webhooks.py`: `test_http_endpoint_never_500s_on_a_genuinely_signed_but_malformed_body` — a real HMAC computed over genuinely malformed (non-JSON) bytes, through the actual HTTP endpoint, confirming signature verification runs before JSON parsing and a malformed-but-signed payload is a clean 200/`"invalid_json"`, never a 500.

## Frontend gap analysis and additions
Of the seven listed topics, checkout, payment selection, payment
success, payment failure, retry, and payment history were all already
thoroughly covered in `customer-mobile` (confirmed by direct
inspection of `checkout.razorpay.test.tsx`, `order-detail.payment-
retry.test.tsx`, `payments.screen.test.tsx` — the same three files
Phase 37 had just finished verifying/fixing). The one genuine gap:
**admin payment management** had only ever been tested at the
API-request-shape layer (`adminApi.test.ts`) — no test rendered the
actual `admin-web` Payments list or Payment details pages.

New:
- `admin-web/src/pages/Payments.test.tsx` — renders every required
  field (payment id, order, customer, amount, method, provider,
  status, provider reference, created/paid time, refund status),
  submits the filter form and confirms status/method/order-id/
  customer are sent as distinct params, empty-state, error-state, and
  a check that no Razorpay secret is ever rendered.
- `admin-web/src/pages/PaymentDetails.test.tsx` — renders every
  required detail field, a failed payment's specific failure reason,
  COD collection info, refund status, a secret-leak check, and the
  404 error state.

Two real RTL gotchas were hit and fixed while writing these: (1)
`PaymentDetails.tsx` renders the customer's name and email either
side of a `<br/>`, so no single DOM node's `textContent` is exactly
"Ravi Kumar" — `getByText` needs the surrounding container's text
checked instead; (2) `Payments.tsx`'s own status filter `<select>`
renders an `<option>PAID</option>`/`<option>PARTIALLY REFUNDED</option>`
etc., which collides with the identical text in the results table's
status pill — fixed by scoping those assertions to the table via
`within(screen.getByRole("table"))`.

## Files created
- `backend/tests/test_payment_concurrency_real_threads.py`
- `admin-web/src/pages/Payments.test.tsx`
- `admin-web/src/pages/PaymentDetails.test.tsx`
- `docs/payments/phase-38-automated-tests.md`

## Files modified
- `backend/tests/test_payment_api.py`
- `backend/tests/test_payment_webhooks.py`
- `docs/payments/README.md`

## Testing
- Backend: full `pytest` suite — **1238 passed, 10 skipped, 0 failed**
  (baseline 1232 + 6 new: 3 real-thread concurrency tests, nonexistent
  order id, missing signature field, malformed-but-signed webhook
  body). The 3 new real-thread tests were additionally run 5x
  consecutively in isolation with no flakiness observed before being
  folded into the full run. One unrelated, pre-existing flaky test
  (`test_admin_authentication.py::test_admin_with_a_tampered_token_is_rejected`
  — tampering only the JWT's last base64 character can occasionally
  land on a padding-bit boundary that doesn't change the decoded
  signature bytes) surfaced once and passed cleanly on every rerun;
  it predates this phase and is outside its scope (admin auth, not
  payments), so it was left as is.
- `admin-web`: full `vitest` suite — **4 test files, 19 tests, all
  passing** (was 6 failing before the two RTL-scoping fixes above).

## Live verification
None required — this phase adds automated test coverage only; no
application behavior changed except the test infrastructure itself
(the `BEGIN IMMEDIATE` fixture is test-only, not shipped code).

## Known limitations
The real-thread concurrency tests prove genuine multi-threaded
correctness of this app's own locking/idempotency code, but — being
SQLite-backed — cannot reproduce Postgres's specific row-level lock
implementation. That specific guarantee remains proven only via this
project's established live-verification practice against the real
dev database, as documented in every phase since Phase 21.
