# Troubleshooting

A developer-facing guide for diagnosing the common ways this platform's realtime systems can appear broken, cross-referenced to where the actual behavior lives in code. Two sections: **Live Rider Tracking** below, and **Notifications & Communication System** further down. See `docs/live-tracking-architecture.md` / `docs/notification-architecture.md` for the design these symptoms are being checked against, and `docs/location-privacy.md` for what's deliberately never exposed (don't "fix" those by exposing more than intended).

## Live Rider Tracking

## Customer sees no rider position at all

Rider location is deliberately withheld outside a specific window — this is very often correct behavior, not a bug:

1. **Order status isn't location-visible yet.** Rider location only ever appears while `order.status` is `RIDER_ASSIGNED`, `PICKED_UP`, or `OUT_FOR_DELIVERY` (`LOCATION_VISIBLE_STATUSES`, `app/services/tracking_snapshot.py`). Before a rider is assigned, or once the order is delivered/cancelled, `rider_location` is `null` by design.
2. **The rider has never reported a position.** Check `User.current_latitude`/`location_updated_at` for that rider directly. A rider who is online but hasn't opened the app since accepting the delivery, or whose foreground permission was denied (`permission-denied` state in `locationTrackingStore`), has nothing to report yet.
3. **The rider's report was rejected, not just delayed.** Check the backend logs for `event=location_rejected` (Phase 39) with a `reason` of `ineligible`, `implausible_movement`, or `implausible_timestamp` — see the matching sections below.

## "Location rejected" / `location_rejected` in the logs

The `reason` field tells you which of three independent checks failed (`app/services/rider_location.py`):

- **`ineligible`** — the rider is neither online (`DeliveryPartner.is_online`) nor holding an active delivery (`RIDER_ACTIVE_STATUSES`). The client should stop its own reporting loop on a 403 here, not retry blindly.
- **`implausible_movement`** — poor accuracy (over `RIDER_LOCATION_MAX_ACCEPTED_ACCURACY_METERS`) *and* an implausible implied speed (over `RIDER_LOCATION_MAX_PLAUSIBLE_SPEED_MPS`) both held at once. Deliberately conservative — a real highway trip or a single noisy point alone should never trigger this; if it does, check whether the two thresholds need retuning for the actual delivery radius/vehicle mix in your market (`.env.example`).
- **`implausible_timestamp`** — the device's `captured_at` was further from the server's own clock than `RIDER_LOCATION_MAX_TIMESTAMP_AGE_SECONDS`/`_FUTURE_SECONDS`. Usually a genuinely wrong device clock; check the specific rider's device settings before assuming a bug.

## Rider position shows as "Delayed" or "Unavailable" (STALE/OFFLINE)

This is `determine_rider_location_state()` (`app/services/rider_location.py`) computed purely from `location_updated_at`'s age against `RIDER_LOCATION_STALE_AFTER_SECONDS` (30s) / `RIDER_LOCATION_OFFLINE_AFTER_SECONDS` (120s) — it does not mean the update was rejected, only that it's aging. Confirm the rider's own device is actually still reporting (rider-mobile's status banner shows its own `tracking`/`reconnecting`/`stopped` state) before assuming a backend issue.

## ETA is missing, or stuck on the static estimate

`eta_source` in the tracking response tells you which formula produced `estimated_delivery_at`:

- **`"static"`** — the plain creation-time + `restaurant.delivery_time_minutes` formula. Expected whenever `rider_location` is `null`, or the routing provider (OSRM) has never successfully answered for this order yet.
- **`"live"`** — a real OSRM route. Only recomputed once the rider has moved `LIVE_ETA_MIN_MOVEMENT_METERS` (300m) or `LIVE_ETA_MIN_REFRESH_SECONDS` (60s) has passed since the last calculation *for that order* — a value that looks "stuck" for under a minute while the rider is barely moving is expected, not a bug.
- **`"unavailable"`** — only returned when no estimate, live or previously cached, exists at all; the frontend's `deriveEtaDisplayState` additionally forces `"unavailable"` display whenever `rider_location.state !== "live"`, regardless of `eta_source` (never present a stale-position-derived ETA as current).

If ETA never goes live even with the rider actively reporting, check `OSRM_API_BASE_URL` is reachable and confirm the order's delivery address actually has `latitude`/`longitude` set (an address without coordinates makes `get_live_eta` return early — see `app/services/eta.py`).

