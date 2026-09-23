# Phase 18 — Webhook Idempotency

## Scope
Payment providers may retry webhook delivery — the same event may arrive
more than once. Implement protection against duplicate processing, using
a `PaymentEvent`-style record (provider, event_id, event_type,
processed_at, status). Ensure the same event twice is processed once;
never create duplicate payment records or duplicate financial entries.

## What was found
Phase 17's `WebhookEvent` already gave state-based idempotency (checking
whether the target Payment/Refund was already in the resulting state
before acting), but had no concept of the provider's own event identity
at all — every redelivery of the same event created its own audit row and
re-ran the full check, which is "eventually correct" but not "processed
once" in the strict sense: two genuinely concurrent deliveries of the
identical event could both read the pre-change state before either
committed. Research confirmed Razorpay's actual mechanism for this
exact problem: every webhook delivery carries a unique
`x-razorpay-event-id` request header, which Razorpay's own docs
recommend deduplicating on directly — Phase 17 never read this header at
all.

## What was built
Kept the existing `WebhookEvent` model (not renamed to `PaymentEvent` —
same fields the phase suggests, "reuse existing architecture" over
introducing a parallel table for the same concept) and added:

- **`event_id`** column, populated from `x-razorpay-event-id`.
- **`uq_webhook_events_provider_event_id`** — a NULL-safe unique
  constraint (same pattern as every other provider-id constraint in this
  codebase since Phase 3): a request with no event id is never blocked by
  another id-less row, but a genuine repeated event_id is.
- `process_webhook_event()` now checks for an existing row with the given
  `event_id` **before** doing any parsing or dispatch at all — a
  redelivery returns the *original* event's own row untouched, with zero
  further processing, even if the redelivered body somehow differed.
- The check-then-insert is race-proof, not just sequential: if two
  genuinely concurrent deliveries of the same event both pass the
  existence check before either commits, the unique constraint lets
  exactly one win; the loser catches the resulting `IntegrityError`,
  rolls back everything it staged (including any Payment/Order mutation
  from that same call), and returns the winner's row instead of
  surfacing a 500 — the same `IntegrityError`-catch-and-recover pattern
  already used for `uq_payments_order_id` (Phase 6) and
  `uq_payment_attempts_provider_payment_id` (Phase 14).
- This is additive to, not a replacement for, Phase 17's state-based
  checks: a request with no event id (or two genuinely *different* event
  ids that happen to have the same effect) still falls back to exactly
  the Phase 17 behavior.

## Files modified
- `backend/app/models/webhook_event.py`
- `backend/app/services/payment/webhook_service.py`
- `backend/app/api/v1/endpoints/payments.py`

## Files created
- `backend/alembic/versions/20261002_43_webhook_event_id_uniqueness.py`
- `backend/tests/test_webhook_idempotency.py` (7 tests)

## Testing
- New: 7/7 passing — the same event_id delivered twice (and five times)
  results in exactly one `WebhookEvent` row, one `Payment` row, and one
  state change; a redelivery with a deliberately different/malformed body
  under the same event_id still returns the *original* outcome without
  reprocessing; two genuinely different event_ids are each recorded
  independently (Phase 17's own state-check still catches the second as a
  no-op); no event id at all still works via Phase 17's original
  mechanism; a **genuinely concurrent** duplicate insert (the exact race,
  reproduced by forcing the existence-check query to miss the row that's
  actually there) resolves to the winner's row rather than a 500; a real
  HTTP round trip with a repeated `x-razorpay-event-id` header via
  `TestClient` produces exactly one audit row and one payment state
  change.
- Regression: `test_payment_webhooks.py`, `test_security.py`,
  `test_payment_service_architecture.py`,
  `test_payment_signature_verification.py` — 72/72 passing.
- Full backend suite: run after this change (confirmed in the next
  phase's report if not already landed at report time).

## Live verification
Same constraint as Phase 17 — `RAZORPAY_WEBHOOK_SECRET` was never
provisioned on the real running dev server, so a genuine signed
redelivery can't be demonstrated against it. Confirmed live instead that
the real server still honestly refuses (503) even when a real-looking
`x-razorpay-event-id` header is present, rather than fabricating
processing — the full event_id dedup path itself is covered by the
`TestClient`-based HTTP test, which exercises the real app/router/DB
dependency, not a mock.

## Known limitations
Unchanged from prior phases — the unguarded legacy `/payments/{id}/refund`
endpoint and `Order.payment_status` being a plain string remain open.
