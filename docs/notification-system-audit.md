# Notifications & Communication System — Phase 1 Audit

> **Final status (Phase 47 of this same command): every gap this audit found below has since been closed.** This document is kept as-written — a snapshot of what existed *before* this effort started — rather than rewritten, since its value now is historical: it's the record of what was actually already working versus what Phases 2–46 genuinely had to build. For the current, as-built state, see `docs/notification-architecture.md` (design/decisions) and `docs/troubleshooting.md` (operational debugging). Specifically: `business-web` notifications (Phase 12), the preference system (Phases 24–25), the idempotency guarantee (Phase 30), the unread-count endpoint (Phase 9), and full deep-link coverage (Phase 27) are all now built and tested — none of the "genuine gaps" named in the headline below remain open.

**Status key:** ✅ already implemented and working · ⚠️ exists but incomplete against this master command's own checklist · ❌ does not exist at all.

**Headline finding:** this is not a greenfield build. A substantial, working notification system already exists — built incrementally across three earlier, differently-numbered protocols referenced in code comments ("Notification Event Integration," "Admin Portal Phase 20/22," "Rider Portal Phase 21," "Live Rider Tracking Phase 34," "Performance & Reliability Phase 39"). In-app notifications, Expo push delivery, and device-token management are all real and running for the Customer and Rider apps today. The genuine gaps are narrower than the full 48-phase command implies: `business-web` has zero notification surface, there is no preferences system, no idempotency key, no unread-count endpoint, and deep-linking only covers two of the notification types actually being sent.

---

## Backend

### Models (✅ exist, ⚠️ incomplete against Phase 3's suggested shape)

**`app/models/notification.py`** — `Notification` (id, user_id, type, title, body, order_id, is_read, created_at) + a 25-value `NotificationType` enum already covering order lifecycle, rider delivery, payment, admin-operational, and promotional events. Indexed on `(user_id, is_read)`.

