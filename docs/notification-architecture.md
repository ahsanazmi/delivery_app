# Notifications & Communication System — Architecture

**Status key:** ✅ already implemented and running · 🆕 designed here, not yet built (a later phase's job) · 🔒 a deliberate decision *not* to build something, with the reasoning.

This document designs the architecture *around* the existing implementation identified in `docs/notification-system-audit.md`, the same way `docs/live-tracking-architecture.md` did for live tracking. Where the audit found a working pattern, it's documented as the standing design, not re-litigated. Where this master command asks for something that doesn't exist yet (a preference check, a formal event-handler layer), a concrete decision is made here so later phases have a specific target, not a vague direction.

---

## 1. The pipeline, as it actually runs today

```text
Business action (e.g. transition_order_status)                 ✅
     │  the business service completes its own state change
     │  and commits it FIRST — a notification is never part of
     │  the same atomic guarantee the business action needs
     ▼
Direct call into a notify_* function                            ✅
     │  e.g. notify_order_status_change(db, order, new_status)
     │  — see §2 for why this is NOT a generic event bus
     ▼
Notification Service (app/services/notifications.py)            ✅
     │  resolves the recipient, looks up the right
     │  title/body/type for this event, decides whether to
     │  fire at all (the notifications_enabled kill switch;
     │  then the per-user preference check — see §5)
     ▼
Notification Record (Notification row, db.add + commit)         ✅
     │  this alone is the in-app channel — no separate
     │  "in-app delivery" step exists or is needed; the row
     │  existing IS the in-app notification
     ▼
Push delivery (app/services/push_notifications.py)              ✅
     │  send_push_to_user/send_push_to_users(_in_background) —
     │  a real HTTP call to Expo's push endpoint, failure-
     │  isolated from everything above it
     ▼
Client                                                            ✅
     │  in-app: GET /notifications (polled, on screen open)
     │  push: delivered by the OS: foreground → alert shown
     │  in-app by the client's own notification handler,
     │  background/killed → OS notification tray, tap → deep
     │  link (full coverage across every category each client
     │  actually receives, Phase 27 — the audit's own Deep
     │  Linking gap is closed)
```

This already matches the master command's own preferred flow almost exactly:

| This phase's diagram | What actually exists |
|---|---|
| Business Event | The business service's own function (e.g. `transition_order_status`) |
| Notification Event Handler | *Is* the `notify_*` function call site — see §2 for why no separate layer exists |
| Notification Service | `app/services/notifications.py` |
| Notification Record | `Notification` row |
| Delivery Channel → In-App | The row itself, read via `GET /notifications` |
| Delivery Channel → Push | `app/services/push_notifications.py` |

## 2. 🔒 No generic event bus — a direct function call is the "Notification Event Handler"

The diagram's "Notification Event Handler" step could be read as asking for a formal event-dispatch layer: business code calls `emit_event("order.confirmed", payload)`, and one or more registered handlers (one of which is the notification system) react to it. **This is deliberately not being built.** Reasoning:

- **No second consumer exists for these events.** An event bus earns its complexity when multiple independent subsystems need to react to the same business event without knowing about each other. Today exactly one thing reacts to "order confirmed": the notification system. Introducing a pub/sub layer for a single subscriber is complexity without justification — the same discipline Live Rider Tracking's own Phase 35 applied to not introducing Redis for a single-worker deployment.
- **The direct call already satisfies "keep business logic separate from delivery."** Verified in the audit: `transition_order_status` (`app/services/orders.py`) contains zero knowledge of *how* a notification is delivered — no Expo HTTP call, no push payload construction, nothing about channels. It calls `notify_order_status_change(db, order, new_status)` and is done. That function, not a separate handler, is the seam — and it already lives in its own module, not inline in the business service.
- **It's the established pattern for a comparable problem already.** Live Rider Tracking's WebSocket broadcast (`_broadcast_tracking_update`, called from the same `transition_order_status` choke point) uses the identical shape: business action commits, *then* a direct call out to a separate concern, wrapped in its own failure-isolation. Notifications should look the same, not introduce a second architectural style for a structurally identical problem.

If a genuine second consumer of these events ever emerges (analytics, an audit trail, a webhook-to-a-third-party feature), *that* is the point to introduce a real dispatch layer — not speculatively now.

## 3. Where a new business event's notification call belongs

For any future phase adding a new `notify_*` call site: it goes at the **same choke point the existing calls already use**, not scattered at every individual caller. Concretely:

- **Order status changes** — all of them already flow through `transition_order_status` (`app/services/orders.py`), the single choke point every caller (customer cancel, rider pickup/deliver, admin override, restaurant confirm) already goes through. A new order-status-triggered notification needs one line added to `_ORDER_STATUS_NOTIFICATIONS`, never a new call site at each of that function's many callers.
- **Payment events** — `app/services/payments.py`'s verification/webhook handlers, mirroring the existing `notify_customer_payment_failed` call site.
- **COD events** — `collect_cod_payment`/`_settle_cod_payment_on_delivery` (`app/services/rider_deliveries.py`/`orders.py`).
- **Non-status-change events (proximity, assignment)** — no single choke point exists for these by nature (they're not order-status transitions), so each gets its own direct call at its own natural trigger point, exactly like `maybe_notify_rider_approaching` already does from `update_rider_location`.

## 4. Failure isolation — extending an existing guarantee, not inventing a new one

Live Rider Tracking Phase 32 established the pattern this system already follows for its own broadcast layer: wrap the delivery call in try/except at the business-service choke point, log a structured `tracking_error` event, and never let a delivery-layer failure abort the business action or any of its own later side effects. `push_notifications.py`'s own `_send_expo_push` already independently arrived at the same guarantee (a bare `except Exception: return`). Later phases (31) should make this **structurally the same pattern**, not a second one: a failure anywhere in the notification pipeline degrades to "notification not sent," logged, never "the order/payment/COD action failed."

## 5. ✅ The preference check (Phase 24) — as built

Built as planned, with one refinement the actual implementation found: the preference check sits **inside the Notification Service, before the `Notification` row is written** — the same place the platform-wide `_notifications_enabled()` kill switch already runs (`app/services/notifications.py`). A per-user preference check is an additional, narrower gate at the same point, never a replacement for it:

```text
notify_order_status_change(...)
    │
    ├─ _notifications_enabled(db)?           platform-wide gate
    ├─ _user_wants(user_id, type)?           per-user gate (_NOTIFICATION_CATEGORY
    │                                        maps every real NotificationType to
    │                                        one of order_updates/delivery_updates/
    │                                        payment_updates/promotions/
    │                                        system_notifications)
    ▼
db.add(Notification(...))
```

Both checks must pass before a `Notification` row is even created — a suppressed notification for either reason is not "created but not delivered," it never exists at all, matching how `_notifications_enabled()` already behaves (a total no-op, not a silently-failed send).

**The one refinement**: the original plan above assumed the whole "transactional" bucket (order/delivery/payment) would be non-disableable. Building it for real found a narrower, more accurate line: `order_updates`/`delivery_updates`/`payment_updates` *are* user-toggleable (defaulting to on, satisfying "should remain enabled where necessary" as a default, not a hard floor) — only `ACCOUNT_APPROVED`/`ACCOUNT_SUSPENDED` are excluded from the category map entirely and can never be silenced, since they gate whether a rider can work at all, not an informational update. Admin operational alerts (`notify_admins`'s own types) are excluded the same way, for a different reason: they're a job-function responsibility tied to the `ADMIN` role, not a personal preference.

## 6. 🔒 No new WebSocket channel for notifications — a considered decision, not an oversight

The audit's own open question: should a `Notification` row's creation push live to an already-open app via WebSocket, the way rider location does? **Decision: no, not now.** Reasoning:

- **The push channel already covers the two cases that matter.** App backgrounded/killed → the OS delivers the push notification directly, independent of any app-level WebSocket. App foregrounded → `push-notifications.ts`'s `setNotificationHandler` already shows the alert immediately when a push arrives while open (`shouldShowAlert: true`) — the one remaining gap is that the notification *list*/unread count doesn't auto-refresh without the screen being reopened, a much smaller problem than "no live delivery at all."
- **`OrderTrackingConnectionManager` doesn't fit this shape without real new infrastructure.** It's order-scoped (one room per order, built for "everyone watching this one order"); a notification is user-scoped and order-independent (a payment failure, a promotion, an admin alert — none of them have an order to room around). A user-scoped channel would be new infrastructure, not a reuse of the existing manager, and nothing in the audit found evidence that polling-on-open is actually insufficient in practice.
- **Consistent with this whole codebase's repeated stance on unjustified complexity** (Redis in Live Rider Tracking Phase 35, an event bus in §2 above): build it if a specific, evidenced gap shows up (e.g. a real user complaint that the badge is stale for minutes while the app is open), not speculatively.

If this decision needs revisiting, the natural design (documented here for whoever revisits it) would be a second, user-scoped `OrderTrackingConnectionManager`-shaped class — same interface shape, different room key (`user_id` instead of `order_id`) — not a modification to the existing tracking manager itself.

## 7. Channel abstraction (Rule 7 — "keep providers replaceable")

`push_notifications.py`'s functions (`send_push_to_user`, `send_push_to_users`, `send_push_to_users_in_background`) already are the channel abstraction — every `notify_*` call site depends on these, never on `httpx.post(EXPO_PUSH_URL, ...)` directly (verified: that URL appears exactly once, inside `_send_expo_push`). This already satisfies "business code should depend on NotificationService, not directly on Expo" for the push channel specifically. A future SMS/email/WhatsApp channel (explicitly out of scope unless a later phase asks for it) would add its own `send_*` module following this same shape, called from the same Notification Service layer — never a second parallel dependency path from business code.

## 8. Summary for implementers of later phases

Phases 3, 4, 9 (unread-count), 12 (business-web, from scratch), 24–25 (preferences), 27 (fix the two unmapped deep-link types the audit found), 30–32 (idempotency/retry/token cleanup) are where genuinely new work is concentrated. Phases 5–8, 18–23 will find most of their own "connect X to notifications" goal already done per the audit, and should focus on the specific named gaps rather than rebuilding what already runs.

## 9. ✅ Retention (Phase 34)

`list_notifications`' own 100-row cap (`_MAX_NOTIFICATIONS_RETURNED`, `app/services/notifications.py`) only ever bounded what one `GET /notifications` call returns — the `notifications` table itself grew without limit underneath it. Phase 34 added the actual retention policy:

**Retention period** — two tiers, not one, because "avoid storing unlimited notification history" and "do not delete active/important operational notifications prematurely" pull in different directions depending on whether the notification was ever read:

| State | Retention | Why |
|---|---|---|
| `is_read = true` | 90 days | The user already saw and acted on it; in-app history beyond this has steeply diminishing value. |
| `is_read = false` | 365 days | "Still active" from that user's own point of view, however old — purged only as a backstop against truly-abandoned accounts, an order of magnitude longer than the read-retention window, never a routine trigger. |

Both are plain module constants (`_NOTIFICATION_RETENTION_DAYS_READ`/`_NOTIFICATION_RETENTION_DAYS_UNREAD`, `app/services/notifications.py`) — documented, adjustable business rules, the same shape as `COD_SETTLEMENT_DUE_THRESHOLD` and `_PAYMENT_EXPIRY_WINDOW` elsewhere in this codebase, not derived from anything external.

**Cleanup strategy** — `purge_old_notifications(db)` is a plain, idempotent, callable function, not a scheduled job: this codebase has no scheduler/background-worker system (confirmed repeatedly — see `PaymentService`'s own lazy order-expiry check for the same reasoning), so building one speculatively here, ahead of Phase 42's own decision on background processing, would be exactly the kind of unjustified complexity §2/§6 above already argue against. It's exposed as `POST /api/v1/admin/notifications/cleanup` (admin-only, platform housekeeping — not scoped to the calling admin's own notifications) so it can be triggered on demand today, and is exactly what a future scheduled job would call once one exists.

**Database indexes** — `ix_notifications_is_read_created_at` (new, Phase 34) on `(is_read, created_at)`, matching `purge_old_notifications`' own global (not per-user) sweep pattern; the pre-existing `ix_notifications_user_id_is_read` doesn't serve this query since it has no `user_id` filter at all. The existing `ix_notifications_created_at`, `ix_notifications_type`, `ix_notifications_status`, and `ix_notifications_user_id_is_read` indexes continue to serve `list_notifications`/`count_unread_notifications`/the admin aggregation check (Phase 33) as before — unchanged by this phase.

## 10. 🔒 Background processing — the existing mechanism already fits, no new one introduced

Phase 42's own diagram (`Business Event → Persist event/notification → Background worker → Push Provider`) describes something that already exists in this codebase, for the one path that actually needs it: `notify_admins`'s `background_tasks` parameter (Performance & Reliability, Phase 39). The `Notification` row is written synchronously, atomically with the business event that caused it (unchanged); only the real network call to the push provider is deferred, via FastAPI's own built-in `BackgroundTasks` — scheduled to run *after* the HTTP response is sent, in `send_push_to_users_in_background`'s own independent DB session (a request-scoped session isn't safe to reuse from a background task). Currently wired into exactly one caller: the Razorpay webhook handler, where a slow Expo response must never delay Razorpay's own webhook acknowledgement — a real, external time constraint the other paths don't have.

**Decision: not extended any further, and no new dependency introduced.** Reasoning:

- **It's already "existing infrastructure," not a new one.** `BackgroundTasks` is part of FastAPI itself, no new package, no new service to run or operate. Using it more broadly would be "reuse existing infrastructure," exactly as this phase asks — but doing so isn't free.
- **No evidence the other paths need it.** Every other `notify_*` call site dispatches its push synchronously, bounded by Phase 31's own retry budget (at most ~0.6s added latency in the worst case, and even that only on a genuine provider failure — the common case is a single fast round trip). Nothing in this whole 42-phase engagement found a real complaint or measurement showing this is actually too slow for a customer's own order-status-change request, a rider's own delivery action, or an admin's own promotional broadcast.
- **Extending it would be a large, invasive refactor for a hypothetical problem.** `notify_*` functions are called from deep inside service code (`transition_order_status`, `create_order`, `collect_cod_payment`, ...), none of which currently receive a `background_tasks` parameter — only `notify_admins`'s own specific caller (the webhook route) already threads one through. Giving every call site the same treatment would mean adding an optional `background_tasks` parameter to every route handler, every intermediate service function, and every `notify_*` call in the chain — real surface area and real risk, for a path with no demonstrated latency problem.
- **A heavier queue (Redis/Celery/Kafka) was never on the table.** This phase explicitly warns against introducing one "solely for complexity," and nothing here comes close to needing one — this backend's actual notification volume (order-lifecycle events for one platform, not a mass fan-out system) doesn't call for durable retry queues, worker pools, or cross-process coordination. `BackgroundTasks` itself already covers the one case that needed deferring.

If a specific, evidenced latency problem shows up on a particular path later (a real measurement, not a guess), the fix is the same one already proven here: thread `background_tasks` through that *one* call chain, the same way the webhook path already does — not a new mechanism, and not every path at once.

## 11. ✅ API endpoints — complete reference

Every notification-related route in the backend, grouped by role. `{role}` below is the router's own prefix (`customer`/`rider`/`restaurant`/`admin`); `/register` and `/preferences` are shared across every role (there's nothing role-specific about "this is my own device" or "this is my own setting").

| Method | Path | Who | What |
|---|---|---|---|
| `GET` | `/api/v1/{role}/notifications` | customer, rider, restaurant, admin | List this caller's own notifications (capped at 100, most recent first) |
| `GET` | `/api/v1/{role}/notifications/unread-count` | customer, rider, restaurant, admin | This caller's own unread count |
| `POST` | `/api/v1/{role}/notifications/{id}/read` | customer, rider, restaurant, admin | Mark one of this caller's own notifications read (idempotent) |
| `POST` | `/api/v1/{role}/notifications/read-all` | customer, rider, restaurant, admin | Mark every unread notification of this caller's own read (idempotent) |
| `POST` | `/api/v1/admin/notifications/cleanup` | admin only | Trigger `purge_old_notifications` on demand (Phase 34) — global, not scoped to the calling admin |
| `POST` | `/api/v1/admin/notifications/broadcast` | admin only | Send a promotional push to every active customer — title/body only, see §9/Phase 36 for why type/recipient can never be set |
| `POST` | `/api/v1/notifications/register` | any authenticated role | Register/renew this device's own push token (Phase 14/15) |
| `DELETE` | `/api/v1/notifications/register` | any authenticated role | Deactivate this device's own push token (logout) |
| `GET` | `/api/v1/notifications/preferences` | any authenticated role | This caller's own preference row (lazily created on first read) |
| `PATCH` | `/api/v1/notifications/preferences` | any authenticated role | Update one or more of this caller's own preference categories (Phase 25) |

No route anywhere lets a client create an arbitrary `Notification` row or target another user — verified structurally, not just by convention (`test_no_route_anywhere_lets_a_client_create_an_arbitrary_notification`, Phase 36).

## 12. ✅ Device token lifecycle

```text
App launches, user signs in
      │
      ▼
registerForPushNotifications() (client)        — permission requested at
      │                                          most once ever (Phase 28/16)
      ▼
POST /api/v1/notifications/register
      │  device_identifier: a stable per-install id (SecureStore),
      │  never cleared on logout — identifies the device, not the session
      ▼
upsert_push_token()
      │
      ├─ same device_identifier already on file?  -> same row, token
      │                                               updated in place
      │                                               (handles OS-level
      │                                               token rotation)
      ├─ same token already active under a         -> that row deactivated
      │  DIFFERENT user? (shared/reused device)        first (Phase 15)
      └─ neither?                                   -> new row
      ▼
PushToken row: is_active=true, last_seen_at=now
      │
      │   ... time passes, pushes are sent ...
      ▼
Provider reports DeviceNotRegistered (Phase 32)
      │
      ▼
is_active=false  (never deleted — device_identifier/history preserved;
                   a future re-registration from the same device revives
                   this same row)
      │
      │   ... or the user logs out ...
      ▼
DELETE /api/v1/notifications/register  ->  is_active=false (same soft
                                             deactivation, same reasoning)
```

A deactivated token is simply never selected by `send_push_to_user`/`send_push_to_users` again (`PushToken.is_active.is_(True)` is part of every query) — "never repeatedly send to a known-invalid token" holds by construction, not by a separate check.

## 13. ✅ Security rules — summary

The full detail lives in each phase's own tests (Phase 35's dedicated audit, Phase 45's final pass); this is the index.

- **Authentication/authorization** — every route requires a valid, non-expired JWT; role-gated routes (`/admin/*`) reject every other role with 403.
- **Ownership (IDOR)** — every list/read/mark-read query is scoped to `user_id == current_user.id`; a wrong-owner notification ID 404s (never leaks existence), the same pattern this codebase uses everywhere else.
- **Device-token ownership** — no field exists anywhere to register or deactivate a token under anyone but the authenticated caller; the same physical token can never stay "live" under two different users at once (Phase 15).
- **Payload security** — `build_notification_data()` is a narrow, named-parameter builder (`type`/`order_id`/`status` only), not `**kwargs` — structurally impossible to stuff an email, a raw amount, or any other field into a notification's `data` without first changing that function's own signature.
- **Provider secret protection** — `EXPO_ACCESS_TOKEN` is read from settings, attached only to the outbound provider request's own `Authorization` header, and never appears in a stored row, an API response, or a log line (Phase 45).
- **Event integrity** — no client-callable endpoint can fabricate a business-event notification; the only file in the entire codebase that ever constructs a `Notification` row is `app/services/notifications.py` (Phase 36).
- **Rate limiting / anti-spam** — repeated admin alerts of the same type aggregate into one row instead of flooding; no customer/rider/restaurant transactional notification is ever suppressed for this reason (Phase 33).
