# Phase 31 — Security Audit

## Scope
Test: Customer A → Payment of Customer B ❌; Rider → Payment APIs ❌
where unauthorized; Restaurant → Payment of another restaurant ❌;
Non-admin → Refund API ❌; Forged Razorpay signature ❌; Invalid webhook
signature ❌; Modified payment amount ❌; Modified order ID ❌;
Duplicate webhook ❌; Duplicate payment request ❌. Never expose:
RAZORPAY_KEY_SECRET, RAZORPAY_WEBHOOK_SECRET, JWT secrets, database
credentials.

## Method
A verification phase: ten named attack scenarios and four secret-leak
checks, each given its own explicit, unambiguous test, consolidated in
one new file (`tests/test_payment_security_audit.py`) even where
equivalent coverage already existed scattered across earlier phases'
own test files — so this phase's own list has a direct, auditable
1:1 mapping to test functions, not something inferred from other files'
incidental coverage. Backed by live verification against the real dev
server for the scenarios that matter most to prove against a genuine
running system, not just an in-memory test database.

## Result: all fourteen checks pass
Every one of the ten attack scenarios and four secret-exposure checks
was already correctly blocked/never-leaked by existing code from earlier
phases (14, 15, 17, 18, 21, 23, 26, 27, 28) — this audit found **no new
product-code gap**. One test-authoring bug was found and fixed while
writing the audit itself (a cross-session SQLAlchemy `refresh()` call in
the duplicate-webhook test, not a security issue).

| # | Scenario | Proven by | Result |
|---|---|---|---|
| 1 | Customer A → Payment of Customer B | `test_customer_a_cannot_access_customer_bs_payment` (GET/verify/retry/order-lookup, all 404) | ❌ Blocked |
| 2 | Rider → Payment APIs, unauthorized | `test_rider_cannot_access_any_payment_api` (8 endpoints, all 403) | ❌ Blocked |
| 3 | Restaurant → another restaurant's payment info | `test_restaurant_owner_cannot_see_another_restaurants_order_payment_info` (404) | ❌ Blocked |
| 4 | Non-admin → Refund API | `test_non_admin_cannot_call_the_refund_api` (customer/rider/owner all 403, unauthenticated 401) | ❌ Blocked |
| 5 | Forged Razorpay signature | `test_forged_razorpay_signature_is_rejected` (rejected, payment stays FAILED) | ❌ Blocked |
| 6 | Invalid webhook signature | `test_invalid_webhook_signature_is_rejected` (forged → 400, missing → 400, nothing recorded) | ❌ Blocked |
| 7 | Modified payment amount | `test_modified_payment_amount_is_rejected` (provider-confirmed amount mismatch rejected) | ❌ Blocked |
| 8 | Modified order ID | `test_modified_order_id_is_rejected` (a genuinely-signed but wrong order_id rejected) | ❌ Blocked |
| 9 | Duplicate webhook | `test_duplicate_webhook_is_processed_once` (same event_id twice → one WebhookEvent row, no re-mutation) | ❌ Blocked |
| 10 | Duplicate payment request | `test_duplicate_payment_creation_request_never_creates_two_payment_rows` (double-tap → same row returned) | ❌ Blocked |
| — | RAZORPAY_KEY_SECRET exposure | `test_razorpay_key_secret_never_appears_in_any_payment_response` (5 response bodies grepped) | Never exposed |
| — | RAZORPAY_WEBHOOK_SECRET exposure | `test_razorpay_webhook_secret_never_appears_in_any_response` (forged + missing-signature responses grepped) | Never exposed |
| — | JWT secret exposure | `test_jwt_secret_never_appears_in_any_response` (4 response bodies, including a failed login, grepped) | Never exposed |
| — | Database credentials exposure | `test_database_credentials_never_appear_in_any_response` (including a 404-on-missing-payment response) | Never exposed |

