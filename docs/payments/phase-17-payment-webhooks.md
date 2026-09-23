# Phase 17 — Payment Webhooks

## Scope
Implement a backend webhook endpoint (`POST
/api/v1/payments/webhooks/razorpay`). It must: receive the provider
event, verify the webhook signature, identify the payment/order, process
the event idempotently, update payment state, and create an audit/event
record. Never trust a webhook payload without signature verification.

## What was found
Signature verification already existed (`POST /api/v1/payments/webhook`,
built in Phase 4/5 as a deliberate placeholder — its own docstring said
"No order/payment mutation is wired up yet"). Everything past that —
identifying the payment/order, idempotent processing, state updates, and
an audit record — was genuinely missing.

## What was built

### `WebhookEvent` (new model + migration)
A durable, append-only audit row for every signature-verified webhook
this backend ever receives, independent of whether it could be matched
to a known payment (`payment_id` is nullable specifically for that case —
`PaymentAttempt` couldn't represent it, since its own `payment_id` is
required). Stores the event type, identified provider ids, a short
machine-readable `outcome`, and the raw verified payload (safe to retain
— Razorpay webhook bodies never include the key secret or card/UPI
details). Migration `20261001_42` round-trip tested (upgrade → downgrade
→ verified table gone → upgrade → back to head).

### `process_webhook_event()` (`app/services/payment/webhook_service.py`)
The route handler's job is authenticity only (signature check, unchanged
from Phase 5); this function is the *only* place that acts on a verified
payload, and it always returns a committed `WebhookEvent` rather than
raising — a webhook handler's job is to acknowledge receipt, and an event
this backend doesn't recognize is not this backend's error to surface as
one.

- **`payment.captured`** — looks up the `Payment` by `razorpay_order_id`;
  if already `PAID`, records `duplicate_ignored` (idempotent — most
  likely because the client's own `/verify` call already completed
  first); if the amount/currency in the payload disagrees with
  `payment.amount`/`currency`, records `amount_mismatch` and marks
  **neither** PAID nor FAILED (an inconsistent webhook is an anomaly to
  flag, not proof of failure); otherwise marks `PAID` and syncs
  `Order.payment_status`/`is_paid` — the exact same, single rule Phase 16
  established, applied at this second entry point too.
- **`payment.failed`** — same lookup; never downgrades an already-`PAID`
  payment (`ignored_already_paid` — a late, out-of-order failure
  notification loses to a capture that already happened), otherwise marks
  `FAILED`.
- **`refund.processed`** — looks up the `Refund` by `provider_refund_id`;
  idempotent the same way, marks `COMPLETED` when new.
- Any other event type (`payment.authorized`, `order.paid`, `dispute.*`,
  ...) is recorded with `outcome="unhandled_event_type"` and otherwise
  ignored — Razorpay retries on anything but a 200, so an event this
  backend was never going to act on must never come back as an error.
- Malformed JSON is recorded (`invalid_json`) rather than crashing the
  request.

### Endpoint
Renamed `POST /api/v1/payments/webhook` → `POST
/api/v1/payments/webhooks/razorpay` (matching this phase's own suggested
path; the old route was never registered against any real Razorpay
dashboard — this is a local dev server with no public URL — so nothing
depended on the old path). Signature verification is unchanged; a
verified body is now handed to `process_webhook_event()`.

## Files created
- `backend/app/models/webhook_event.py`
- `backend/alembic/versions/20261001_42_create_webhook_events.py`
- `backend/app/services/payment/webhook_service.py`
- `backend/tests/test_payment_webhooks.py` (14 tests)

## Files modified
- `backend/app/models/__init__.py`
- `backend/app/services/payment/__init__.py`
- `backend/app/api/v1/endpoints/payments.py`
- `backend/tests/test_security.py` (updated the two existing webhook
  tests to the new route path — same assertions, unchanged behavior)

## Testing
- New: 14/14 passing — `payment.captured` marking paid + syncing the
  order, idempotent replay, unknown-order handling, amount-mismatch
  refusal; `payment.failed` marking failed and never downgrading an
  already-paid payment; `refund.processed` completion + idempotent
  replay + unknown-refund handling; unhandled event types and malformed
  JSON both handled without crashing; every processed event leaves an
  audit row with the verified payload; a full real-HTTP round trip with a
  genuinely-computed HMAC signature processes end to end; an unsigned or
  forged request never reaches the processing/audit layer at all — zero
  `WebhookEvent` rows result from it, and the payment is provably
  untouched.
- Regression: `test_security.py`, `test_payment_api.py`,
  `test_payment_service_architecture.py`,
  `test_payment_signature_verification.py`,
  `test_payment_status_synchronization.py` — 76/76 passing.
- Full backend suite: run after this change (confirmed in the next
  phase's report if not already landed at report time).

## Live verification
`RAZORPAY_WEBHOOK_SECRET` was never supplied by the user (unlike
`RAZORPAY_KEY_ID`/`SECRET`, which came from `rzp-test-key.csv`) — the real
running dev server has no webhook secret configured, so a genuine signed
round trip against it isn't currently possible without fabricating a
secret that was never actually provisioned. What *was* verified live
against the real running server: a request with no signature header is
rejected (400), and a request with a signature but no configured secret
is honestly rejected (503) rather than silently accepted — the same
"never fabricate verification you can't actually perform" principle
holds on the real server, not just in tests. The full genuine-signature
processing path is covered instead by `test_http_endpoint_processes_a_genuinely_signed_event_end_to_end`,
which exercises the real FastAPI app, router, and DB dependency through
`TestClient` with an HMAC computed the same way Razorpay itself would.

## Known limitations
Unchanged from prior phases — the unguarded legacy `/payments/{id}/refund`
endpoint and `Order.payment_status` being a plain string remain open. If a
real `RAZORPAY_WEBHOOK_SECRET` is ever provisioned and this endpoint's URL
registered in the Razorpay dashboard, the live server behavior above will
change to genuine processing automatically — no code changes needed.
