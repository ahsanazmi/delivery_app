# Live Rider Tracking — Phase 1 Audit

**Date:** 2026-09-29
**Scope:** Full inspection of `backend/`, `customer-mobile/`, `rider-mobile/`, `business-web/` against the 43-phase Live Rider Tracking & Real-Time Delivery master command.

## Headline finding

**Live rider tracking is not a greenfield feature here.** A substantial, working implementation already exists — built earlier as its own prior work item (its code comments reference "Phase 22," "Phase 25" etc. under a numbering scheme that predates both this master command and the separately-completed 36-phase Maps & Location System protocol). Most of what Phases 3–21 of this master command ask for is already built, tested, and running. The real remaining work is concentrated in a smaller set of genuine gaps: **live ETA** (currently a static estimate), **GPS accuracy/impossible-jump filtering**, **explicit stale/live/offline UI state**, **richer tracking-state modeling on the rider side**, **restaurant/admin visibility**, **proximity-triggered notifications**, and **formal docs/observability**.

This changes the shape of every later phase: several will be "extend/hardened what exists" rather than "build from scratch," and a few (e.g. Phase 13, "WebSocket Infrastructure") are effectively already done.

---

## 1. Existing rider assignment implementation

- `DeliveryAssignment` model + `AssignmentStatus` state machine (`PENDING → ACCEPTED/REJECTED → ARRIVED_AT_RESTAURANT → PICKED_UP → OUT_FOR_DELIVERY → DELIVERED`), enforced through a single choke-point transition function in `app/services/rider_deliveries.py` (mirrors `services/orders.py::transition_order_status`'s own `VALID_TRANSITIONS` pattern).
- Order-side lifecycle exactly matches what this master command describes: `PLACED → CONFIRMED → PREPARING → READY_FOR_PICKUP → RIDER_ASSIGNED → PICKED_UP → OUT_FOR_DELIVERY → DELIVERED`, plus `CANCELLED`/`REJECTED`.
- Admin-driven first assignment (`PATCH /api/v1/admin/orders/{id}/assign-rider`) and reassignment both exist, audited (`AdminAuditLog`), reason-required.
- Rider's own accept/reject/pickup/start/complete flow: `/api/v1/rider/deliveries/{id}/{accept|reject|pickup|start|complete}` (granular, replaced an older dual-hop `/orders/{id}/pickup|deliver` pair that was found and removed as dead/rule-bypassing code in a prior security pass).
- `RIDER_ACTIVE_STATUSES = (RIDER_ASSIGNED, PICKED_UP, OUT_FOR_DELIVERY)` — this is the canonical "does this rider have an active delivery" predicate, reused throughout (eligibility, dashboard, location-visibility gating).

## 2. Existing rider GPS/location code

**Backend:**
- `User` model carries a **latest-position cache**: `current_latitude`, `current_longitude`, `current_accuracy`, `current_heading`, `current_speed`, `location_updated_at`.
- `RiderLocationPing` (`app/models/rider_location.py`) is a **throttled history table** — a new row is only inserted when ≥10s (`MIN_LOCATION_PING_INTERVAL_SECONDS`) have passed since the last one for that rider, specifically to prevent unbounded growth from a ~12s foreground reporting interval. Indexed on `(rider_id, recorded_at)`. This already matches this master command's Phase 5/29 privacy intent ("latest location primarily, limited history").
- `app/services/rider_location.py::update_rider_location()` — the de facto `RiderLocationService` this master command's Phase 5 asks for (business logic, not in a route handler): checks eligibility (`_is_eligible_for_location_tracking` — online OR has an active delivery, mirroring the client's own rule as defense in depth), updates the latest-position cache, conditionally inserts a history row, and broadcasts a fresh tracking snapshot to every WebSocket subscriber of every order this rider is actively delivering.
- **Endpoint:** `PATCH /api/v1/rider/location` (`app/api/v1/endpoints/rider.py`), `Depends(require_rider)` — the rider identity comes from the JWT, never from the request body. Payload (`RiderLocationUpdate`) already validates `latitude ∈ [-90,90]`, `longitude ∈ [-180,180]`, `accuracy ≥ 0`, `heading ∈ [0,360)`, `speed ≥ 0` — all optional except lat/lng.
- **Not currently captured:** `altitude`, or a client-supplied `captured_at` timestamp (only the server's own receive time is used) — this master command's Phase 3/6 list both.
- **Not currently implemented:** any impossible-GPS-jump detection, or accuracy-based point rejection (Phase 7/8 territory) — a bad point is stored as-is today.
- **Rejection behavior is a soft no-op, not a hard error:** a call from a rider who's neither online nor has an active delivery is silently ignored (`_is_eligible_for_location_tracking` returns `False` → the function returns the rider's *existing* cached position without writing anything) rather than raising an explicit error. `is_active` (suspended/deactivated accounts) *is* enforced, but at the universal `get_current_user` auth choke-point, not this endpoint specifically. This master command's Phase 6 literally says the endpoint "must reject" ineligible callers — worth deciding explicitly whether soft-no-op is acceptable or whether Phase 6/7 should make this loud.