Missing against Phase 3's suggested field list: `role` (not stored — the recipient's role is implicit from which router served the request, not persisted on the row itself), `channel`, `status`, `data` (JSON — the push payload's `data` dict is constructed ad hoc at each call site and never persisted on the row), `read_at`, `sent_at`, `failed_at`. None of these block Phase 1; they're candidates for Phase 3's own gap-filling, not urgent.

**`app/models/push_token.py`** — `PushToken` (id, user_id, token, platform, created_at), unique on `(user_id, token)`. Missing against Phase 14's suggested shape: `device_identifier`, `is_active`, `last_seen_at`, `updated_at`. A stale/invalid token is currently handled by outright **deletion** (see Push delivery below), not an `is_active` soft-flag — Phase 32 will need to decide whether to keep that behavior or switch to soft-deactivation.

**No preference model exists at all.** Phase 24/25 is a genuine, complete gap — nothing today lets a user opt out of anything short of an admin's platform-wide `notifications_enabled` kill switch (`app/services/admin_settings.py`, `PlatformSettings`).

### Migrations (✅ precedent to follow)

`20260905_01_create_push_tokens.py`, `20260910_04_create_notifications.py`, `20260924_35_create_platform_settings.py` — real, tested migrations already establish the pattern (including the native-enum-value-addition pattern used repeatedly since, e.g. `20261006_49_add_rider_approaching_notification_type.py`) that Phase 4/5 should follow for any new columns/enum values.

### Service layer (✅ substantial, reusable)

**`app/services/notifications.py`** already provides: `upsert_push_token`/`delete_push_token`, `notify_order_placed`, `notify_order_status_change` (a status→notification lookup table, `_ORDER_STATUS_NOTIFICATIONS`), `maybe_notify_rider_approaching` (proximity-triggered, not status-triggered — the model for how a non-status-change event integrates), `notify_riders_of_new_delivery`, `notify_customer_payment_failed`, `notify_admins`, `broadcast_promotion`, `list_notifications`, `mark_notification_read`, `mark_all_notifications_read`. This is functionally most of what Phase 7's "NotificationService" asks for already — it's organized as a module of functions (this codebase's established convention for every service, not a class), not a single `NotificationService` object, which Phase 7 should follow rather than introduce a second style.

**`app/services/push_notifications.py`** — real Expo push integration: `send_push_to_user`, `send_push_to_users`, and `send_push_to_users_in_background` (opens its own DB session, since a request-scoped session can't safely be reused from a `BackgroundTasks` callback). Synchronous HTTP call to `https://exp.host/--/api/v2/push/send` with a 5s timeout; any failure is swallowed (`except Exception: return`) so a push failure never blocks the order/admin action that triggered it (Rule 4 already honored) — but there is **no retry** at all today (Phase 31 gap). A token Expo reports as `DeviceNotRegistered` is deleted outright (Phase 32's "mark inactive" vs. "delete" decision already leans toward delete in the existing code — worth an explicit decision in that phase, not a silent behavior change).

**Idempotency:** ❌ none. Every `notify_*` function just `db.add(Notification(...))` unconditionally — the one exception is `maybe_notify_rider_approaching`, which dedupes by querying for an existing row of that `(order_id, type)` before inserting, the closest thing to a precedent for Phase 30's idempotency key.

### APIs (✅ exist for 3 of 4 roles, ⚠️ missing unread-count)

`app/api/v1/customer/notifications.py`, `.../rider/notifications.py`, `.../admin/notifications.py` — each a thin, near-identical wrapper: `GET /notifications`, `POST /notifications/{id}/read`, `POST /notifications/read-all`, each correctly scoped to `current_user.id` (no IDOR — verified by reading `list_notifications`/`mark_notification_read`'s own `WHERE user_id = :user_id` filters). `app/api/v1/endpoints/notifications.py` — device-token registration (`POST/DELETE /register`), role-agnostic (`CurrentUser`, any authenticated role), owner-scoped.

**Missing:** `GET /notifications/unread-count` (Phase 9 names this explicitly) — today the client computes it by filtering an already-fetched list client-side. No restaurant-owner router at all. No pagination — `list_notifications` is capped at the most recent 100 rows with no cursor, a deliberate simplification noted in its own code comment, not an oversight.

### Existing business events already wired

Order lifecycle (placed/confirmed/preparing/ready/rider_assigned/picked_up/out_for_delivery/delivered/cancelled/rejected), rider proximity (Live Rider Tracking Phase 34), new-delivery broadcast to eligible riders, payment failure, and a range of admin-operational alerts (new restaurant/rider registration, document submitted, order issue, payment failure, COD settlement due) are all real, firing triggers — not aspirational. Phase 8 of this protocol will find most of its "connect notifications to business events" work already done; its job is closing the *remaining* gaps (restaurant-owner events, the promotion/preference interaction), not building the mechanism from scratch.

### WebSocket / realtime infrastructure (✅ exists, but for a different concern)

`app/ws/manager.py`'s `OrderTrackingConnectionManager` (Live Rider Tracking) is a general in-process pub/sub already proven at scale for one order-scoped channel. **Notifications do not use it today** — a `Notification` row's existence is only ever discovered by the client via `GET /notifications` (polled) or the push notification itself arriving. There is no "new notification created" WebSocket event. Phase 2's architecture design should explicitly decide whether in-app notifications need a live push while the app is open (reusing this same manager, a new order-agnostic per-user room) or whether push+poll is judged sufficient — this is a real design decision, not a gap to silently fill.

---

## Customer Mobile (✅ mature)

- `app/notifications.tsx` — full notification center: list, tap-to-navigate (partial, see Deep Linking below), mark-read, mark-all-read, a `TYPE_ICON` map covering every `NotificationType` (kept in sync deliberately, per its own comment, with the backend enum — the same hand-maintained-mirror pattern used elsewhere in this codebase).
- `services/api/notificationsApi.ts` — typed client for every existing endpoint.
- `features/notifications/push-notifications.ts` — real Expo push integration: lazy-loaded (Expo Go on Android dropped remote push support at SDK 53, so the module is never imported there), permission request/grant/deny handling, foreground notification display handler, EAS project ID check, token register/unregister.
- `features/notifications/notification-provider.tsx` — mounted at the app root (`app/_layout.tsx`), wires registration (+ re-registration on token refresh) and deep-link handling for both a cold start (tapped from killed) and a warm tap.

**Gaps found:**
- **Deep linking is incomplete** (❌ for two real, already-firing notification types). `handleDeepLink` only recognizes `data.type === "order_status"` → `/track/[id]` and `"promotion"` → `/home`. But the backend already sends `data.type === "payment_failed"` (`notify_customer_payment_failed`) and `data.type === "rider_approaching"` (`maybe_notify_rider_approaching`) — tapping either of those notifications today does nothing. This is a concrete, evidence-based finding for Phase 27, not speculative.
- **No unread-count badge anywhere outside the notification list itself.** The home screen has a bell icon (`app/home.tsx`) linking to `/notifications`, but it carries no unread-count indicator — confirmed by reading the surrounding JSX, no badge/overlay exists. Phase 9's unread-count endpoint has no current consumer to attach to besides this list screen's own header.

## Rider Mobile (✅ near-identical maturity to customer-mobile)

- `app/(rider)/notifications.tsx`, `services/api/notificationsApi.ts`, `features/notifications/push-notifications.ts`, `features/notifications/notification-provider.tsx` — same architecture, mounted the same way (`app/_layout.tsx`). Client-side unread count computed the same way (list filter, no badge elsewhere).
- No deep-link handler was inspected in as much depth as customer-mobile's for this audit; Phase 11/27 should verify its `handleDeepLink` equivalent covers `NEW_DELIVERY`/`DELIVERY_CANCELLED`/`DELIVERY_UPDATED` the same way customer-mobile's needs fixing for `payment_failed`/`rider_approaching`.

## Business Web (❌ complete gap)

**Zero notification-related files exist** — no API client, no UI, no push (browser notifications or otherwise), nothing. This is the single largest genuine gap in the whole system relative to this master command's stated goal ("Restaurant Owner and Admin can use in-app + browser notifications"). Phase 12 is not incremental work here; it is the first notification code business-web will ever have. `admin-web` (a separate app from `business-web`, per this codebase's own established Admin-Portal/business-web split — see the pinned admin-portal memory) was not inspected in this pass since the master command's own text only names `business-web` under existing apps; confirm before Phase 13 whether admin notifications should land in `admin-web` instead of being newly built into `business-web` on Admin's behalf.

---

## Possible conflicts / things later phases must not accidentally redo

1. **`NotificationType` is a native Postgres enum.** Any new type Phase 5's catalog wants that isn't already in the list above needs an `ALTER TYPE ... ADD VALUE` migration (precedent: `20261006_49_...py`), not a plain model change — forgetting this passes SQLite tests but fails against real Postgres.
2. **Phase 5's example catalog lists `RIDER_ACCEPTED` and `RESTAURANT_NEW_ORDER`/`RESTAURANT_ORDER_CANCELLED`/`RIDER_NEW_ASSIGNMENT`/`RIDER_ASSIGNMENT_CANCELLED` as new types** — the existing enum already has semantically equivalent values under different names (`NEW_DELIVERY` ≈ `RIDER_NEW_ASSIGNMENT`, `DELIVERY_CANCELLED` ≈ `RIDER_ASSIGNMENT_CANCELLED`). Phase 5 should reconcile naming rather than create true duplicates that split one concept across two enum values.
3. **`_notifications_enabled()` is already the platform-wide kill switch.** A new preferences system (Phase 24) needs to compose with this, not replace it — the existing switch should remain the outermost gate.
4. **`send_push_to_users_in_background` already exists** as this codebase's answer to "should notification delivery block the request" — Phase 42's "background processing" phase should audit whether every hot path actually uses this variant (some `notify_*` call sites may still call the synchronous `send_push_to_user`/`send_push_to_users` directly) rather than introducing new infrastructure.
5. **This backend has no task queue/cron of any kind** (confirmed repeatedly across the Live Rider Tracking protocol's own audits) — Phase 42's own instruction ("do not introduce Redis/Celery/Kafka solely for complexity... reuse existing infrastructure") should treat `BackgroundTasks` (already used above) as that existing infrastructure, not a gap to fill with new tooling, unless a specific, evidenced need for true async/retry-with-delay emerges.

---

## Files likely to be modified (not created) by upcoming phases

- `app/models/notification.py` / `app/models/push_token.py` — new columns (Phase 3/14)
- `app/services/notifications.py` — new `notify_*` functions, preference checks (Phase 7/8/18–23/24)
- `app/services/push_notifications.py` — retry logic (Phase 31), stale-token handling (Phase 32)
- `app/api/v1/customer/notifications.py`, `.../rider/notifications.py`, `.../admin/notifications.py` — unread-count route (Phase 9)
- `customer-mobile/features/notifications/notification-provider.tsx` — deep-link map fix (Phase 27, and arguably worth fixing opportunistically whenever that phase is reached, since the gap is already concretely identified here)
- `customer-mobile/app/home.tsx`, rider-mobile's equivalent — unread badge (Phase 26)
- New: an entire `business-web` notification surface (Phase 12) — API client, a notifications view/dropdown, browser Notification API integration

---

## What Phase 1 explicitly did not do

No code was modified. No new files were created besides this document. Every finding above was verified by reading the actual current source, not assumed from a prior phase's memory — several details here (unread-count is client-computed with no badge; the two unmapped deep-link types; business-web's total absence of notification code) required opening files this session had not previously read.
