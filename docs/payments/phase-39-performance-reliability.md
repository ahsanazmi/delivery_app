# Phase 39 — Performance & Reliability

## Scope
Review payment creation latency, database queries, webhook
processing, payment status lookup, admin payment listing, and refund
processing. Ensure webhook processing is reliable and does not
perform unnecessary long-running work synchronously. Use background
processing only if already supported by the architecture; do not
introduce unnecessary infrastructure for MVP.

## Method
A direct code review of all six named areas (no subagent — this
phase is about judging specific tradeoffs in code already read in
depth across Phases 4/17/21/23/24/27, not a broad multi-file search).
One concrete, fixable reliability issue was found; everything else
was already sound and is documented below as reviewed, not changed.

## The fix: webhook processing was blocking on a real network call

`_handle_payment_captured()` (`webhook_service.py`), on the "payment
captured for an already-cancelled/rejected order" edge case, calls
`notify_admins()`, which — before this phase — called
`send_push_to_users()` **synchronously**: a real `httpx.post()` to
Expo's push API with a 5-second timeout, executed on the same request
thread that owes Razorpay its webhook acknowledgment. A slow or
unreachable Expo endpoint would delay that acknowledgment by up to 5
seconds, risking Razorpay treating the delivery as failed and
retrying it (harmless thanks to this project's existing webhook
idempotency, but still unnecessary load and latency) — exactly what
this phase's "does not perform unnecessary long-running work
synchronously" instruction is about.

**Fix**: this backend has no task queue (confirmed — `grep` for
`BackgroundTasks`/Celery/RQ across `app/` found nothing), and the
instruction is explicit not to add infrastructure for an MVP. FastAPI
itself already ships `BackgroundTasks` — no new dependency, no new
process, no new deployment unit — so it's the "already supported by
the architecture" option, not a new piece of infrastructure. Changes:

- `app/services/push_notifications.py` — new
  `send_push_to_users_in_background()`, which opens and owns its
  *own* independent DB session (`SessionLocal()`) rather than reusing
  the caller's request-scoped one (whose lifetime relative to a
  background task isn't something to rely on), and commits its own
  stale-push-token cleanup — a real, if small, correctness
  improvement over before, where that cleanup only ever persisted if
  whatever unrelated commit happened to follow it succeeded.
- `app/services/notifications.py` — `notify_admins()` gained an
  optional `background_tasks: BackgroundTasks | None = None`
  parameter. The Notification DB rows are still written synchronously
  and atomically with the caller's own commit, exactly as before —
  only the actual network call is deferred, and only when a caller
  opts in by passing `background_tasks`. Every other existing caller
  is unaffected.
- `app/services/payment/webhook_service.py` — `background_tasks`
  threaded through `process_webhook_event()` →
  `_handle_payment_captured()` → its one `notify_admins()` call. The
  other three webhook handlers (`_handle_payment_failed`,
  `_handle_refund_processed`, `_handle_refund_failed`) don't call
  `notify_admins()` at all, so nothing else needed to change.
- `app/api/v1/endpoints/payments.py` — the `/payments/webhooks/razorpay`
  route now takes `background_tasks: BackgroundTasks` and passes it
  through.

Two payment-service call sites of `notify_admins()`
(`payment_service.py`, on the customer-facing `/verify` endpoint's
failure and dead-order paths) have the identical synchronous-push
pattern, but were deliberately left unchanged: those run on a
customer's own request/response cycle, not a third-party webhook with
its own retry/timeout semantics, and backgrounding them is a broader
change than this phase's specific "webhook processing" instruction
asks for. Flagged here for a future phase to decide, not silently
left undiscovered.

## Everything else reviewed — no change needed

- **Payment creation latency**: `create_payment_for_order()`
  deliberately holds the Order row's `with_for_update()` lock across
  the real Razorpay `create_order()` call. This looks like a latency
  smell in isolation, but it's Phase 21's own explicit, documented
  design: the lock is what stops a genuinely concurrent duplicate
  request from *also* calling Razorpay and orphaning a second
  provider-side order. The cost is a one-time, per-order lock held for
  one network round-trip — narrow and appropriate for MVP scale;
  removing it would reintroduce the exact bug Phase 21 fixed (and
  Phase 38's new real-thread concurrency test now guards against
  regressing).
- **Refund processing**: `create_refund()` holds the Payment row's
  lock across `provider.initiate_refund()` for the identical reason
  (Phase 23) — prevents two near-simultaneous refunds from together
  exceeding the captured amount. Same considered tradeoff, same
  conclusion: no change.
- **Database queries**: no N+1 pattern found across
  `admin_payments.py`, `payments.py`, `refund_service.py`,
  `rider_deliveries.py`, `webhook_service.py` (checked by grepping
  every loop body for a query call inside it). Admin payment listing
  already does one JOIN query plus a single *batched* refund-status
  lookup for the whole page (not per-row); customer payment history
  already uses `joinedload(Payment.order)`.
- **Payment status lookup**: both lookup paths are already indexed —
  `Payment.id` (primary key) for `GET /payments/{id}`, `Payment.order_id`
  (explicit `index=True`) for `GET /payments/order/{id}`.
- **Admin payment listing**: reviewed above under database queries.
  The one theoretical scaling concern — `ILIKE '%...%'` search/filter
  patterns can't use a plain btree index — is real but only bites at
  a data volume well beyond MVP; a trigram index would be new
  infrastructure this phase's own instruction says not to add
  pre-emptively. `Payment.payment_status` also has no dedicated index
  for admin's status filter; same conclusion — worth revisiting if
  admin payment volume genuinely grows, not before.

## Files created
- `docs/payments/phase-39-performance-reliability.md`

## Files modified
- `app/services/push_notifications.py`
- `app/services/notifications.py`
- `app/services/payment/webhook_service.py`
- `app/api/v1/endpoints/payments.py`
- `backend/tests/test_payment_webhooks.py`
- `backend/tests/test_push_notifications.py`
- `docs/payments/README.md`

## Testing
- New: `test_payment_captured_for_a_cancelled_order_defers_the_admin_push_to_background_tasks`
  — proves `notify_admins()` never calls the synchronous push path
  when `background_tasks` is supplied (monkeypatches
  `send_push_to_users` to raise if called), and that exactly one
  `send_push_to_users_in_background` call is scheduled instead.
- New: `test_send_push_to_users_in_background_uses_its_own_independent_session`
  — proves the background function opens, uses, and commits its own
  session, independent of any caller session, by verifying the
  stale-token cleanup is durably persisted when read back through a
  completely separate session afterward.
- Full backend suite: **1240 passed, 10 skipped, 0 failed** (baseline
  1238 + 2 new).

## Live verification
Not applicable — no externally-observable API contract changed (same
request/response shapes, same status codes); the change is purely
about *when* an internal side effect's network call happens relative
to the webhook response.

## Known limitations
The customer-facing `/verify` endpoint's two `notify_admins()` calls
(payment_service.py) still send push notifications synchronously,
same as before this phase — noted above as a deliberate scope
boundary, not an oversight.
