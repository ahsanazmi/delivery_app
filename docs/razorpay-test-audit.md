# Razorpay Test Mode — Phase 1: Implementation Audit

| | |
|---|---|
| **Phase** | 1 of 38 — Razorpay Implementation Audit (inspection only) |
| **Date** | 2026-10-06 |
| **Code audited** | `main` @ `5b19ccb58` (also what Render currently runs) |
| **Code changes in this phase** | None |
| **Secrets** | None printed or recorded. Key ID shown only as `rzp_test_***`. |

This audit inventories the existing Razorpay implementation as it stands, ahead of
the hands-on testing phases (2–38). It does not redesign anything. Every
"potential problem" below is a hypothesis for a later phase to confirm or rule out
against a real Razorpay Test Mode account.

---

## 1. Summary

The implementation is mature and was built in 40 earlier phases (`docs/payments/`).
The backend owns every amount, status and verification decision; the mobile app
only opens Razorpay Checkout and reports the result back. Signature checks use
constant-time HMAC, the webhook is signature-gated before any parsing, and
idempotency is enforced with database unique constraints rather than application
checks alone. Razorpay and COD share the `Payment` table but take separate code
paths.

**Baseline tests:** 289 backend payment tests pass and 16 mobile payment tests pass.
All of them run against mocked Razorpay; none has ever exercised a real Razorpay
Test Mode account. That's the main thing the later phases add.

**Top risks to confirm in later phases:**

1. **Production already returned a 502 on payment creation today** (order
   `1c793bcf…`, 08:45 UTC), and the backend doesn't log Razorpay's actual error, so
   the cause can't be determined from Render logs. → Phases 3/4/36.
2. **Webhook configuration is unverified**, and recovery from several failure modes
   depends on it (§6, P1–P3). `RAZORPAY_WEBHOOK_SECRET` is **missing from the local
   `.env`**. → Phases 2/17.
3. **Manual-capture accounts would break verification**: a payment that's only
   `authorized` is marked FAILED and the customer is told it failed. → Phases 11/20.

---

## 2. Architecture as implemented

```text
Customer Mobile (react-native-razorpay)
   │ 1. POST /api/v1/customer/orders                  → Order (payment_method="razorpay")
   │ 2. POST /api/v1/customer/orders/{id}/payment     → Payment + Razorpay Order (server amount)
   │ 3. RazorpayCheckout.open({key, order_id})        → razorpay_payment_id + signature
   │ 4. POST /api/v1/payments/{payment_id}/verify     → HMAC + fetch payment + fetch order
   │ 5. GET  /api/v1/payments/{payment_id}            → authoritative status shown to user
   ▼
FastAPI ── PaymentService ── PaymentProvider (ABC) ── RazorpayProvider (httpx → api.razorpay.com/v1)
   ▲
   └── POST /api/v1/payments/webhooks/razorpay  (HMAC-verified → webhook_service → WebhookEvent log)
```

### 2.1 Backend components

| Component | File | Role |
|---|---|---|
| `PaymentProvider` (ABC) + `ProviderOrder/Payment/Refund` | [backend/app/services/payment/provider.py](../backend/app/services/payment/provider.py) | Provider-agnostic interface; no Razorpay JSON leaks past it |
| `RazorpayProvider` | [backend/app/services/payment/razorpay_provider.py](../backend/app/services/payment/razorpay_provider.py) | Only file that knows Razorpay's REST API. Uses `httpx` directly, with no SDK. Basic auth with key id and secret, 10 s timeout. Converts amounts to and from paise with `Decimal` + `ROUND_HALF_UP`. |
| `verify_hmac_signature` | [backend/app/services/payment/verification.py](../backend/app/services/payment/verification.py) | HMAC-SHA256 + `hmac.compare_digest`. Returns False when the signature or secret is empty. |
| `PaymentService` | [backend/app/services/payment/payment_service.py](../backend/app/services/payment/payment_service.py) | `create_payment_for_order`, `verify_payment`, `retry_payment`, `refund` |
| `refund_service` | [backend/app/services/payment/refund_service.py](../backend/app/services/payment/refund_service.py) | Row-locked refund creation; tracks the remaining refundable amount |
| `webhook_service` | [backend/app/services/payment/webhook_service.py](../backend/app/services/payment/webhook_service.py) | Handles `payment.captured`, `payment.failed`, `refund.processed`, `refund.failed`; logs every event |
| Typed errors | [backend/app/services/payment/exceptions.py](../backend/app/services/payment/exceptions.py) | `ProviderNotConfigured` → 503, `ProviderRequest` → 502, `PaymentVerification` → 400, `PaymentExpired` → 410, `RefundError` |
| Legacy module | [backend/app/services/payments.py](../backend/app/services/payments.py) | Payment-method list, customer history, `record_order_payment` (used by mobile). Also contains a **legacy signature-only `verify_payment` that no route uses** (see P8). |

### 2.2 Data model

| Model | Key fields / constraints |
|---|---|
| `Order` | `payment_method` (`cod`/`razorpay`), `payment_status` (string), `is_paid`, `total` (Numeric) |
| `Payment` | **unique `order_id`** (one payment per order); unique `(provider, razorpay_order_id)` and `(provider, razorpay_payment_id)`; `amount Numeric(10,2) ≥ 0`; `currency` default `INR`; `payment_status` enum; `is_verified`; `paid_at`; COD fields `collected_by_rider_id`, `collected_at` |
| `PaymentStatus` enum | `pending, processing, paid, failed, cancelled, refund_pending, partially_refunded, refunded` |
| `PaymentAttempt` | one row per attempt; unique `(provider, provider_payment_id)`; `status`, `failure_code`, `failure_message`; `amount` is Numeric |
| `Refund` | many per payment; unique `provider_refund_id`; status `pending/processing/completed/failed`; `amount` is Numeric; `reason` |
| `WebhookEvent` | append-only audit log; unique `(provider, event_id)` from the `x-razorpay-event-id` header; `outcome`; raw `payload` |
| COD / settlement | `CodCollection`, `CodSettlementAllocation`, `RiderSettlement`: separate tables, no Razorpay references |

**Money handling:** every amount column is `Numeric`, every service uses `Decimal`,
and paise conversion is `int((amount*100).quantize(1, ROUND_HALF_UP))`. The one
float is on the mobile side, `Math.round(amount*100)`, which is display-only
because Razorpay charges the amount stored on the order (§2.4).

### 2.3 Endpoints

| Method & path | Auth | Purpose | Client-supplied inputs |
|---|---|---|---|
| `GET /api/v1/customer/payment-methods` | customer | COD always; "online" available only if key id + secret are set | none |
| `POST /api/v1/customer/orders/{order_id}/payment` | customer (owner) | **Mobile's entry point.** Creates the Payment and Razorpay Order idempotently. Method comes from `order.payment_method`. | `order_id` only |
| `POST /api/v1/payments/create` | customer (owner) | Generic create (not used by mobile) | `order_id`, **`method`** (see P9) |
| `GET /api/v1/payments/{payment_id}` | customer (owner) | Status | path id |
| `GET /api/v1/payments/order/{order_id}` | customer (owner) | Status by order | path id |
| `POST /api/v1/payments/{payment_id}/verify` | customer (owner) | Signature + provider re-fetch + amount/currency/capture checks | `provider_order_id`, `provider_payment_id`, `signature` |
| `POST /api/v1/payments/{payment_id}/retry` | customer (owner) | Re-opens a FAILED/PENDING payment on the **same** Razorpay order within 30 min | path id |
| `POST /api/v1/payments/webhooks/razorpay` | HMAC signature (no JWT) | Webhook | raw body, `x-razorpay-signature`, `x-razorpay-event-id` |
| `GET /api/v1/customer/payments` | customer | Own payment history (paginated) | page, limit |
| `GET /api/v1/admin/payments`, `GET …/{id}` | admin | List/detail with filters | filters |
| `POST /api/v1/admin/payments/{id}/refund` | admin | Refund (full/partial); `amount: Decimal > 0`, `reason` required | amount, reason |