**rider-mobile:**
- `features/location/use-location-reporter.ts` — foreground-only, one-shot `getCurrentPositionAsync` on a 12s interval (matches the backend's throttle floor with margin), publishes a shared status (`idle | requesting-permission | sharing | denied | error`) via `store/locationTrackingStore.ts` (Zustand) rather than each screen running its own reporter. Requests foreground permission itself; stops immediately when `active` (online-or-has-delivery) flips false.
- `features/location/background-location-task.ts` — `expo-task-manager`-based background tracking (30s / 50m interval — coarser than foreground on purpose, battery-conscious), lazily imports its native dependencies and is a safe no-op under Expo Go or when a prerequisite (foreground permission, background permission) is missing. Foreground-service notification configured on Android already ("Sharing your location while you're online.").
- `features/location/use-tracking-eligibility.ts` — client-side mirror of the same online-or-active-delivery rule, polling the rider dashboard every 60s as a backstop.
- `features/location/device-location.ts` — a **separate**, one-shot, non-transmitting location fetch (5-state result: `granted|denied|denied_permanently|gps_disabled|unavailable`) used only for the delivery map's own "you are here" pin — deliberately distinct from the continuous reporter above.
- **Rider-side tracking state today is exactly the 5 values above** — narrower than this master command's proposed `idle/requesting_permission/permission_denied/starting/tracking/paused/reconnecting/error/stopped` (Phase 10). No distinct `paused`/`reconnecting`/`stopped` states exist client-side; the reporter is binary (running interval or not).
- No dedicated foreground/background-location test coverage beyond what a prior pass could exercise (dynamic `import()` of `expo-task-manager`/`expo-location` isn't supported under this project's Jest/Babel transform — confirmed directly while testing this file for other work; only its degraded/no-op path is currently testable in this environment).

## 3. Existing customer tracking screen & map components

- `customer-mobile/app/track/[id].tsx` — full tracking screen: order timeline, rider info, live map, "Xs/Xm ago" relative freshness label (ticking every 5s), connection-state banner (`connecting`/`reconnecting`), distinct empty states for "no rider yet" vs. "rider assigned, no location yet," cancelled/rejected banner, "Open in Google Maps" fallback deep link (keyless, same pattern as rider-mobile's navigation.ts — no API key involved).
- `customer-mobile/features/tracking/RiderMap.tsx` — MapLibre Native map, distinct rider (orange) vs. delivery (green) pins, camera **eases** to a fresh rider position (`easeTo(..., duration: 800)`) rather than jump-cutting — partial coverage of this master command's Phase 18 ("smooth marker movement"), though it's camera easing, not independent marker interpolation, and there's no explicit "don't keep moving if stale" guard yet.
- **No explicit LIVE/STALE/OFFLINE state exists anywhere in the UI** — the relative-time label is purely informational text; nothing changes color/behavior once a position is old, and a stale coordinate is displayed exactly like a fresh one. This is this master command's Phase 19, genuinely not done yet.

## 4. Existing order tracking APIs

- `GET /api/v1/customer/orders/{order_id}/tracking` (REST) — ownership-checked (`get_user_order`), used both for a manual "retry" and as the **polling fallback** while the socket is down.
- `WS /api/v1/customer/ws/orders/{order_id}` — see §5.
- Both are backed by the same `build_tracking_snapshot()` (`app/services/tracking_snapshot.py`), so REST and WebSocket payloads are always shape-identical.
- `LOCATION_VISIBLE_STATUSES = {RIDER_ASSIGNED, PICKED_UP, OUT_FOR_DELIVERY}` — this **is** already this master command's "trackable order states" list from its introduction, word for word.
- `estimated_delivery_at` today is `order.created_at + a restaurant's own fixed delivery_time_minutes` (or a 45-minute platform default) — a **static** estimate, not derived from the rider's live position or a route calculation at all. This master command's Phases 22–24 (Live ETA) are genuinely new work.

## 5. Existing WebSocket infrastructure

- `app/ws/manager.py::OrderTrackingConnectionManager` — an in-process, order-scoped connection registry (`dict[order_id, set[WebSocket]]`). `broadcast()` is callable from synchronous service code off the event-loop thread (`asyncio.run_coroutine_threadsafe`, with a strong reference held until each send completes so a broadcast is never silently GC'd mid-flight). Its own docstring already documents the scaling path: swap this class for a Redis-pub/sub-backed one later without touching any caller — this master command's Phase 35's "design so Redis can be introduced later" is already satisfied by construction.
- **Authenticated by construction** — the socket handler decodes the JWT from a `?token=` query param (the one auth transport every client, including React Native's WebSocket and `wscat`, can actually set), re-checks `is_active` and role, then separately proves order ownership via `get_user_order(db, user_id, order_id)` before ever calling `websocket.accept()`. An unauthenticated, wrong-role, or non-owning connection is closed with a distinct code (4401/4404) before ever joining the broadcast group.
- Sends a **full snapshot immediately on connect** (before waiting for any future event) — this already satisfies this master command's Phase 21 ("don't depend exclusively on the WebSocket for the initial state"), just via a different mechanism (an immediate push on the same socket) than the literal "REST GET + WS" pattern the phase describes.
- Lightweight `ping`/`pong` keepalive already implemented at the message level.
- Broadcasts only fire for orders whose status is in `LOCATION_VISIBLE_STATUSES` — a location update on a `DELIVERED`/`CANCELLED` order's now-closed connection is a structural non-event, not something requiring separate cleanup logic (Phase 28's "stop on terminal status" is mostly free here, though see §9 for one open question).

**customer-mobile client side** (`features/tracking/use-order-tracking.ts`):
- Connects, and on `onclose` starts an exponential-backoff reconnect (1s → capped 15s) **and** falls back to 15s REST polling for as long as the socket stays down — the socket, once reconnected, takes back over and polling stops.
- Detects terminal order statuses client-side and stops reconnecting entirely once reached (`stoppedRef`).
- This is already almost all of this master command's Phase 20 (Reconnection Handling).

## 6. Existing notification infrastructure

- `app/services/notifications.py` — `notify_order_placed`, `notify_order_status_change` (fires on every order status transition, which already covers "rider assigned," "picked up," "delivery completed" in spirit, since those map to order-status changes), `notify_riders_of_new_delivery`, `notify_admins`.
- **Not present:** any notification triggered by rider *proximity* (e.g. "rider is approaching," within N meters of the destination) — this genuinely requires new logic tied to live GPS + distance-threshold evaluation, not just an order-status hook. This master command's Phase 34 names this specific example explicitly.

## 7. Existing Google Maps integration

**None.** Confirmed via a full-repo sweep earlier in this project's history: every map (customer address picker, live tracking, business-web restaurant location, admin-web location views, rider-mobile's new delivery map) runs on MapLibre Native/GL JS + CARTO's free Voyager style; geocoding runs on Photon; routing runs on OSRM. The only Google-domain reference anywhere is a **keyless** `google.com/maps/dir` / `google.com/maps/search` deep link used as an "open in your installed maps app" fallback (both customer-mobile's tracking screen and rider-mobile's navigation service) — this requires no API key and incurs no billing, so it does not conflict with this master command's later phases about Routes-API cost control; there is no Google Routes API in use to control the cost of.

## 8. Existing authentication dependencies

- `get_current_user` — the single choke point (decodes JWT, loads the user, rejects if missing/inactive) every authenticated route and the WebSocket handler both funnel through.
- `require_rider`, `require_customer`, `require_admin`, `require_roles(*roles)` — ready-made or factory dependencies layered on top.
- Nothing rider-location-specific bypasses this; `/rider/location` uses `Depends(require_rider)` like every other rider endpoint.

## 9. Existing database models

- `Order` (full lifecycle + immutable delivery-location snapshot, from the just-completed Maps & Location work), `DeliveryAssignment`, `User` (latest-position cache columns), `RiderLocationPing` (throttled history). No new "latest rider location" model is needed per this master command's Phase 3 — the cache already lives on `User`, and a history table already exists in the exact shape Phase 3 sketches (`rider_id`, lat/lng, accuracy/heading/speed, `recorded_at`), missing only `assignment_id`/`order_id` foreign keys, `altitude`, and a separate `captured_at` (client) vs. `received_at` (server) distinction — currently only one timestamp (`recorded_at`, server-assigned) exists.
- **Open question for a later phase:** `RiderLocationPing` has no FK back to `order_id`/`assignment_id` at all — it's purely per-rider. If a rider is reassigned mid-shift, history rows don't distinguish which delivery they belonged to. Whether that granularity is actually needed depends on what "limited history when genuinely required" (this master command's own Phase 29 privacy rule) ends up being used for.

## 10. Existing service layer

Already follows the same "business logic in `services/`, thin route handlers" convention this master command's rules require — confirmed throughout `rider_location.py`, `tracking.py`, `tracking_snapshot.py`, `orders.py`, `rider_deliveries.py`. No route handler touched during this audit contained business logic directly.

## 11. Existing tests

Substantial, already-passing coverage directly on point:
- `test_rider_location.py` (7 tests) — role gate, store-and-return happy path, out-of-range coordinate rejection, the online/active-delivery no-op rule (both directions), and the throttle window (both under and over it).
- `test_customer_tracking.py` (9 tests) — visibility before/after assignment, before/after a rider actually reports a position, hidden again after delivery completes, full status-history reflection, cross-customer isolation, one HTTP-level smoke test.
- `test_customer_tracking_ws.py` (7 tests) — no-token rejection, deactivated-user rejection, invalid-token rejection, wrong-owner rejection, initial-snapshot-on-connect, broadcast-on-status-change, and — critically — proof that rider location is only broadcast once the order actually reaches a visible status, not before.
- `test_integration_customer_order_tracking.py` (1 test) — full lifecycle + a second customer locked out, as an integration-level check.
- Plus tracking/rider-location references inside several broader E2E and role-isolation test files.

This is already most of this master command's own Phase 30 (Security/IDOR Audit) and a meaningful chunk of Phase 36 (Automated Testing) for the backend side. Frontend-side (customer/rider) automated tests for the *tracking-specific* behavior (reconnection, stale detection, marker updates) are thinner — `RiderMap.test.tsx` exists and covers marker rendering/camera easing, but there's no test today for `use-order-tracking.ts`'s reconnect/backoff/polling-fallback logic specifically.

---

## What genuinely needs to be built (by future phase)

This list is what actually remains net-new, mapped to this master command's own phase numbers — everything not listed here is either fully done or would be a refinement of something that already exists:

| Phase | Gap |
|---|---|
| 3/4 | `altitude`, client `captured_at` vs. server `received_at` distinction not modeled; `RiderLocationPing` has no `order_id`/`assignment_id` FK |
| 6/7 | Ineligible-caller rejection is a silent no-op, not an explicit error; no configurable min-interval/min-distance/max-accuracy thresholds exposed as settings (the 10s throttle is hardcoded) |
| 8 | No impossible-GPS-jump detection, no accuracy-based point filtering at all |
| 10 | Rider-side tracking state is 5 values (`idle/requesting-permission/sharing/denied/error`); this master command's richer set (`paused/reconnecting/stopped` as distinct states) doesn't exist |
| 12 | No formally shared/typed realtime event contract document (the shape exists and is consistent, just not documented as a contract) |
| 18/19 | No explicit LIVE/STALE/OFFLINE UI state or threshold; marker movement uses camera easing only, no independent interpolation or "stop moving when stale" guard |
| 22–24 | Live ETA — today's estimate is static (creation time + fixed minutes), never derived from the rider's actual live position or a route calculation |
| 25/26 | Rider-side "GPS accuracy / weak signal / reconnecting" UI states don't exist yet on the delivery screen |
| 27 | No restaurant/admin-facing live rider location view exists at all today (this is new surface, not a hardening of existing surface) |
| 29 | No documented retention policy for `RiderLocationPing` (it's already minimal/throttled by construction, but nothing is written down) |
| 33 | The existing polling fallback is customer-side only; no rider-side fallback exists (not yet needed, since rider→backend is a plain HTTP PATCH already, not itself WebSocket-dependent) |
| 34 | No proximity-triggered ("rider is approaching") notification |
| 39 | No structured logging for tracking-specific events (`tracking_started`, `location_rejected`, etc.) — today's logging is generic warning-level auth/error logging only |
| 42 | No `docs/live-tracking-architecture.md` or `docs/location-privacy.md` yet (this audit is the first doc in that set) |

## Files inspected (not modified — per this phase's own "DO NOT modify unrelated modules" instruction)

Backend: `app/ws/manager.py`, `app/services/{tracking,tracking_snapshot,rider_location,rider_deliveries,orders,notifications}.py`, `app/models/{rider_location,order,user,delivery_assignment}.py`, `app/schemas/{rider,tracking}.py`, `app/api/v1/customer/tracking.py`, `app/api/v1/endpoints/rider.py`, `app/api/v1/deps.py`, `tests/test_{rider_location,customer_tracking,customer_tracking_ws,integration_customer_order_tracking}.py`.

customer-mobile: `features/tracking/{use-order-tracking,RiderMap,map-tile-config}.ts(x)`, `app/track/[id].tsx`.

rider-mobile: `features/location/{use-location-reporter,background-location-task,use-tracking-eligibility,device-location,DeliveryMap,map-tile-config}.ts(x)`, `store/locationTrackingStore.ts`, `app/(rider)/delivery/[id].tsx`, `services/navigation.ts`.

## Blockers

None. No missing prerequisite, no ambiguous existing behavior that blocks starting Phase 2 — the one open design question worth resolving explicitly before or during a later phase is the "silent no-op vs. explicit rejection" behavior noted in §2/§6, since Phase 6 of this master command asks for the endpoint to actively reject ineligible callers.
