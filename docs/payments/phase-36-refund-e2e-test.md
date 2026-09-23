# Phase 36 — Refund E2E Test

## Scope
Test: Successful payment → Admin refund → Provider refund →
Webhook/status update → Internal refund record → Customer payment
status → Admin visibility. For partial refund: ₹500 payment, ₹150
refund. Verify remaining refundable amount.

## Method
One new, canonical, comprehensive test
(`test_complete_refund_flow_every_record_consistent`) drives the exact
flow this phase diagrams through the real HTTP API, using the phase's
own named example throughout (₹500 payment, ₹150 refund, ₹350
remaining). Deliberately exercises the **asynchronous** refund path —
the faked Razorpay gateway's `initiate_refund()` returns `"pending"`,
never `"processed"` — so "Provider refund" and "Webhook/status update"
are two genuinely distinct events, exactly as the diagram lists them
separately, rather than one collapsed step. This is the one part of the
flow Phase 25's own test never exercised (it used the COD/`provider=None`
path, which completes instantly with no webhook involved at all).

## A real, previously-hidden bug, found by this test
Stage 3 ("Provider refund") expected `refundable_amount` to already
read `350.00` the moment the refund was accepted at the provider —
before the webhook ever resolves it — since an in-flight refund is just
as "spoken for" as a settled one (this exact principle is why
`refund_service.create_refund()`'s own validation, `_COMMITTED_REFUND_STATUSES`,
already counts `PROCESSING` refunds when deciding whether a *second*
refund is allowed). It actually read `500.00`.

**Root cause**: `admin_payments.py`'s `refundable_amount` field was
computed as `payment.amount - _refunded_amount(payment)`, where
`_refunded_amount()` deliberately only sums `COMPLETED` refunds (correct
for that field — "refunded" should mean genuinely settled money). But
`refundable_amount` was built from that *same* COMPLETED-only figure,
so a refund still `PROCESSING` was invisible to it — the exact opposite
of `refund_service.create_refund()`'s own validation, which correctly
treats `PROCESSING` as committed. The two figures had quietly drifted
out of sync: the real validation was always correct (confirmed by this
same test — a second refund request for more than the true remaining
amount is still correctly rejected with `409`), but what the admin was
*told* was refundable didn't match what a real refund attempt would
actually be allowed to take.

**Fix**: a new `_refundable_amount()` helper in `admin_payments.py`,
matching `refund_service.py`'s own `_COMMITTED_REFUND_STATUSES`
(`COMPLETED` + `PROCESSING`) exactly, so the displayed figure and the
enforced rule can never diverge again.

## What was verified, stage by stage
1. **Successful payment** — seeded directly (Phase 34 already proves
   capture end to end; this phase's own scope starts from an
   already-paid ₹500 payment).
2. **Admin refund** — `POST /admin/payments/{id}/refund` for ₹150.
3. **Provider refund** — the fake gateway accepts the request
   (`"pending"`), recorded as `Refund.status = PROCESSING`, never
   assumed settled. `refundable_amount` already correctly shows `350.00`
   (the bug fixed above); a second refund attempt for more than that
   remaining amount is still correctly rejected.
4. **Webhook / status update** — a genuine `refund.processed` webhook
   resolves the refund to `COMPLETED` and correctly recomputes the
   parent `Payment`'s own status.
5. **Internal refund record** — the `Refund` row itself: `COMPLETED`,
   correct amount, `provider_refund_id`, `reason` — resolved by the
   webhook, not the original admin call.
6. **Customer payment status** — `GET /customer/payments` shows
   `partially_refunded`; the customer's own view of the *original*
   amount (`500.00`) is unchanged.
7. **Admin visibility** — both the list and detail admin endpoints show
   `PARTIALLY_REFUNDED`, `refunded_amount: 150.00`,
   `refundable_amount: 350.00` — the phase's own named example, verified
   end to end. A duplicate delivery of the same webhook event is
   confirmed to never double-apply the resolution.

## Files modified
- `backend/app/services/admin_payments.py`

## Files created
- `backend/tests/test_refund_e2e.py`
- `docs/payments/phase-36-refund-e2e-test.md`

## Testing
- New: 1 comprehensive test, exercising all seven diagrammed stages.
  Two test-authoring bugs were found and fixed while writing it (UUID
  vs. string comparisons) — neither was a product bug; the one real
  product bug found (`refundable_amount`, above) was fixed in
  `admin_payments.py` itself.
- Regression: `test_admin_payments.py` + `test_partial_refunds.py` +
  `test_refund_e2e.py` together — 38/38 passing after the fix.
- Full backend suite: **1232 passed, 10 skipped, 0 failed** (baseline
  1231 + 1 new) — no regressions.

## Live verification (real dev server)
Seeded a real ₹500 payment with a real, genuinely `PROCESSING` `Refund`
row (₹150) directly in Postgres, then hit the real
`GET /admin/payments/{id}` endpoint: `refundable_amount` correctly
read `350.00`, not `500.00` — confirming the fix live, not just in the
unit test.

All live test data cleaned up afterward (`psql`, FK-dependency order,
verified zero rows remaining).

## Known limitations
Same recurring constraint as every phase touching a real Razorpay
refund since 24: a genuinely `PROCESSING`-then-webhook-resolved refund
against the *real* Razorpay test API can't be produced headlessly (it
requires a payment that was itself genuinely captured through a
browser checkout first). The full async chain is proven against a
faithful fake instead; only the "provider unreachable/network call
itself works" class of proof (Phase 24's own initiate-refund-against-a-
nonexistent-payment check) has ever been done against the real gateway.