Ownership is checked on every customer route through `_get_owned_order_or_404` /
`_get_owned_payment_or_404`. Another customer's resource returns 404, not 403, so
it doesn't reveal that the resource exists.

### 2.4 Customer mobile integration

* [customer-mobile/features/payments/razorpay-flow.ts](../customer-mobile/features/payments/razorpay-flow.ts):
  opens Checkout with the **server-provided** `key_id` + `order_id`, sends
  `{order_id, payment_id, signature}` to `/verify`, then **re-reads the payment
  from the server** and reports only what the backend says (`paid`, `failed`,
  `pending` or `unknown`). Checkout success alone never shows "paid".
* [customer-mobile/app/checkout.tsx](../customer-mobile/app/checkout.tsx): the
  order is created first. If payment initialisation fails, the customer sees
  "Order placed… retry payment from your order" and is never told to place a
  second order.
* [customer-mobile/app/orders/[id].tsx](../customer-mobile/app/orders/[id].tsx): retry payment.
* Native module: `react-native-razorpay ^3.0.0` (needs a dev/release build, not Expo Go).
* Amount sent to Checkout: `Math.round(payment.amount * 100)` from the server
  response. It's informational, since the Razorpay `order_id` fixes the amount.

### 2.5 Verification logic (`PaymentService.verify_payment`)

All of these must pass before the payment is marked `paid`:

1. `provider_order_id == payment.razorpay_order_id` → else `ORDER_MISMATCH`
2. Payment not older than **30 min** → else `PAYMENT_EXPIRED` (410, marked FAILED)
3. HMAC of `order_id|payment_id` with the key secret → else `SIGNATURE_MISMATCH`
4. `fetch_payment` + `fetch_order` from Razorpay (unreachable → `PROVIDER_UNREACHABLE`, 502, status left unchanged)
5. The fetched payment's `order_id` matches → else `ORDER_MISMATCH`
6. The fetched payment's status is **`captured`** → else `PAYMENT_NOT_CAPTURED`
7. The fetched payment and order amounts equal `payment.amount` → else `AMOUNT_MISMATCH`
8. The fetched currencies equal `payment.currency` → else `CURRENCY_MISMATCH`

On success, if the order is already CANCELLED or REJECTED, the payment becomes
`refund_pending` and admins are alerted. Otherwise the payment becomes `paid`, the
order gets `is_paid=True`, and the restaurant and customer are notified. Every
call writes a `PaymentAttempt`. A reused `provider_payment_id` is caught by the
unique constraint.

### 2.6 Webhook logic

* The endpoint rejects a missing signature (400), returns 503 if no webhook secret
  is configured, and rejects an invalid HMAC over the **raw body** (400). Only
  then is the body parsed.
* Idempotency: an existing `WebhookEvent` with the same `event_id` is returned
  without reprocessing, and a race is caught by the unique constraint.
* `payment.captured`: amount and currency are checked against the Payment. A
  payment that's already `paid` is logged `duplicate_ignored`. An order that's
  already dead goes to `refund_pending`.
* `payment.failed`: marks FAILED unless the payment is already `paid`
  (`ignored_already_paid`).
* `refund.processed` / `refund.failed`: update the Refund and recompute the
  payment's refund status.
* Any other event is recorded as `unhandled_event_type`. That includes
  **`payment.authorized`** and **`order.paid`**.

### 2.7 Refund logic

The Payment row is locked with `SELECT … FOR UPDATE`. Refunds are allowed only
from `paid` or `partially_refunded`, and the amount must be greater than 0 and no
more than `payment.amount − Σ(completed + processing refunds)`. A Razorpay refund
whose status is `processed` is marked completed, `failed` is marked failed, and
anything else is marked processing and finished later by webhook. COD refunds
(no provider) complete immediately. Only admins can refund, and the reason is
required.

### 2.8 COD and Razorpay separation