## WebSocket won't connect / closes immediately

The close code tells you which check failed, before the server ever calls `accept()` (`app/api/v1/customer/tracking.py`):

- **4401** — no `?token=`, an invalid/expired token, or the token decodes but the user is deactivated/not a customer.
- **4404** — the order doesn't exist, or exists but isn't owned by this token's user (the same "never leak that it exists" pattern used everywhere else in this codebase — a wrong-owner attempt looks identical to a nonexistent order).

Check the backend logs for `event=subscription_rejected` with a `reason` field distinguishing these (Phase 39) — never the token value itself, which is never logged anywhere on this path.

## WebSocket connects but then goes quiet / customer stuck on "Reconnecting…"

- If the *order itself* reached a terminal status, this is by design — the server closes the room (§28 in the architecture doc) and the client is supposed to recognize `TERMINAL_ORDER_STATUSES` and stop treating that as a failure (`use-order-tracking.ts`). A customer stuck showing "Reconnecting…" for an order that's actually DELIVERED/CANCELLED is a real bug in that recognition, not in the backend.
- Otherwise, confirm the customer's own device actually has network connectivity — the REST-polling fallback (§16) should already be covering for this; if `tracking` data is also stale in the poll response, the backend itself is the problem, not the socket.

## "429 Too Many Requests"

Three tracking-surface endpoints are rate-limited (`app/core/rate_limit.py`, Phases 33/35/40): the rider's own `PATCH /rider/location` (30/60s, keyed per rider), and the customer's `GET /orders/{id}/tracking` poll (30/60s, keyed per customer — shared across all of that customer's simultaneously-active orders, not per order). Hitting this in normal use means a client is reporting/polling far faster than its own designed interval (12s for the rider, 15s for the customer's fallback poll) — look for a retry loop that isn't backing off, not a limit that needs raising.

## A delivery completed, but the rider's earning or assignment status looks wrong

This should be structurally impossible by design (Phase 32) — `transition_order_status` (the single choke point for every order status change) commits the status change *before* running its own tracking broadcast, and wraps that broadcast in a failure-isolation guard so a tracking-layer exception can never abort a caller's remaining side effects (assignment status, `record_delivery_fee_earning`). If you see this, check `event=tracking_error` in the logs first — a *repeated* failure there (not just tracking never actually recovering) would indicate something new broke the isolation guarantee itself, which is a real regression worth escalating rather than working around.

## Rider's live position stops updating once they background the app

Check `checkBackgroundLocationAvailability()` (`rider-mobile/features/location/background-location-task.ts`) for that rider's device — background tracking is real and additive (§11/§17 in the architecture doc), but it silently does nothing (never surfaces an error) when: the app is running in Expo Go (background tasks require a real dev/standalone build), the rider never granted background permission (foreground-only tracking still works fine in this case — this is expected, not a bug), or — the one genuine known gap (§11) — the OS hard-killed the process (a user force-stop, or an aggressive OEM battery manager) rather than merely backgrounding it, which drops the registered task until the rider reopens the app. A persistent "Sharing your location while you're online" notification should be visible on the rider's device whenever background tracking is actually active; its absence while the rider believes they're online is the fastest way to tell which of the above applies.

## Android build issue: an unexpected *absence* of the "Allow all the time" location prompt

Background tracking is a real, intentional feature here (§11/§17), not an oversight — `rider-mobile/app.json`'s `expo-location` plugin config deliberately declares `locationAlwaysAndWhenInUsePermission`/`isAndroidBackgroundLocationEnabled`/`isAndroidForegroundServiceEnabled` alongside the foreground `locationWhenInUsePermission`. If a build stops prompting for background access at all, check that plugin block hasn't been trimmed back down to foreground-only.

---

# Notifications & Communication System — Troubleshooting

See `docs/notification-architecture.md` for the design these symptoms are being checked against.

## A user isn't receiving push notifications at all

Work through this in order — most "no push" reports are one of the first three, not a backend bug:

1. **Permission was never granted, or was denied once.** Check `Notifications.getPermissionsAsync()` on that device. `registerForPushNotifications()` (both mobile apps' own `features/notifications/push-notifications.ts`) only ever calls `requestPermissionsAsync()` once, when status is `"undetermined"` — a prior denial is never re-prompted (Phase 28), so a user who denied it once has to re-enable it from the OS's own app settings; there's no in-app way to force a second prompt, by design.
2. **No `EAS project id` configured.** `registerForPushNotifications()` logs `"no EAS project id configured"` and returns `null` without ever calling Expo's token API — check `expoConfig.extra.eas.projectId` (`npx eas init`).
3. **Running in Expo Go.** `expo-notifications` throws synchronously in Expo Go on Android since SDK 53 — both apps load it lazily and no-op entirely rather than crash (`getNotificationsModule()`); a real dev/standalone build is required to actually receive a push.
4. **The device's token is deactivated.** Check `PushToken.is_active` for that user — `false` means Expo itself already reported `DeviceNotRegistered` for it (Phase 32), and it will never be sent to again until the same device re-registers (its `device_identifier` reviving this same row, not creating a new one).
5. **Platform-wide kill switch.** `PlatformSettings.notifications_enabled` — an admin may have turned this off entirely (`GET /admin/settings`).
6. **The recipient turned the category off.** `GET /api/v1/notifications/preferences` for that user — check the specific category the event maps to (`_NOTIFICATION_CATEGORY` in `app/services/notifications.py`), not just whether notifications are "on" in general.

## `event=notification_failed` / `event=notification_retry` in the logs

- **`notification_failed` from `_notification_failure_boundary`** (with a `reason=<ExceptionType>` field) — the notify_* function's own DB-write-plus-dispatch crashed outright (a bug, or the database itself briefly unavailable). The business operation that triggered it is unaffected either way (Phase 7's SAVEPOINT isolation) — this is a delivery-layer problem to investigate, never a reason the triggering order/payment/COD action should be suspected of having failed too.
- **`notification_failed` from `push_notifications.py`** (with a `count=` field, no `reason=`) — the provider itself reported one or more messages as failed after all retries were exhausted. Check the paired `notification_retry` lines immediately before it for the actual cause (`reason=request_error` or `reason=http_<code>`).
- **A token repeatedly shows up in `push_token_invalid`** — that's Expo authoritatively saying the token is dead (`DeviceNotRegistered`), not a transient issue; the row is deactivated (never deleted, Phase 32) and will correctly never be sent to again.

## "I disabled a notification category but still got notified"

Two things to check before assuming it's a bug:

1. **`ACCOUNT_APPROVED`/`ACCOUNT_SUSPENDED` are never preference-gated at all**, deliberately — see §5/§13 of the architecture doc. A rider cannot silence whether they can work.
2. **Admin operational alerts (`notify_admins`) are never preference-gated either.** An admin's own feed only has the platform-wide kill switch, never a personal per-category toggle — these are job-function alerts, not a personal preference.

If neither applies, check `_NOTIFICATION_CATEGORY` (`app/services/notifications.py`) maps the specific `NotificationType` involved to the category the user actually disabled — the mapping is deliberately not 1:1 with every type name (e.g. all order-lifecycle types share `order_updates`).

## A rider's notification history is growing without bound / an old notification disappeared unexpectedly

- **Growing without bound** — `purge_old_notifications` (Phase 34) isn't scheduled anywhere (this codebase has no background-job system, see §10) — it has to be triggered, today, via `POST /api/v1/admin/notifications/cleanup`. If nobody's calling that, the table will keep growing exactly as expected.
- **An old notification disappeared** — read notifications are purged after 90 days; unread ones after 365. Check `is_read`/`created_at` against those windows (`_NOTIFICATION_RETENTION_DAYS_READ`/`_UNREAD`) before assuming data loss — an unread notification inside the 365-day window is never touched regardless of age past 90 days.

## Admin alerts seem to be "missing" during a known incident (e.g. a payment provider outage)

This is very likely the intended aggregation (Phase 33), not a bug: an admin who already has a recent (5-minute window), still-unread alert of the exact same `NotificationType` gets that one row updated in place (an occurrence count folded into the body) instead of a second row and a second push. Check that admin's own existing notification of that type for an "(`N` similar alerts since you last checked)" suffix before assuming events were dropped — they weren't; they were folded in. Reading the alert (or waiting out the 5-minute window) lets the next genuine occurrence start fresh again.