## Why each scenario was already blocked
- **1/2/3 (cross-account access)** — every payment-adjacent endpoint
  scopes its query by the authenticated principal (`current_user.id`,
  `current_rider.id`, `restaurant.id` resolved from the owner's own
  token) at the database-query level, not a post-hoc check — and
  consistently returns 404 rather than 403 for another account's
  resource, so an attacker can't even learn whether a given id exists
  (Phases 5, 22, 27, 28's own established convention). Role gates
  (`require_customer`/`require_rider`/`require_admin`/
  `require_roles(RESTAURANT_OWNER)`) additionally reject the wrong
  principal type before any ownership check even runs.
- **4 (refund)** — `POST /admin/payments/{id}/refund` has only ever had
  one gate, `require_admin` (Phase 23), never a second, looser path.
- **5/7/8 (signature/amount/order-id forgery)** — Payment Signature
  Verification (Phase 14) and Payment Amount Validation (Phase 15) both
  run three independent checks in `PaymentService.verify_payment()`:
  the provider's own reported order_id must match this payment's, the
  HMAC signature must be genuine, and the provider-confirmed amount must
  match the order's own total — any one failing rejects the whole
  verification and leaves the payment `FAILED`, never `PAID`.
- **6/9 (webhook signature/duplicate)** — Payment Webhooks (Phase 17)
  verifies the HMAC signature before any parsing happens at all;
  Webhook Idempotency (Phase 18) checks `x-razorpay-event-id` against
  `WebhookEvent` before any Payment/Order mutation, backed by a real
  unique constraint for the genuinely-concurrent-delivery race.
- **10 (duplicate payment creation)** — Idempotent Order Payment
  Creation (Phase 21): a find-or-create check plus
  `uq_payments_order_id` (database-level) together make a second
  request for the same order return the same row, never a second one.
- **Secrets** — `RAZORPAY_KEY_SECRET`/`RAZORPAY_WEBHOOK_SECRET` are only
  ever read server-side for verification math, never serialized into
  any response schema (only the public `RAZORPAY_KEY_ID` is, and only
  to the customer's own checkout flow). `JWT_SECRET_KEY` never appears
  in any response body — session tokens are signed with it, never
  echoed back. `DATABASE_URL` is never referenced outside
  `app/core/config.py`/`app/db/session.py`, and the generic
  unhandled-exception handler (`test_security.py`, pre-existing) already
  returns a fixed, generic 500 body, never a stack trace or connection
  string.

## Files created
- `backend/tests/test_payment_security_audit.py`
- `docs/payments/phase-31-security-audit.md`

## Testing
- New: 14 tests, all passing. Full backend suite: **1208 passed, 10
  skipped, 0 failed** (baseline 1194 + 14 new) — no regressions.

## Live verification (real dev server)
Registered real customers, a real rider, and drove the actual HTTP
endpoints against real Postgres — not just the in-memory test database:
- A real customer's own `/customer/payments` correctly scoped (empty
  list for a brand-new account, never another account's data).
- A real rider token → `403` on `/customer/payments`, `/admin/payments`,
  `/admin/cod`.
- A non-admin token → `403` on the refund endpoint.
- An unsigned/forged webhook request → `400`/`503` (honestly rejected;
  `503` specifically because this dev environment has no
  `RAZORPAY_WEBHOOK_SECRET` configured at all, the same documented
  limitation every webhook-touching phase since 17 has noted — an
  honest "can't verify" refusal, never a silent accept).
- Grepped a real response body for a Postgres-connection-string-looking
  substring: none found.

All live test data (three registered users, no orders/payments created)
cleaned up afterward.

## Known limitations
This audit exercises the backend API surface exhaustively but does not
re-verify browser/mobile-client-side secret handling (e.g. that
`customer-mobile`/`business-web`/`admin-web` never log a bearer token to
device console output) — out of this phase's own stated scope, which
names specific server-side secrets and specific API-level attack
scenarios only.