* COD gets a Payment row with `provider=COD`, no Razorpay call and no Razorpay
  IDs. Cash collection is a rider-only endpoint and refuses non-COD orders
  ([rider_deliveries.py:530](../backend/app/services/rider_deliveries.py#L530)).
* `/verify` and `/retry` reject COD payments with a 400.
* An unpaid Razorpay order is hidden from the restaurant and gated from
  progressing ([orders.py:744](../backend/app/services/orders.py#L744),
  [orders.py:789](../backend/app/services/orders.py#L789)).
* The one weak spot is P9 below.

---

## 3. Environment variables

| Variable | Used by | Local `backend/.env` | Render | Notes |
|---|---|---|---|---|
| `RAZORPAY_KEY_ID` | provider auth; returned to clients as `razorpay_key_id` | configured (`rzp_test_***`) | unknown, Phase 2 | public by design |
| `RAZORPAY_KEY_SECRET` | provider auth, payment signature | configured | unknown, Phase 2 | backend only |
| `RAZORPAY_WEBHOOK_SECRET` | webhook HMAC | **missing** | unknown, Phase 2 | webhook returns 503 without it |
| `ENVIRONMENT` | production guards | set | unknown | see note |

**Production guard** ([config.py:150-179](../backend/app/core/config.py#L150-L179)):
with `ENVIRONMENT=production`, startup **fails** if the key is `rzp_test_…`, or if a
key id is set without a webhook secret. So a Test Mode deployment on Render cannot
run with `ENVIRONMENT=production`, and the "webhook secret required" guard is
switched off for exactly the deployment these phases will test.

**Git hygiene:** every `.env` is git-ignored; only `.env.example` and
`.env.development` files are tracked, and none contains Razorpay values. No key
secret or webhook secret value was found in tracked files or in history. A
Razorpay **Key ID** (`rzp_test_Tf3d…`) is written in
`docs/payments/phase-40-production-payment-readiness.md`. Key IDs are public (sent
to every client), so this isn't a leak, but Phase 34 should note it.

---

## 4. Existing test coverage

**Backend: 289 tests passed in 33 payment/COD/refund/webhook files.**

| Area | Test files |
|---|---|
| Order creation / idempotency | `test_razorpay_order_creation`, `test_idempotent_payment_creation`, `test_duplicate_payment`, `test_payment_concurrency_real_threads`, `test_checkout_payment_decision` |
| Signature / amount | `test_payment_signature_verification`, `test_payment_api` |
| Status / state machine | `test_payment_status_synchronization`, `test_payment_order_state_machine` |
| Failure / retry | `test_payment_failure_recovery`, `test_payment_retry` |
| Webhooks | `test_payment_webhooks`, `test_webhook_idempotency`, `test_payment_webhook_notifications` |
| Refunds | `test_partial_refunds`, `test_refund_e2e`, `test_notification_payment_refund_hooks` |
| Security / IDOR | `test_payment_security_audit` |
| E2E | `test_complete_razorpay_e2e`, `test_complete_cod_e2e`, `test_cod_end_to_end` |
| Financial / visibility | `test_financial_ledger_validation`, `test_financial_consistency`, `test_admin_payments`, `test_admin_financial_integration`, `test_restaurant_payment_visibility`, `test_customer_payments` |
| COD | `test_cod_flow`, `test_rider_cod_collection`, `test_admin_cod_reconciliation`, `test_cod_notifications` |

**Customer mobile: 16 tests passed** (`checkout.razorpay`, `order-detail.payment-retry`, `payments.screen`).

All backend tests replace Razorpay with fakes or mocked transports. **No test
talks to the real Razorpay Test Mode API.**

---

## 5. Missing tests

| Gap | Phase |
|---|---|
| Live Test Mode connectivity: authentication and creating a real test order | 3 |
| `POST /payments/create` with a `method` that doesn't match `order.payment_method` | 25 / 27 |
| `payment.authorized` webhook or authorized-only payment (manual-capture accounts) | 11 / 20 |
| Verify called after the 30-minute expiry while Razorpay has already captured the payment (late capture), followed by recovery through webhook | 13 / 15 |
| `payment.captured` arriving for a payment that's already `refunded` / `partially_refunded` | 19 / 24 |
| PaymentAttempt audit trail when payment is confirmed **only** by webhook | 21 |
| Real Checkout on a device (success, failure, cancel) | 8, 9, 13, 14 |
| Live webhook delivery to Render | 17, 36 |

---

## 6. Potential problems (hypotheses for later phases)

| # | Severity | Problem | Where | Phase |
|---|---|---|---|---|
| **P1** | High | **Late capture after expiry.** `verify` marks a payment FAILED (410) once it's more than 30 min old, but the Razorpay order is still payable. A customer who pays at minute 31 is charged while the order stays unpaid. Only a `payment.captured` webhook repairs it, because the handler only skips `paid`. Without a working webhook the money is captured but the order is never confirmed. | `payment_service.verify_payment`, `_PAYMENT_EXPIRY_WINDOW` | 13, 15, 17 |
| **P2** | High | **Webhook dependency.** P1 and P3 recovery, refund completion and failure sync all need the webhook. The secret is missing locally, and Render's state is unknown. The production guard can't enforce it in Test Mode (§3). | env / Razorpay Dashboard | 2, 17 |
| **P3** | Medium | **`payment.authorized` isn't handled, and verify requires `captured`.** If the Razorpay account isn't set to automatic capture, verify returns `PAYMENT_NOT_CAPTURED`: the payment is marked FAILED, and the customer and restaurant get "payment failed" notifications while the funds are authorized. `create_order` doesn't set capture behaviour, so it depends on the dashboard setting. | `razorpay_provider.create_order`, `verify_payment` | 11, 20 |
| **P4** | Medium | ✅ *Fixed in Phase 3 (uncommitted).* **Provider errors aren't logged.** `ProviderRequestError` becomes a generic 502 (`record_order_payment`, `/payments/create`, `/verify`), and Razorpay's response body or status is never logged. That's why today's production 502 can't be diagnosed. | `services/payments.record_order_payment`, `endpoints/payments.py` | 3, 4 |
| **P5** | Low | **The webhook can overwrite refund state.** `payment.captured` only skips `paid`; for a `refunded` / `partially_refunded` payment it would set `paid` again. Razorpay retries use the same event id, which is deduplicated, so this needs an unusual delivery to trigger. | `_handle_payment_captured` | 19, 24 |
| **P6** | Low | **No attempt is recorded for webhook-confirmed payments.** When only the webhook confirms a payment, no `PaymentAttempt` records the success. The audit trail shows just the creation-time `pending` attempt. | `_handle_payment_captured` | 21, 37 |
| **P7** | Low | **The creation-time attempt is never closed.** The attempt written at Razorpay order creation stays `pending` forever; verify writes a separate attempt. Reconciliation may see a "pending" attempt next to a `paid` payment. | `create_payment_for_order` | 7, 37 |
| **P8** | Low | **Dead weaker verifier.** `services/payments.verify_payment` checks only the signature, not amount, capture or expiry. It isn't routed and only tests import it, but it would be unsafe if someone wired it up. | `services/payments.py` | 34 |
| **P9** | Low | **`/payments/create` trusts the client's `method`.** The body's `method` isn't compared with `order.payment_method`. A customer can create a COD Payment for an online order. Because there's one Payment per order, that permanently prevents online payment, so the order can never progress. That's self-harm only, with no free food or money. Mobile doesn't use this route. | `endpoints/payments.create_payment` | 25, 27 |
| P10 | Info | The test **Key ID** appears in a tracked docs file. It's public by design, not a secret. | `docs/payments/phase-40…` | 34 |

**Confirmed sound (no action):** HMAC is constant-time; the webhook is verified
before parsing; webhook and payment-id idempotency are backed by unique
constraints; Payment creation takes a row lock and is unique per order; refunds
lock the payment and check the remaining amount; all money is `Decimal`/`Numeric`;
the backend derives the amount and method on the mobile route; every customer
route checks ownership; admin refund requires `require_admin`; mobile never
reports "paid" without asking the server.

---

## 7. Phase 1 result

| Item | Result |
|---|---|
| Implementation located and documented | ✅ |
| Razorpay separated from COD | ✅ with one weak spot (P9) |
| Existing automated tests | ✅ 289 backend + 16 mobile passed |
| Files changed | `docs/razorpay-test-audit.md` (new). No code changes. |
| Blocker for Phase 2 | `RAZORPAY_WEBHOOK_SECRET` is missing from local `backend/.env`. Render's values need confirming from the dashboard, because I can't read Render's environment. |

### Phase 1 re-check (2026-10-07)

Re-ran on request. HEAD is still `5b19ccb58`. The only payment-code change since the
audit is the uncommitted Phase 3 logging fix in `razorpay_provider.py`, which resolves P4.
The other uncommitted changes (`schemas/review.py`, `services/reviews.py`) don't touch
payments. Baseline: **289 backend payment tests passed** (34 files) and **16 mobile payment
tests passed**. §2–§6 still describe the code accurately. P1–P3 and P5–P10 remain open
for their mapped phases.

---

## Phase 2 — Test Environment Validation (2026-10-06)

No secret values were printed or recorded. The checks used the app's own settings loader and redacted `grep`.

| Variable | Local `backend/.env` | Render (deployed) | How Render was checked |
|---|---|---|---|
| `RAZORPAY_KEY_ID` | configured · `rzp_test_` ✅ · no stray whitespace | configured | `GET /customer/payment-methods` → `online.available=true` (needs both key and secret) |
| `RAZORPAY_KEY_SECRET` | configured · 24 chars, the normal Razorpay length · no stray whitespace | configured | same |
| `RAZORPAY_WEBHOOK_SECRET` | **missing** | **missing** | `POST /payments/webhooks/razorpay` with a bogus signature → `503 "Webhook verification is not configured yet."` (rejected before parsing; nothing stored) |
| `ENVIRONMENT` | `development` | not `production` (inferred) | A test key with `ENVIRONMENT=production` would refuse to start, and the service is healthy |

Not yet verifiable: whether **Render's** key ID starts with `rzp_test_`. It's only returned on a Razorpay payment response, so it's checked in Phase 3/4.

**Git:** `backend/.env`, `admin-web/.env`, `business-web/.env` and `customer-mobile/.env.production`
are all git-ignored and untracked. No tracked `.env*` file contains a Razorpay value. No
key-secret or webhook-secret value appears in the current tree or in the last 200 commits.

**Result:** FAIL, blocked on `RAZORPAY_WEBHOOK_SECRET` (local and Render). Key ID and secret pass.

### Phase 2 re-run (2026-10-06, after local key rotation)

* Local `RAZORPAY_KEY_ID` / `RAZORPAY_KEY_SECRET` were replaced with the user's new test pair. Both are configured, the key ID starts with `rzp_test_`, and neither has stray whitespace or quotes. The old pair is backed up outside the repo.
* Local `RAZORPAY_WEBHOOK_SECRET`: **still missing**.
* Render: online payment is still `available=true` (key ID and secret present). The webhook probe still returns **503, not configured**.
* `backend/.env` is still ignored and untracked; no tracked file contains a Razorpay value.
* **Result: still FAIL, blocked on `RAZORPAY_WEBHOOK_SECRET` (local and Render).**

### Phase 2 re-run #2 (2026-10-06, after webhook setup) — **PASS**

| Variable | Local | Render |
|---|---|---|
| `RAZORPAY_KEY_ID` | configured · `rzp_test_` ✅ | configured ✅ (prefix checked in Phase 3/4) |
| `RAZORPAY_KEY_SECRET` | configured ✅ | configured ✅ |
| `RAZORPAY_WEBHOOK_SECRET` | configured ✅ | configured ✅ |

* Render webhook with a bogus signature → `400 Invalid webhook signature` (was 503).
* Render webhook with an event signed using the **local** secret → `200 received`, so local and Render secrets match. That probe (`phase2.secret_match_probe`) is logged as `unhandled_event_type` and touched no payment.
* `backend/.env` is ignored and untracked; no env file appears in `git status`.
* Note: the local webhook secret is 15 characters. That's fine for Test Mode, but use a 32+ byte random value (`openssl rand -hex 32`) for live.

---

## Phase 3 — Razorpay API Connectivity (2026-10-06) — **PASS** (local)

Run through the existing `RazorpayProvider` with the local Test Mode keys (`rzp_test_***`). No secrets were printed.

| Check | Result |
|---|---|
| Authentication + `create_order` ₹1.00 (100 paise) | ✅ `order_Tki2gpXrPB25oP`, amount `1.00`, `INR`, status `created`, ~1 s |
| `fetch_order` read-back | ✅ id, amount, currency and status match |
| Paise conversion ₹499.50 | ✅ round-trips exactly as `499.50` |
| Wrong secret | ✅ refused by Razorpay with `401`, raised as `ProviderRequestError` |
| Empty credentials | ✅ `ProviderNotConfiguredError` raised before any network call |

**Issue confirmed and fixed (audit P4):** a Razorpay error such as a 401 for bad keys
reached users as a generic 502 "Unable to reach the payment provider", and nothing was
logged, which is why the 502 seen in production earlier couldn't be explained.
`razorpay_provider.py` now logs each failed call once, with Razorpay's HTTP status and
error description, through a new `_request_error()` helper used by all four calls:
order creation, payment lookup, order lookup and refund. I checked that neither the key
secret nor the webhook secret appears in the log line. Example:
`Razorpay order creation failed: HTTP 401 — Authentication failed`.
API responses to clients are unchanged.

**Tests:** 289 payment tests still pass.

**Not covered here:** connectivity from **Render**. Its keys are only exercised through
the app's payment endpoint, which is Phase 4. The logging fix reaches Render only after
it's pushed and deployed.

Two ₹1.00 / ₹499.50 Test Mode orders (receipts `phase3-connectivity-probe*`) remain in
the Razorpay dashboard in `created` state. That's harmless, as unpaid Test Mode orders cost nothing.

---

## Phase 4 — Backend Payment Order Creation (2026-10-06) — **PASS** (Render, live Test Mode)

The app's real flow was driven against **Render** as test customer `customer.aligarh@sayhichai.in`:
address → cart (Masala Chai ×2 + Cold Coffee ×1) → `GET /customer/checkout` → `POST /customer/orders/validate`
→ `POST /customer/orders` (`payment_method=razorpay`) → **`POST /customer/orders/{id}/payment`**, the endpoint
the mobile app calls.

| Check | Result |
|---|---|
| Server-calculated total (checkout) | ₹120.00 (subtotal 120, delivery 0, tax 0, discount 0) |
| Order | `ORD-20261006-3FEC2A`, total 120.00, `placed`, `is_paid=false` |
| Payment endpoint | ✅ 200 in 3.5 s, method `online`, status **`pending`** |
| Razorpay order ID | ✅ `order_TkiFsFQ5VmDfob` (same on `transaction_reference` and `provider_order_id`) |
| Amount | ✅ payment 120.00 = order 120.00 = checkout 120.00 = **Razorpay 12000 paise** |
| Currency | ✅ `INR` locally and at Razorpay |
| Razorpay order status (fetched directly from Razorpay) | ✅ `created` |
| Not yet verified/paid | ✅ `is_verified=false`, `paid_at=null` |
| Render key ID | ✅ `rzp_test_***` and **identical to the new local pair**, so Render's keys were rotated correctly |
| Client sends `amount: 1, currency: "USD"` (mobile route) | ✅ ignored; same payment returned, ₹120.00 |
| Client sends `amount: 1, currency: "USD"` (`/payments/create`) | ✅ ignored; same payment, ₹120.00, `INR` |
| Repeated calls | ✅ same Payment and same Razorpay order; no new Razorpay order created |

Existing automated tests for this area (`test_razorpay_order_creation`, `test_idempotent_payment_creation`,
`test_checkout_payment_decision`, `test_payment_api`): all pass.

**Earlier production 502 explained:** Render's Razorpay order creation works now that its keys match the
new pair. The 502 at 08:45 UTC is consistent with the old, rejected key pair. The Phase 3
logging fix would have shown `HTTP 401` directly.

**Notes**
* The Aligarh restaurant's delivery fee is ₹0 because the owner script doesn't set one. That's fine for testing. Set a fee in business-web if you want to test with one.
* Test artifacts left on Render: order `0df3c060-888c-4fbb-b780-40f0b4351a50` (unpaid Razorpay order; hidden from the restaurant until paid), payment `588db351-…`, and a Test Mode Razorpay order in `created` state. The payment expires after 30 min.

No code changes in this phase.

---

## Phase 5 — Amount Integrity (2026-10-07) — **PASS** (local backend + live Razorpay Test Mode)

A scratch harness (not committed) drove the real HTTP routes: cart → `POST /customer/orders` →
`POST /customer/orders/{id}/payment` → `POST /payments/{id}/verify`. It ran on a throwaway in-memory
database, with the **real** `RazorpayProvider` calling Razorpay Test Mode (`rzp_test_***`).
The local dev database and Render were not touched. Delivery fee was ₹0, so the order total equals
the cart value. Every Razorpay amount was read back with `fetch_order`.

### Consistency across order, payment, attempt and Razorpay

| Target | `Order.total` | `Payment.amount` | `PaymentAttempt.amount` | Razorpay order | Currency / status |
|---|---|---|---|---|---|
| ₹1 | 1.00 | 1.00 | 1.00 | 100 paise | INR · created ✅ |
| ₹100 | 100.00 | 100.00 | 100.00 | 10000 paise | INR · created ✅ |
| ₹499 | 499.00 | 499.00 | 499.00 | 49900 paise | INR · created ✅ |
| ₹999 | 999.00 | 999.00 | 999.00 | 99900 paise | INR · created ✅ |
| ₹1500 | 1500.00 | 1500.00 | 1500.00 | 150000 paise | INR · created ✅ |
| ₹499.50 (paise) | 499.50 | 499.50 | 499.50 | 49950 paise | INR · created ✅ |
| ₹33.33 × 3 | 99.99 | 99.99 | 99.99 | 9999 paise | INR · created ✅ |

Every order had exactly one creation attempt. All money stayed `Decimal`/`Numeric`, and paise conversion was exact, with no float drift.

### Manipulation (₹500 order, client tries to pay ₹1)

| Attempt | Result |
|---|---|
| Fields `total`, `subtotal`, `amount`, `currency: "USD"` added to `POST /customer/orders` and `/orders/{id}/payment` | ✅ Ignored. Server totals and INR were used (neither schema has an amount field). |
| A validly signed ₹1 Razorpay order submitted to verify the ₹500 payment | ✅ 400, `ORDER_MISMATCH`, `is_paid=false` |
| The ₹500 order ID sent with the ₹1 order's signature | ✅ 400, `SIGNATURE_MISMATCH`, `is_paid=false` |
| Razorpay reports a **captured ₹1** payment on the ₹500 order (only `fetch_payment` simulated; `fetch_order` live) | ✅ 400, `AMOUNT_MISMATCH` recorded on a `PaymentAttempt`, `is_paid=false` |
| Payment initialisation repeated with `amount: 1` | ✅ The same ₹500 Razorpay order was returned; no cheaper order was opened |

A real captured ₹1 payment needs device Checkout, which is Phases 9 and 13. The capture-mismatch case above
uses a simulated `fetch_payment`. The other three checks it depends on hit the real Razorpay API.

**Tests:** harness 12/12. Existing amount tests (`test_razorpay_order_creation`,
`test_payment_signature_verification`, `test_payment_api`, `test_checkout_payment_decision`,
`test_financial_consistency`) 52 passed. Full payment suite 289 passed.

**Observation (info, no fix):** when a `provider_payment_id` that's already recorded against a *different*
payment is submitted, verify still rejects it. However, the unique constraint means no new
`PaymentAttempt` row is written; only the warning log records it. That is the intended design
(`PROVIDER_ID_ALREADY_USED`). It's noted for Phase 21/37 audit-trail checks.

**Test artifacts:** about 20 Test Mode Razorpay orders (₹1–₹1500, receipts are local UUIDs or `phase5-cheap-order`)
remain in `created` state in the Razorpay dashboard. They're unpaid and cost nothing.

No code changes in this phase.

---

## Phase 6 — Currency Validation (2026-10-07) — **PASS** (local backend + live Razorpay Test Mode)

This used the same approach as Phase 5: real HTTP routes, an in-memory database, and the real `RazorpayProvider`
against Test Mode. Signed webhooks were sent to the local app using the configured webhook secret, which was never printed.

### Where currency comes from

* The backend hardcodes `"INR"` when it creates the Razorpay order (`payment_service.py:149`).
  `Payment.currency` defaults to `INR`.
* **No live request schema accepts a currency.** `CustomerOrderCreate` and `PaymentCreateRequest` (`order_id`, `method`)
  have no currency field, and neither does the mobile payment route.
* `verify` requires **both** the fetched Razorpay payment's currency and the order's currency to equal `Payment.currency`.
  The `payment.captured` webhook requires the same.
* Mobile passes `currency: "INR"` to Checkout. It's informational, since the Razorpay `order_id` fixes the currency.

### Results

| Scenario | Result |
|---|---|
| Client sends `currency` = `USD` / `inr` / `""` on `/customer/orders/{id}/payment` | ✅ Ignored. DB `INR`, live Razorpay order `INR` |
| Client sends `currency` = `EUR` / `XYZ` on `/payments/create` | ✅ Ignored. Response, DB and Razorpay all `INR` |
| Verify: Razorpay payment captured in `USD`, order `INR` (live `fetch_order`) | ✅ 400 `CURRENCY_MISMATCH`, not paid |
| Verify: payment `INR`, Razorpay order `USD` | ✅ 400 `CURRENCY_MISMATCH`, not paid |
| Verify: provider returns lower-case `inr` | ✅ Rejected (strict match; Razorpay always sends `INR`) |
| Verify: `INR`/`INR` (control) | ✅ 200, paid |
| Signed `payment.captured` webhook in `USD` / `EUR` | ✅ Logged as `amount_mismatch`; payment stays `pending`, order unpaid |
| Signed `payment.captured` webhook in `INR` (control) | ✅ `payment_marked_paid` |

**Tests:** harness 12/12. 29 existing test files that cover currency: 215 passed. Full payment suite: 289 passed.

### Observations (no fix; not genuine defects)

* **P11 (info): dead code with a client currency field.** The legacy `PaymentCreate` schema (`currency: str = "INR"`,
  `provider`) and `services/payments.create_payment_record(currency=…)` have no callers in `app/` or `tests/`.
  They're harmless today but would let a client choose the currency if someone wired them up. This is the same
  category as P8, so leave it for the Phase 34 cleanup decision.
* The webhook outcome label `amount_mismatch` also covers currency mismatches. The log line says
  "amount/currency mismatch". This is a naming detail only.
* `CustomerPaymentRead` (mobile route response) doesn't return `currency`. Mobile assumes INR, which is consistent.
* Refund webhooks don't compare currency. Razorpay refunds are always in the payment's currency, so check this again in Phase 22.

**Test artifacts:** about 10 more unpaid Test Mode Razorpay orders in `created` state.

No code changes in this phase.

---

## Phase 7 — Payment Database Validation (2026-10-07) — **PASS** (PostgreSQL 17 + live Razorpay Test Mode)

The project's docker Postgres (`backend-postgres-1`) was started, and a **throwaway database**
(`say_hi_chai_phase7`) was created and built with `alembic upgrade head` (through `20261011_57`). The real HTTP
routes ran against it with the real `RazorpayProvider`. Afterwards the database was dropped and the container
stopped again. Dev data and Render were not touched.

### Schema as migrated

| Table | What was checked |
|---|---|
| `payments` | `amount numeric(10,2)` + `CHECK ≥ 0`; `currency varchar(8) default 'INR'`; `provider`/`payment_status` are PG enums; all timestamps `timestamptz`; **UNIQUE** `order_id`, `(provider, razorpay_order_id)`, `(provider, razorpay_payment_id)`; FK → orders/users `ON DELETE CASCADE` |
| `payment_attempts` | `amount numeric(10,2)` + `CHECK ≥ 0`; `status` enum; `timestamptz`; **UNIQUE** `(provider, provider_payment_id)`; FK → payments |
| `orders` | `subtotal`/`total`/fees `numeric(10,2)` with non-negative CHECKs; `is_paid`; `payment_method`/`payment_status` varchar |

`alembic check` shows **no drift on any payment table** (payments, payment_attempts, refunds, webhook_events).

### One checkout, as stored

| Row | Values |
|---|---|
| Order `ORD-20261007-08AD7F` | `placed` · `razorpay` · `payment_status=pending` · `is_paid=false` · 225.00 + 25.00 delivery = **250.00** |
| Payment | `razorpay` · `pending` · **250.00 INR** · `razorpay_order_id=order_Tl6sLDqNSOu6le` · `razorpay_payment_id`, `signature`, `paid_at`, `failure_reason` all NULL · `is_verified=false` · `user_id` = order owner |
| PaymentAttempt | `pending` · 250.00 · same Razorpay order ID · `provider_payment_id` NULL |
| Razorpay (live) | `order_Tl6sLDqNSOu6le` · 25000 paise · INR · `created` · exactly **1** Razorpay order for receipt = local order ID |
| Timestamps | All tz-aware and inside the run window. Order is created before payment. Payment and attempt share `now()` because they're in one transaction. |
| `webhook_events` | 0, since checkout writes no webhook rows |

### No duplicates

| Scenario | Payments | Attempts | Razorpay orders |
|---|---|---|---|
| Mobile route ×4, then `/payments/create` ×1, same order | 1 | 1 | 1 |
| **6 truly concurrent** payment inits (thread barrier, real Postgres row lock) | 1 | 1 | 1 (all 6 got HTTP 200) |
| Direct SQL insert of a 2nd payment for the order | rejected `UniqueViolation` | | |
| Direct SQL: negative amount / reuse another payment's Razorpay order ID | rejected `CheckViolation` / `UniqueViolation` | | |

**Tests:** harness 17/17; payment suite 289 passed.

Two harness fixes were needed; neither was an app issue. Razorpay's `GET /orders?receipt=` listing lags creation
by a few seconds, and it rate-limits (429) rapid polling, so the harness waits and backs off.

### Observations (no fix in this phase)

* **P7 status:** the creation attempt is correctly `pending` at this stage. Whether it is ever closed after
  payment is still Phase 21/37's question.
* `POST /payments/create` returns **201** even when it returns an already-existing payment. It's idempotent and correct;
  only the status code reads as "created". Info only.
* `orders.payment_status` is a free `varchar(32)`, while `payments.payment_status` is an enum, so the database
  doesn't enforce agreement between them. Check this in Phases 11 and 12.
* `alembic check` drift **outside payments** (categories/coupons/users/notification_preferences unique-vs-index
  representation, coupon CHECKs present in models but not in migrations, and a redundant duplicate unique index on
  `orders.order_number`). This is out of scope for Razorpay testing and is flagged for a separate schema task.

No code changes in this phase.

---

## Phase 8 — Customer Checkout Integration (2026-10-07) — **PASS**

**Device run (by the user)**: the customer app (release APK, pointing at Render) went Login → Restaurant → Menu →
Cart → Checkout → Pay, and **Razorpay Checkout opened**. The user then declined or closed Checkout.

### Backend and Razorpay side (checked from here)

| Check | Result |
|---|---|
| Render `/health` | ✅ 200 |
| New Razorpay order created by **Render** for this checkout | ✅ `order_Tl72dRDiDmRI9I` · 2000 paise (₹20.00) · INR · created 23:41:35 · receipt = Render order ID `16c15b4d-…` |
| Payments on that Razorpay order after the decline | ✅ **0**, with `amount_paid=0` and status `created`. Nothing was charged, and no failed payment was recorded. The decline happened before a payment was submitted. |

### Client build checks

* APK `android/app/build/outputs/apk/release/app-release.apk` (built 2026-10-01): contains the Razorpay native SDK
  (`com.razorpay.CheckoutActivity`, 364 Razorpay classes). The Hermes bundle points at `https://delivery-app-rjux.onrender.com`.
* Mobile changes since that build (`5b19ccb58`) only add a map/distance preview on checkout. Payment code is unchanged.
* `razorpay-flow.ts` opens Checkout with the **server-supplied** `key` (`razorpay_key_id`) and `order_id`. The `amount` passed
  is informational. On success, the callback is only forwarded to `/verify`, and the outcome comes from a fresh `GET` of the payment.
  On dismissal or error, the flow returns "failed" **without calling the backend**, so Render's Payment stays `pending`.

**Not verified directly:** the Render `Payment` row's status after the decline. That needs the customer's token or DB
access. Code inspection and the Razorpay state (0 payments) both mean it's unchanged (`pending`). Phase 14 tests cancellation explicitly.

No code changes in this phase. No unrelated UI was modified.

---

## Phase 9 — Test Payment Success (2026-10-07, completed 2026-10-08) — **PASS (Razorpay side verified; backend 'paid' state confirmed only by the app screen)**

The user will make the successful Test Mode payment on the device later. This phase is **not** passed until a
real captured payment is checked. No simulated payment is counted.

**Done now:**
* Backend success-path tests: `test_payment_signature_verification`, `test_complete_razorpay_e2e`,
  `test_payment_status_synchronization`, `test_payment_order_state_machine`. 23 passed.
* Code path already confirmed in Phase 8: on Checkout success the app sends the callback to `/verify`, then re-reads the
  payment. The order is only marked paid by the backend after the HMAC check and Razorpay's fetched `captured` status,
  amount and currency agree.
* A read-only Razorpay check script is prepared. It lists the newest Test Mode orders with their payments and never prints secrets.

**To run on the device:** place a **new** order. The Phase 8 order (`order_Tl72dRDiDmRI9I`) is past the backend's 30-minute
window, and paying it now would test late capture (P1), not success. Pay with Razorpay's Test Mode details only, such as
UPI `success@razorpay` or a test card from Checkout or the Razorpay docs.

**To verify afterwards:** the Razorpay payment is `captured`, its `order_id` matches, and the amount and currency match. The app
shows "paid" only after the backend confirms. If the order number is shared, compare the Render payment status too.

### Result (2026-10-08) — device payment verified

The user paid a **new** order on the device (release APK → Render). Checked read-only against the Razorpay Test Mode API; no secrets printed.

| Check | Result |
|---|---|
| Razorpay order | `order_TlN7vEPKJ06PrP`, created 15:25:41 IST, status **`paid`**, amount ₹20.00, `amount_paid` ₹20.00, `amount_due` ₹0.00, INR, 1 attempt |
| Backend link | `receipt` = backend order id `b1ec7f77-a599-498b-9f30-3c11086a7d5d` |
| Payment | `pay_TlN9BZ1tXWlnMu`, **`captured`** (`captured=true`), card, created 15:26:55 IST |
| Exactly one captured payment on the order | ✅ |
| `payment.order_id` matches the order | ✅ |
| Amount matches the order (₹20.00) | ✅ |
| Currency INR on both | ✅ |
| No refund, no error code | ✅ |
| Paid within the backend's 30-minute window (74 s after order creation) | ✅ (normal success path, not P1 late capture) |

Render's database can't be read from here. The backend's own `paid` status for `b1ec7f77-…` rests on what the app showed after `/verify`. The webhook secret is configured on Render (Phase 2), so `payment.captured` also reaches it.

**Observation (no defect proven):** four other Razorpay orders of ₹180 were created at 10:13–10:15 IST with 0 attempts. They carry **four distinct receipts**, so they're four separate backend orders, not duplicate Razorpay orders for one backend order. They look like abandoned checkout starts and stay unpaid with no automatic cleanup (see the Phase 14 note). This links to idempotency/double-submit testing (E2E Phase 27).

---

## Phase 10 — Payment Signature Verification (2026-10-07) — **PASS after fix**

The harness drove `POST /payments/{id}/verify` (real route, in-memory DB). Each case used a fresh payment with a real
Test Mode Razorpay order, and signatures were HMAC-SHA256 with the server-side Test Key Secret (never printed).
In every rejection case, `fetch_payment` was **simulated as `captured` with the correct amount**, so only the
signature/ID checks could stop the payment. That isolates this phase's logic.

| Case | Result |
|---|---|
| Valid signature + Razorpay `captured` | ✅ 200 · `paid` · `is_paid=true` · `razorpay_payment_id` stored |
| Valid signature, **live** Razorpay lookup of an unknown payment ID | ✅ HMAC accepted, but 502 `PROVIDER_UNREACHABLE`, payment stays `pending`. A valid signature alone never marks it paid. |
| Invalid signature (random hex) | ✅ 400 `SIGNATURE_MISMATCH` |
| Modified order ID (signature for the real order) | ✅ 400 `ORDER_MISMATCH` |
| Modified order ID, validly re-signed for that other order | ✅ 400 `ORDER_MISMATCH` |
| Modified payment ID | ✅ 400 `SIGNATURE_MISMATCH` |
| Modified signature: 1 hex char flipped / upper-cased / truncated / trailing space / empty | ✅ 400 `SIGNATURE_MISMATCH` |
| `payment|order` order swapped | ✅ 400 `SIGNATURE_MISMATCH` |
| Signed with the webhook secret instead of the key secret | ✅ 400 `SIGNATURE_MISMATCH` |
| Missing `signature` field | ✅ 422 |
| **Non-ASCII signature** (`"é"×64`) | ❌ **500** before the fix → ✅ 400 `SIGNATURE_MISMATCH` after |

In every rejected case, `is_paid=false` and `is_verified=false`, and a `PaymentAttempt` records the failure code.

### Issue found and fixed

**`verify_hmac_signature` crashed on non-ASCII input.** `hmac.compare_digest(str, str)` raises `TypeError` when a string
contains a non-ASCII character, so a crafted signature produced an unhandled **HTTP 500** from `/verify`. The same applied
to the webhook endpoint through a crafted `x-razorpay-signature` header. The payment state was not changed (no partial
write, nothing marked paid), so this was a robustness and availability defect, not a payment bypass.

* Fix: [verification.py](../backend/app/services/payment/verification.py) now compares bytes,
  `compare_digest(expected.encode("ascii"), signature.encode("utf-8"))`. That still runs in constant time.
* Regression test: `test_verify_hmac_signature_rejects_non_ascii_signatures_instead_of_raising` in
  `tests/test_payment_service_architecture.py`.
* After the fix: `/verify` returns 400. The webhook with a non-ASCII signature header returns `400 Invalid webhook signature`.
* **Not yet on Render.** It reaches Render on the next push/deploy, as with the Phase 3 logging fix.

**Tests:** harness 15/15 (14/15 before the fix). Payment suite + `test_security.py`: 316 passed.

**Hypothesis for Phase 18:** the webhook route decodes the raw body with `body.decode("utf-8")` before the HMAC check. A
signed-but-invalid-UTF-8 body, or any invalid UTF-8 body with a signature header, may also produce a 500.

---

## Phase 11 — Payment Status Synchronization (2026-10-08) — **PASS after fix (P3 confirmed and fixed)**

The harness used real routes and an in-memory DB, with live `fetch_order`. `fetch_payment` was simulated per Razorpay
status, and signed webhooks used the configured secret.

### Razorpay status → local status (`/verify`)

| Razorpay payment status | Before fix | After fix |
|---|---|---|
| `created` | 400 · FAILED · "payment failed" alerts | unchanged ✅ (not a hold; still a failure) |
| **`authorized`** (amount/currency/order all match) | ❌ 400 · **FAILED** · customer + restaurant told **"payment failed"** | ✅ 200 · **PROCESSING** · no failure alerts · order unpaid |
| `authorized` but wrong amount | 400 · FAILED | unchanged ✅ |
| `captured` | 200 · PAID · `is_paid=true` · `order.payment_status=paid` | unchanged ✅ |
| `failed` / `refunded` | 400 · FAILED | unchanged ✅ |

### Webhooks

| Event | Result |
|---|---|
| `payment.authorized` | ✅ recorded `unhandled_event_type`; state unchanged and waiting for capture |
| `payment.captured` | ✅ `payment_marked_paid` → PAID, order paid (works from PENDING, PROCESSING or FAILED) |
| `payment.failed` after PAID | ✅ `ignored_already_paid` |
| `payment.failed` | ✅ `payment_marked_failed` → FAILED, order unpaid |

**Race (verify sees `authorized`, capture webhook a moment later):** before the fix it ended PAID, but the customer had
already been told the payment failed and saw "Payment not completed" with a retry button. After the fix the payment is
PROCESSING after verify, with no failure notification, then PAID after the webhook.

### Client cannot set status

* `status`, `payment_status`, `is_paid` added to `/customer/orders/{id}/payment` and `/payments/create` bodies: ✅ ignored (still `pending`)
* `PUT`/`PATCH /payments/{id}`, `POST /payments/{id}/status`: ✅ 405/405/404, no such endpoint
* `/verify` body with `"status": "captured"` while Razorpay says `failed`: ✅ 400, FAILED
* Every server-side writer of PAID/`is_paid` was reviewed: verify, webhook, COD-on-delivery (COD only) and rider COD collection
  (COD only). The legacy signature-only verifier (P8) is still not imported anywhere.

### Fix (P3)

[payment_service.py](../backend/app/services/payment/payment_service.py) `verify_payment`: when Razorpay reports `authorized`
**and** the order ID, amount and currency all match, the payment becomes **PROCESSING**. The attempt is recorded as PROCESSING with
`PAYMENT_NOT_CAPTURED` for audit. No failure notifications or warning are sent; an info log records it. PROCESSING is already re-verifiable and
**not retryable**, so the customer can't pay twice while funds are held. The `payment.captured` webhook or a later `/verify`
completes it. Mobile already shows "Your payment is still processing" for this state, so no app change was needed.

* Updated test `test_a_not_yet_captured_payment_state_is_rejected_even_with_a_valid_signature`. It still asserts "never
  accepted as paid", now asserts PROCESSING instead of FAILED, and checks that a later capture → PAID.
* New test `test_a_created_but_not_authorized_payment_is_still_rejected`.
* **Not yet on Render** (uncommitted, along with the Phase 3 and 10 fixes).

**Tests:** harness 15/15. Payment suite + `test_security.py`: 317 passed.

### Remaining observations

* **Manual-capture risk remains a config question (→ Phase 17/20):** if the Razorpay account is not on automatic capture, a
  payment would now wait in PROCESSING until someone captures it in the dashboard. That is correct behaviour, but it would
  never complete on its own. Phase 9's real payment will show whether the account auto-captures.
* **`orders.payment_status` is only ever set to `"paid"`.** It stays `"pending"` when the payment is FAILED or PROCESSING. It is a
  denormalised display field. The Payment row and `is_paid` are authoritative and correct. Refunds are checked in Phases 22 and 30.

---

## Phase 12 — Order State After Payment (2026-10-08) — **PASS after fix** (2 notification findings deferred to Phase 31)

The harness used real customer and **restaurant-owner** routes and an in-memory DB, with live Razorpay orders. Success was driven by
both `/verify` (simulated `captured` fetch) and a signed `payment.captured` webhook.

### Existing design (unchanged)

Payment success **does not change `order.status`**. It sets `is_paid=true` / `order.payment_status="paid"`, which makes the
order visible to the restaurant. The order stays `placed` until the restaurant accepts it (`→ confirmed`). Accept is gated on `is_paid`
for Razorpay orders. COD is visible and acceptable immediately.

| Scenario | Order | `is_paid` | Payment | Restaurant list | Restaurant accept |
|---|---|---|---|---|---|
| Before payment | placed | false | pending | hidden | 409 ✅ |
| Success via `/verify` | placed | **true** | paid | **visible** | 200 → **confirmed** ✅ (history `placed → confirmed`) |
| Success via webhook only | placed | **true** | paid | visible | 200 ✅ |
| **Failed** | placed | false | failed | hidden | 409 ✅, never confirmed |
| Authorized (PROCESSING) | placed | false | processing | hidden | 409 ✅ |
| Customer cancels, then payment captures | **cancelled** (not revived) | false | **refund_pending** + admin alert ✅ | — | — |
| COD (control) | placed | false | pending | visible | 200 ✅ |

### Issue found and fixed

**A restaurant could reject an unpaid online order.** `accept_order` was gated on payment and `reject_order` was not. The order is
hidden from the restaurant's list, but the premature "New order" push (below) deep-links its ID, and `GET /restaurant/orders/{id}`
returns it. Rejecting while the customer was still in Checkout made the payment that followed land in `refund_pending`:
the customer was charged for a dead order and an admin had to refund it manually.

* Fix: [orders.py](../backend/app/services/orders.py) `reject_order` has the same `razorpay and not is_paid → 409` gate as `accept_order`.
* Regression test: `test_restaurant_cannot_reject_an_unpaid_online_order_even_by_direct_id` in `tests/test_payment_status_synchronization.py`.
* After the fix: reject → 409; preparing → 409. A paid order can still be rejected (existing behaviour; the payment → refund flow).
* **Not yet on Render** (uncommitted).

**Tests:** harness 11/13 (the 2 failures are the notification findings below). **Full backend suite: 1589 passed, 10 skipped.**

### Deferred to Phase 31 (notifications), not fixed here

* **P12: the restaurant is notified "New order … received" at order creation, even for an unpaid Razorpay order.**
  `create_order` calls `notify_restaurant_new_order` unconditionally. The restaurant gets a push for an order it can't see or accept,
  then a second "Payment confirmed" on success. If payment fails or is abandoned, it was told about an order that never happens.
* **P13: on payment failure, the restaurant gets a `payment_update` "payment issue" notification** (`notify_restaurant_payment_issue`)
  for an order it never saw. When an unpaid order is cancelled, it gets `restaurant_order_cancelled` for it, and the cancelled order
  appears in its list (by design: dead records are shown).
* Observation: `GET /restaurant/orders/{id}` returns an unpaid online order, including the delivery address, to its restaurant.
  It's read-only and its own restaurant only. It's worth a decision alongside P12.

---

## Phase 13 — Payment Failure Test (2026-10-08) — **PASS** (backend; device failure run pending)

The harness used real customer and restaurant routes and an in-memory DB, with **live Razorpay Test Mode orders**. Failures arrived the way Razorpay
reports them: a signed `payment.failed` webhook with Razorpay's error fields (`BAD_REQUEST_ERROR`, `payment_failed`,
"declined by the bank"), or `/verify` seeing status `failed`.

### How a failure reaches the backend

* **On the device:** a Checkout failure or dismissal makes `razorpay-flow.ts` return "failed" **without calling the backend**. The
  payment stays `pending` until Razorpay's `payment.failed` webhook arrives. The order screen offers "Complete Payment" /
  "Retry Payment".
* **Retry** (`POST /payments/{id}/retry`) reopens the **same** Razorpay order, since Razorpay allows several attempts per order.
  No new Razorpay order and no new local order or payment are created.

| Scenario | Result |
|---|---|
| `payment.failed` webhook | ✅ `payment_marked_failed`, FAILED, `failure_reason` = Razorpay's description, shown to the customer through `GET /payments/{id}` |
| Order after failure | ✅ `placed`, `is_paid=false`, hidden from restaurant, accept 409, never confirmed |
| 2nd declined attempt (another `payment.failed`) | ✅ `duplicate_ignored`, still exactly 1 customer failure notification |
| Retry after failure | ✅ 200, back to `pending`, same Razorpay order (live status `created`, still payable) |
| Successful 2nd attempt | ✅ PAID, order paid and visible to the restaurant |
| `/verify` sees `failed` | ✅ 400, FAILED, `PaymentAttempt(failed, PAYMENT_NOT_CAPTURED)` |
| 4 failures + 3 retries, then success | ✅ 1 payment, 1 order, 1 Razorpay order, all 5 verify attempts kept, then PAID |
| Dismissed on device (backend not told) | ✅ stays `pending`, retry allowed |
| Retry on a cancelled order | ✅ 409 "This order is cancelled and can no longer be paid." |
| Retry after 30 min | ✅ 410 "expired", stays FAILED, unpaid |
| …then Razorpay captures anyway (still-open Checkout) | ✅ `payment.captured` webhook honours it → PAID (P1 recovery works **when the webhook is configured**, which it now is) |
| Retry on PAID | ✅ 409 |

**No false success** in any scenario: `is_paid` was false after every failure step.

**Tests:** harness 15/15 (one harness typing bug fixed; no app issue). Existing backend failure, retry and webhook tests: 41 passed.
Mobile `checkout.razorpay` + `order-detail.payment-retry`: 11 passed.

### Observations (no fix in this phase)

* **Webhook-reported failures don't create a `PaymentAttempt`.** After "declined via webhook → retry → success", the attempts are
  `[pending, paid]`. The failure is auditable only through `WebhookEvent` (raw payload with the Razorpay payment ID) and
  `Payment.failure_reason`. Failures reported through `/verify` *are* attempts. This links to P6 and is for **Phase 21** (failed attempts
  must stay auditable).
* **The device failure run is still pending.** The user's Phase 8 decline closed Checkout before any payment was created. To see a
  real `payment.failed` from Razorpay, use a Test Mode failure option in Checkout (for example the netbanking/UPI "Failure" choice),
  then retry from the order screen. This can be combined with the Phase 9 success run.

No code changes in this phase.

---

## Phase 14 — Payment Cancellation (2026-10-08) — **PASS**

### Real device evidence (Phase 8 run, Render)

The user opened Razorpay Checkout in the release APK and backed out. Razorpay's record of `order_Tl72dRDiDmRI9I` (₹20, created by Render)
still shows status `created` with **0 payments**. Nothing was charged and no payment exists.

### App behaviour on dismissal

`RazorpayCheckout.open()` rejects, and `razorpay-flow.ts` returns `failed` **without calling `/verify` or anything else on the backend**.
`checkout.tsx` shows "Payment not completed … Your order was placed — you can retry payment from your order." The order screen then offers
"Complete Payment". Mobile test `a cancelled/failed Razorpay checkout never calls verify, and reports failure` passes.

### Backend (harness: real routes, live Razorpay orders)

| Scenario | Result |
|---|---|
| Back out of Checkout twice | ✅ payment `pending`, no failure reason, only the creation attempt, order `placed` / unpaid / hidden from restaurant, **no** "payment failed" notification; Razorpay: `created`, 0 payments |
| "Complete Payment" afterwards | ✅ `/retry` 200 from `pending`, same Razorpay order; success → PAID; 1 payment, 1 order |
| Started paying, then cancelled (Razorpay sends `payment.failed`, "Payment processing cancelled by user") | ✅ FAILED with that reason, order unpaid, retry allowed |
| Back out, then the customer cancels the order | ✅ order `cancelled`, never paid, retry 409, no refund needed |

Dismissal is never treated as success: in every case `is_paid=false` until a verified capture.

**Tests:** harness 10/10. Mobile cancel test passes.

### Observations (no fix)

* On a cancelled unpaid order, the Payment stays `pending` (the `cancelled` status exists but isn't used), and its Razorpay order stays open.
  If the customer somehow still pays it, the existing path flags `refund_pending` and alerts an admin (verified in Phase 12). This is a
  bookkeeping/reconciliation note for **Phase 37**.
* After the 30-minute window an abandoned online order stays `placed`/unpaid (hidden from the restaurant) until the customer cancels it.
  There is no automatic cleanup. This is information only.

No code changes in this phase.
