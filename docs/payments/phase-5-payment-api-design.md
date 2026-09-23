# Phase 5 — Payment API Design

## Scope
Create/verify APIs under `/api/v1/payments/*`: create, get by id, verify,
retry, get by order. Every endpoint must authenticate, verify order
ownership, verify payment state, validate amount server-side, and return a
safe response — Customer A must never access Customer B's payment.

## What was built
Rewrote `app/api/v1/endpoints/payments.py` on the Phase 4 `PaymentService`:

```
POST /create               body {order_id, method}; idempotent; 503/502 on provider errors
GET  /{payment_id}         payment ownership via payment.user_id
POST /{payment_id}/verify  rejects non-razorpay (400) and non-verifiable state (409) before calling the provider
POST /{payment_id}/retry   reopens the SAME provider order, no new HTTP call
GET  /order/{order_id}     order ownership checked before the payment lookup even happens
```

`POST /webhook` and the legacy `POST /{payment_id}/refund` were kept
unchanged (out of this phase's scope — the refund endpoint's missing
guard is a known, flagged gap). The old, generic `POST /api/v1/payments`
(where the client picked the provider) was retired after confirming via
grep across all four frontends that nothing used it.

`PaymentService.retry_payment` and `verify_payment`'s admin/customer
failure notifications (`notify_admins`, `notify_customer_payment_failed`)
were added in this phase — porting behavior the old, pre-Phase-4 service
had that the new one hadn't picked up yet, avoiding a silent regression of
already-tested Phase 20 behavior.

## Real credentials
The user supplied real Razorpay TEST-mode API keys, loaded into
`backend/.env` (never committed). `tests/conftest.py` force-clears
`RAZORPAY_KEY_ID`/`SECRET`/`WEBHOOK_SECRET` at import time so the
automated suite stays hermetic regardless of the developer's local
`.env`.

**Production Payment Readiness (Phase 40) — correction**: this
section originally quoted the actual `key_id` in plaintext and
referenced a `rzp-test-key.csv` file it claimed was gitignored. That
file was in fact already tracked by git at the time `.gitignore` was
updated to list it (the ignore rule has no retroactive effect on an
already-committed file), so a real, working Razorpay test-mode
key/secret pair was live in this repository's history. The CSV file
has been removed from the tracked tree and the real value redacted
from this doc, but the key/secret pair itself remains permanently
recoverable from this repository's git history at commit `c07d240d1`
regardless — **it must still be rotated in the Razorpay dashboard**
(this was not done as part of this phase; it requires dashboard
access this environment doesn't have). Never paste a real credential
value into a committed file again, `.gitignore`'d or not — a
gitignore rule only stops a *future* `git add`, never one that
already happened.

## Testing
`tests/test_payment_api.py` (19 tests) — every endpoint's auth/ownership/
state/amount/safe-response requirements, including explicit
`test_customer_a_cannot_access_customer_bs_payment` and equivalents for
verify/retry/order-lookup.

## Live verification
Ran the real create → verify flow against the real running dev server and
the real Razorpay test API: a genuine `order_...` id was returned, an
HMAC-genuine signature verified successfully, and every cross-customer
IDOR attempt (get/verify another customer's payment) correctly 404'd.

## Bugs found and fixed in this phase
- `RazorpayProvider` was caching credentials at `__init__` time — fixed by
  converting them to lazy properties (see Phase 4 doc).
- The new `PaymentService.verify_payment` was missing the
  failure-notification calls the old service had — added.
