# Live Rider Tracking — Architecture

**Status key used throughout this document:** ✅ already implemented and running · 🆕 proposed here, not yet built (a later phase's job).

This document designs the live tracking architecture *around* the existing implementation identified in `docs/live-tracking-audit.md`, rather than describing a system built from scratch. Where a decision already exists in code, it's documented as the standing design, not re-litigated. Where this master command asks for something that doesn't exist yet (stale-state thresholds, live ETA), a concrete proposal is made here so later phases have a specific target to implement against, not a vague direction.

---

## 1. End-to-end pipeline

```text
Rider Mobile (GPS)                                          ✅
     │  getCurrentPositionAsync, foreground, ~12s interval
     ▼
Location validation                                          ✅ (range/type) 🆕 (jump/accuracy filtering — Phase 8)
     │  RiderLocationUpdate: lat ∈[-90,90], lng ∈[-180,180],
     │  accuracy/heading/speed bounds; eligibility gate
     │  (online OR active delivery)
     ▼
Latest location storage                                      ✅
     │  User.current_latitude/longitude/accuracy/heading/
     │  speed/location_updated_at (the read path for every
     │  consumer below) + a throttled RiderLocationPing
     │  history row (≥10s apart)
     ▼
Realtime event                                                ✅
     │  build_tracking_snapshot() → the same payload shape
     │  REST and WebSocket both return
     ▼
Authenticated WebSocket                                       ✅
     │  /api/v1/customer/ws/orders/{order_id}
     │  JWT via ?token=, is_active + ownership re-checked
     │  before accept()
     ▼
Customer active-order tracking                                ✅
     │  OrderTrackingConnectionManager — broadcasts only to
     │  sockets subscribed to that specific order_id
     ▼
Live map                                                      ✅ (rendering) 🆕 (stale/live/offline state — Phase 19)
        RiderMap.tsx — MapLibre, eased camera movement
```

## 2. Update frequency

| Layer | Interval | Status |
|---|---|---|
| Rider foreground GPS read | ~12s (`REPORT_INTERVAL_MS`, `use-location-reporter.ts`) | ✅ |
| Rider background GPS read | 30s / 50m, whichever first (`BACKGROUND_TIME_INTERVAL_MS`/`BACKGROUND_DISTANCE_INTERVAL_METERS`) | ✅ |
| Minimum gap between *history* rows | 10s (`MIN_LOCATION_PING_INTERVAL_SECONDS`) — the latest-position cache still updates on every accepted call regardless | ✅ |
| Customer polling fallback (socket down) | 15s (`POLL_INTERVAL_MS`) | ✅ |
| Rider eligibility re-check (online/active-delivery) | 60s backstop poll (`ELIGIBILITY_POLL_INTERVAL_MS`) — most transitions push their own refresh immediately instead of waiting for this | ✅ |

The foreground interval (12s) intentionally sits just under the backend's read-side needs while comfortably clearing the 10s history floor with margin, so a foreground report is essentially never thrown away by the throttle purely due to timer jitter.

## 3. Throttling

**Today (✅):** a single hardcoded floor — `MIN_LOCATION_PING_INTERVAL_SECONDS = 10` — gates only whether a *history* row is written; the latest-position cache on `User` always updates. There is no minimum-movement-distance or maximum-accepted-accuracy check anywhere yet, and the 10s figure is a Python constant, not an environment/config value.

**Proposed for Phase 7 (🆕):** promote the relevant numbers to `app/core/config.py` settings (matching the pattern `PHOTON_API_BASE_URL`/`OSRM_API_BASE_URL` already established for other tunables), specifically:
- `RIDER_LOCATION_MIN_INTERVAL_SECONDS` (default 10 — keep today's value, just make it configurable)
- `RIDER_LOCATION_MIN_MOVEMENT_METERS` (default ~15m — below this, a new point this soon after the last one is redundant for a moving vehicle's granularity)
- `RIDER_LOCATION_MAX_ACCEPTED_ACCURACY_METERS` (default ~100m — beyond this the reported position is more noise than signal; see §4)

## 4. GPS accuracy / impossible-jump filtering (🆕 — Phase 8)

Not implemented today. Proposed conservative rule, applied in `update_rider_location()` before writing anything:

```text
reject the point only when ALL of:
  accuracy is worse than RIDER_LOCATION_MAX_ACCEPTED_ACCURACY_METERS
  AND
  implied speed since the last accepted point > a generous ceiling
    (implied_speed = distance(prev, new) / elapsed_seconds;
     ceiling ~55 m/s / ~200 km/h — well above any real delivery vehicle,
     deliberately loose so normal traffic/highway movement is never
     mistaken for a jump)
```

Both conditions together, not either alone — a single poor-accuracy point from a stationary rider must not be rejected just because accuracy is bad; a huge jump with *good* accuracy (a real teleport-class GPS glitch, or a genuinely impossible movement) should still be rejected on its own. Distance uses the same `LocationService.distance_km` helper already used elsewhere (straight-line is appropriate here — this is a plausibility check, not a routed-distance calculation). A rejected point is dropped silently from the rider's perspective today (no error surfaced) but logged (`location_rejected`, see `docs/live-tracking-architecture.md` §11 / the future Phase 39 observability work) so a pattern of rejections is visible operationally.

## 5. Stale-location rules (🆕 — Phase 19)

Not implemented today (the customer tracking screen shows a plain "Xs ago" label with no threshold behavior). Proposed three-state model, computed client-side from `rider_location.updated_at` against wall-clock time (no new backend field needed — the timestamp already round-trips):

```text
LIVE     age < 30s   — normal display, marker updates as usual
STALE    30s–120s    — a visible (but not alarming) "last seen Xs ago"
                        indicator; marker stays in place, stops easing
                        to new positions if one arrives with this label
                        already showing staleness resolving on its own
                        once a fresh point lands
OFFLINE  > 120s       — explicit "rider location unavailable right now"
                        state; the marker is not removed (the rider is
                        still presumably en route) but is visually
                        de-emphasized, and the ETA (§9) must not claim
                        freshness it doesn't have
```

These three thresholds are proposed values, meant to be implemented as constants in the tracking hook (`use-order-tracking.ts` or a new small helper), not hardcoded per-component.

## 6. Reconnect behavior

**Today (✅), customer side:** `use-order-tracking.ts` reconnects on `onclose` with exponential backoff (`1000ms × 2^attempt`, capped at 15000ms), and runs the 15s REST poll as a safety net for exactly as long as the socket is down — the moment the socket reconnects (`onopen`), polling stops and the socket becomes authoritative again. Reconnection attempts stop permanently once a terminal order status (`DELIVERED`/`CANCELLED`/`REJECTED`) is observed, since nothing will ever change again.

**Not yet covered:** app-backgrounded/resumed transitions aren't handled explicitly (React Native's WebSocket typically survives a brief background/foreground cycle, but there's no explicit `AppState` listener forcing a reconnect check on resume) — worth a small addition when Phase 20 is revisited, not a redesign.

**Rider side:** there is no WebSocket on the rider side at all — `PATCH /rider/location` is a plain, stateless HTTP call on a fixed interval, so "reconnection" there just means the next scheduled interval tries again; a single failed PATCH is not retried out-of-band today (Phase 33/38 territory).

## 7. Battery considerations

- Foreground tracking only runs while `active` (online OR has an active delivery) is true — a rider who goes offline or finishes their last delivery stops the interval immediately (`use-location-reporter.ts`'s own cleanup on `active` flipping false).
- `Accuracy.Balanced` (not `.High`/`.BestForNavigation`) is used for every GPS read, foreground and background — deliberately not the most battery-expensive accuracy tier.
- Background tracking uses a coarser interval (30s/50m vs. foreground's 12s) specifically because, per its own code comment, "background GPS is one of the most battery-expensive things a phone can do" and there's no UI to keep fresh while backgrounded.
- Background tracking additionally requires its own separate permission grant and is a no-op wherever unavailable (Expo Go, permission declined) — a rider who declines background permission still gets full foreground tracking; this is additive coverage, never a hard requirement.

## 8. Security boundaries

- **Rider identity is never client-supplied.** `PATCH /rider/location` resolves the rider from `Depends(require_rider)` (JWT → `User`); the function signature `update_rider_location(db, rider, latitude, longitude, ...)` has no `rider_id` parameter for a client to point elsewhere even if it wanted to.
- **Order/customer ownership is re-checked, not assumed, at every access point:** the REST tracking endpoint (`get_user_order(db, user_id, order_id)`) and the WebSocket handler (the same check, before `accept()`) both independently verify the connecting user actually owns the order — proven by dedicated tests (`test_ws_rejects_order_owned_by_another_customer`, `test_customer_cannot_track_someone_elses_order`).
- **Deactivated/suspended accounts are rejected universally** at `get_current_user`, the one choke point every authenticated route (including the WebSocket) passes through — not a tracking-specific check, but tracking inherits it for free.
- **Rider location is broadcast only to sockets already subscribed to that specific order** (`OrderTrackingConnectionManager`, keyed by `order_id`) — there is no global broadcast path, and a location update for order A structurally cannot reach a socket connected to order B.

## 9. Privacy rules

- **Latest-position-first, not history-first:** every read path (available-deliveries distance, the customer tracking snapshot) reads `User.current_latitude/longitude`, never `RiderLocationPing`. The history table exists only as a durable, low-frequency ledger, already throttled to ≥10s apart specifically to avoid unbounded growth.
- **No customer access to raw history** — the customer-facing tracking response (`OrderTrackingResponse`/`RiderLocation`) carries only the *current* rider position, never a list of past points. There is no endpoint today that returns `RiderLocationPing` rows to anyone.
- **Time-boxed visibility** — a rider's location is only ever included in a tracking snapshot while the order is in `{RIDER_ASSIGNED, PICKED_UP, OUT_FOR_DELIVERY}`; before assignment there's nothing to show, and after delivery/cancellation it reverts to hidden even though the `User.current_*` cache itself isn't cleared (the *gating*, not the data, is what changes — proven by `test_rider_location_hidden_again_after_delivery`).
- **No restaurant/admin visibility exists yet (🆕 — Phase 27).** When it's built, it must reuse this same time-boxed gating (an operational "where is this delivery right now" view during an active order, not an unrestricted live-location dashboard) and must not additionally expose raw `RiderLocationPing` history without a stated operational reason, per this master command's own Phase 29 rule.
- **Retention policy is currently undocumented** (🆕 — a genuine gap, flagged in the audit; `docs/location-privacy.md` doesn't exist yet and is explicitly this master command's Phase 29 deliverable).

## 10. ETA refresh strategy (🆕 — Phases 22–24)

**Today:** `estimated_delivery_at = order.created_at + restaurant.delivery_time_minutes` (or a 45-minute platform default) — computed once, at snapshot-build time, never adjusted for the rider's actual position. This is not "live ETA" in any sense; it's a static estimate that happens to be recomputed (identically) on every snapshot build.

**Proposed design for when Phase 22 is implemented:**
- ETA becomes `now + route(rider_current_position → order.delivery_location).duration_minutes`, using the already-built `location_service.route()` (OSRM-backed, Phase 17 of the completed Maps & Location protocol) — reusing that exact function, not a new routing integration.
- **Refresh triggers**, combined (matching this master command's own Phase 24 rule almost verbatim — no new rule needed, just an implementation target):
  - the rider has moved more than a threshold distance since the last ETA calculation (proposed: 300m — enough to meaningfully change a route, not so little that ordinary GPS noise triggers a recalculation), **or**
  - a minimum time has elapsed since the last calculation (proposed: 60s), **or**
  - the order transitions between trackable statuses (e.g. `PICKED_UP → OUT_FOR_DELIVERY`), since the effective destination/leg of the trip changes at that point.
- **Never** recalculate on every single GPS ping — this is precisely the OSRM-quota concern Phase 27 of the *already-completed* Maps & Location protocol built caching/throttling to protect against; live ETA must respect the same discipline, not bypass it.
- The backend remains authoritative — the ETA value is computed and stored/broadcast server-side (inside `build_tracking_snapshot()`, gated by the same throttle rule above), never computed client-side from a raw rider position the client itself already has.
- **ETA staleness (Phase 23):** if the rider's own location is `STALE`/`OFFLINE` (§5), the ETA must be labeled accordingly ("Updating…" / "Temporarily unavailable") rather than silently continuing to show a number computed from a now-old position.

---

## 11. Background location — Android platform limitations

Background rider tracking already exists (`rider-mobile/features/location/background-location-task.ts`, predating this master command) and is genuinely required by the delivery workflow in the narrow sense this phase means: a rider whose screen is off or app is backgrounded mid-delivery must still be findable, since customer tracking depends on `User.current_latitude/longitude` staying fresh regardless of what the rider's phone is doing. It is **not** required outside an active delivery, and the existing implementation already respects that — it starts/stops in lockstep with the exact same `active` (online-or-has-a-delivery) signal the foreground reporter uses, never running unconditionally.

**Android permissions (✅ verified correct):** `app.json`'s `expo-location` plugin config (`isAndroidBackgroundLocationEnabled: true`, `isAndroidForegroundServiceEnabled: true`) causes the installed plugin (`expo-location@57.0.16`, confirmed by reading its actual config-plugin source, not assumed) to inject `ACCESS_BACKGROUND_LOCATION`, `FOREGROUND_SERVICE`, **and** `FOREGROUND_SERVICE_LOCATION` into the generated manifest. The last one matters specifically on Android 14+ (API 34), which introduced typed foreground-service permissions — a plain `FOREGROUND_SERVICE` grant alone is no longer sufficient there for a location-type service. This platform is already correctly configured for that requirement.

**Foreground service (✅):** `startLocationUpdatesAsync` is called with `foregroundService: { notificationTitle, notificationBody }`, which is what makes this a true Android foreground service (persistent notification, `foregroundServiceType="location"`) rather than best-effort background execution — this is also the main practical defense against the OS killing the process outright while a delivery is active (see below).

**Task registration & app restart behavior (⚠️ documented limitation, not fixed in this phase):** `TaskManager.defineTask(...)` is only called lazily, inside `startBackgroundLocationTracking()`, itself only invoked once a rider actually goes online — not unconditionally at module load / app entry. Expo's own guidance for background tasks that must survive a full app kill-and-relaunch (the OS headlessly restarting the JS engine specifically to deliver a location event to a previously-registered task) is to call `defineTask` unconditionally at the top level of a module that's always imported, so the task name is registered again before that headless invocation needs it. This codebase deliberately does *not* do that today — `getModules()`'s dynamic `import()` of `expo-task-manager`/`expo-location` is itself guarded behind an `Constants.appOwnership !== "expo"` check specifically so importing this file at all never crashes an Expo Go session, and making that registration unconditional would mean attempting it (and having it silently no-op, per the same guard) on every single app launch regardless of whether tracking is even relevant yet.

In practice, on **Android specifically** (the prioritized platform), this gap matters less than it would in the abstract: a foreground service with an active notification is explicitly protected from Android's routine background-process reclaiming — the process, and the JS engine inside it, generally stay alive for as long as that notification is showing, which is the normal case (rider mid-delivery, app never fully killed). The scenario where this limitation actually bites is a **hard kill** while tracking is active — the user force-stopping the app from Android system settings, or an aggressive OEM battery manager (Xiaomi/OnePlus/Oppo-style skins are the known offenders here, not stock Android) killing it despite the foreground service. In that case, the task is not re-registered on relaunch, and background tracking silently doesn't resume — the rider would need to reopen the app (which re-triggers `startBackgroundLocationTracking` through the normal `active`-driven path) to restore it. Foreground tracking (Phase 9) is unaffected either way, since it only ever runs while the app is genuinely open.

**A full fix** — moving `defineTask` to an unconditional, top-level call gated by a build-time (not runtime) Expo-Go-vs-real-build check, so it's registered on every cold start without ever executing in Expo Go — is a real, bounded piece of work, but one that needs an actual Android device/build to verify (a headless relaunch can't be exercised in this environment or in Jest), so it's documented here as a known limitation rather than attempted blind in this phase.

**Battery restrictions (✅):** already covered in §7 above — 30s/50m background interval (vs. 12s foreground), `Accuracy.Balanced` never `.BestForNavigation`, and the whole mechanism only runs while `active`.

**Permission denial (✅):** `startBackgroundLocationTracking()` checks foreground permission first (background is meaningless without it), then separately requests background permission; if either is missing, it returns silently — a rider who declines background permission still gets full foreground tracking, this is additive, never a hard requirement to use the app at all.

## 12. Realtime event model

**The actual event envelope is `OrderTrackingResponse` (`app/schemas/tracking.py`), not a minimal per-change-type event.** This master command's own example (`{"type": "rider.location.updated", "order_id": ..., "location": {...}, "server_timestamp": ...}`) sketches a narrow, single-purpose delta event. The existing, already-tested implementation instead broadcasts one **consistent, full snapshot** — order status, rider identity, rider location (with its `state`), delivery coordinates, ETA, and status history — every time *anything* about the order changes, whether that's a new GPS position or a status transition. This is a deliberate design already in place, not an oversight, kept as-is rather than replaced:

- A client that reconnects, or that missed a message while briefly disconnected, is never left needing to merge a partial delta against stale local state — every message is already the full current truth.
- The same shape is used for the REST endpoint, the WebSocket's initial-snapshot-on-connect, and every subsequent broadcast — one type, three call sites, no drift possible between them.
- It costs a slightly larger payload per message than a bare `{lat, lng}` delta would — accepted, since order-tracking traffic is low-volume (one customer, one order, occasional updates) compared to, say, a multiplayer game's position stream, where a minimal delta would matter.

**Fields, and why each is there (mapped against this phase's example):**

| This phase's example | Existing equivalent | Note |
|---|---|---|
| `type` | *(implicit)* | Not needed — there is exactly one message shape on this channel; a `type` discriminator matters when multiple event types share a socket, which isn't the case here. |
| `order_id` | `order_id` | ✅ present |
| `assignment_id` | *(not present)* | Not exposed to the customer — an assignment is an internal accept/reject/progress record; the customer already gets everything operationally relevant to them (`assignment_status: "unassigned" \| "assigned"`, and the rider's identity/location once assigned). Adding the raw `assignment_id` would be exposing an internal id with no client-side use, so it's deliberately left out. |
| `location.{latitude,longitude,accuracy,heading,speed}` | `rider_location.{latitude,longitude,updated_at,state}` | Accuracy/heading/speed are captured server-side (`User.current_accuracy/heading/speed`) but **not** currently forwarded to the customer — see "not exposed" below. `state` (Live Rider Tracking Phase 5/19) is additive beyond this phase's own example. |
| `server_timestamp` | `rider_location.updated_at` | ✅ present, server-assigned (never the client's own `captured_at`) |

**"Do not expose unnecessary rider/account information" — audited, already satisfied:** `RiderInfo` (the rider object embedded in the response) carries exactly `id`, `name`, `phone` — no email, no address, no account/financial data, no raw device/session info. Accuracy/heading/speed are deliberately **not** forwarded to the customer today (only latitude/longitude/updated_at/state) — arguably fine to add later if a UI need arises (e.g. showing a direction-of-travel arrow from `heading`), but not added speculatively here without a consumer for it.

**Shared types:** this project has no code-generation bridge between the FastAPI/Pydantic backend and the TypeScript frontends — Python and TypeScript types are hand-maintained mirrors of each other, kept in sync deliberately rather than automatically. `app/schemas/tracking.py` (`OrderTrackingResponse`, `RiderLocation`, `RiderInfo`) is the source of truth; `customer-mobile/services/api/trackingApi.ts` (`OrderTracking`, `RiderLocation`, `Rider`) is its TypeScript mirror — updated in this phase to add the `state` field Phase 5 introduced server-side, which had not yet been reflected client-side.

## 13. Performance & Scalability (🆕 — Phase 35)

**Measured/reasoned-through, not load-tested** — this environment has no production traffic to profile, so the figures below are derived from the code's own configured parameters (already a deliberate design decision from earlier phases, not new math for this phase).

| Dimension | Figure | Where it's bounded |
|---|---|---|
| GPS update rate (rider→server) | 1 per 30s or 50m, whichever first | `rider-mobile`'s background location task (Phase 10) |
| History table writes | ≤1 per 10s or 15m per rider | `_should_store_history_row` (Phase 7) |
| "Latest position" cache writes | 1 per accepted update | `User.current_latitude` etc. — necessary, not throttled (it *is* the read model every consumer uses) |
| Route/ETA (OSRM) calls | ≤1 per 60s or 300m per order, plus a global cross-request throttle | `get_live_eta`'s refresh gate (Phase 24) + `routing.py`'s `_wait_for_throttle_slot` + `_route_cache` |
| WebSocket connections | 1 per customer actively viewing an in-progress order's tracking screen | Naturally bounded by concurrent in-progress orders — not a per-GPS-ping concern |
| Broadcast latency | In-process (`asyncio.run_coroutine_threadsafe` within the same worker) — no network hop, no queue to wait on | `app/ws/manager.py` |
| Rate-limit state (`_attempts`) | Bounded by distinct customers/IPs, not by order count | See the fix below |

**Two real, evidence-based optimizations found and applied** (not speculative — each is a specific code path with a concrete, traceable cost):

1. **Skip snapshot-building when nobody's listening.** `update_rider_location`'s broadcast loop previously called `build_tracking_snapshot` (a DB read, plus a possible live OSRM call) for every location-visible order on *every accepted GPS ping*, regardless of whether any customer was actually connected to receive it. `OrderTrackingConnectionManager.has_listeners()` (a cheap `O(1)` dict-key check) now gates this — the expensive work only runs when there's a real listener. The proximity-notification check (Phase 34) is deliberately **not** gated by this, since a customer with the app backgrounded still needs the push.
2. **Bounded rate-limit key for the tracking-polling endpoint.** `GET /orders/{order_id}/tracking`'s path embeds `order_id`; `rate_limit()`'s default key (`path:ip`) would have created one permanent, never-evicted entry per order for the life of the process — a real, order-count-scaled memory leak, and one specific to this endpoint (every other `rate_limit()` caller in this codebase uses a fixed-cardinality literal path). Fixed by giving `rate_limit()` an explicit `key` override, and keying this one endpoint by customer id instead — bounded by distinct customers, and correctly shares one budget across a customer's several simultaneously-active orders rather than granting one free budget per order.

**Frontend render cost:** `customer-mobile`'s tracking screen re-renders every 5s purely to refresh "Xs ago" relative-time text (`forceTick`), independent of whether any real tracking data changed. `RiderMap` (the MapLibre subtree) is now wrapped in `React.memo` so that tick doesn't also re-run the map's own render — its props (`riderLocation`/`restaurantLocation`/`deliveryLocation`) are referentially stable between genuine data updates, so memo's default shallow comparison correctly bails out on every tick that isn't a real change.

**Redis-readiness — confirmed, not built.** `OrderTrackingConnectionManager`'s own docstring has said since Phase 13 that it's designed to be swappable for a shared pub/sub behind the same `broadcast()`/`connect()`/`disconnect()`/`close_room()`/`has_listeners()` interface, with no caller needing to change. This phase re-confirms that's still true after the Phase 28/35 additions (`close_room`, `has_listeners` are both plain methods on the same class, no new caller-visible coupling to the in-process dict) and deliberately does **not** introduce Redis — this app runs as a single uvicorn worker today, so there is no multi-process fan-out problem to solve yet, and adding Redis now would be exactly the complexity-without-justification this phase's own final instruction warns against.

## 14. Observability (🆕 — Phase 39)

**Structured, not plain-text, logging** for the tracking lifecycle: `app/core/observability.py`'s `log_event(logger, event, **fields)` emits a fixed `event=<name>` token plus flat `key=value` fields (logfmt — parseable by a log aggregator with a one-line regex, still readable directly in a terminal), rather than this codebase's existing free-form `%s`-interpolated messages. Used alongside those existing messages, not instead of them.

| Event | Where | Fires on |
|---|---|---|
| `tracking_started` | `rider_location.py` | The first accepted GPS ping for a specific order |
| `tracking_stopped` | `orders.py` | An order reaches a terminal status (same point `close_room` already fires from) |
| `location_received` | `rider_location.py` | Every accepted location update |
| `location_rejected` | `rider_location.py` | Ineligible rider, implausible movement, or implausible timestamp |
| `location_filtered` | `rider_location.py` | Accepted for the cache, but the history write was throttled |
| `websocket_connected` / `websocket_disconnected` | `customer/tracking.py` | The raw socket accept / the connection ending |
| `subscription_created` / `subscription_rejected` | `customer/tracking.py` | Successfully joining an order's room / any auth or ownership failure first |
| `eta_refresh` | `eta.py` | Only on an actual fresh OSRM computation — never on a cache-hit reuse |
| `tracking_error` | `rider_location.py`, `orders.py` | The Phase 32 failure-isolation guards catching a broadcast-layer exception |

**Never logged — audited, not just intended:** no call site above ever passes a token (the WS auth token is read and used, never logged, not even on rejection — `subscription_rejected` identifies the attempt by `order_id`/`user_id` only), no name/email/phone/raw address text (every field is an id, a status, a reason string, or a plain number), and no payment details. Verified by a dedicated test (`test_subscription_rejected_is_logged_and_never_includes_the_token`) that asserts a token value never appears in any captured log line, not just that the right event fires.

## 15. WebSocket Endpoint Reference (🆕 — Phase 42)

**Endpoint:** `GET /api/v1/customer/ws/orders/{order_id}` (upgraded to a WebSocket).

**Auth:** `?token=<access token>` as a query parameter — not an `Authorization` header, since neither browsers' nor React Native's WebSocket client can set custom headers on the handshake, and a query param works everywhere (web, native, `wscat`). The same access token issued by `/api/v1/auth/login`/`/refresh`; a customer-role, active-account token for an order that customer actually owns, or the server closes the connection with a 4401/4404 close code before ever accepting it (see §8 Security boundaries).

**On connect:** a full `OrderTrackingResponse` snapshot is sent immediately — never a delta, and never a wait for the next change (§12 Realtime event model explains why).

**While connected:** the server pushes the same full-snapshot shape again on every status change and every accepted rider location update for this order, for as long as the order stays in a non-terminal status. The client may send the literal text `"ping"`; the server replies `"pong"` (a liveness check only — no other client message is meaningful).

**Disconnection:** the server closes the connection itself once the order reaches DELIVERED/CANCELLED/REJECTED (Phase 28, "tracking stops" — no further message will ever come). The client should not treat that as an error requiring reconnection; `TERMINAL_ORDER_STATUSES` is the client-side signal to distinguish it from a real network drop (see `customer-mobile/services/api/trackingApi.ts`).

## 16. Fallback Behavior (🆕 — Phase 42, built in Phase 33)

The customer app's REST-polling fallback (`customer-mobile/features/tracking/use-order-tracking.ts`) only runs while the WebSocket is down — it is never the primary transport. On any socket close that isn't the server's own terminal-status close, the client starts polling `GET /orders/{order_id}/tracking` every 15 seconds (slower than any realtime push) while simultaneously retrying the WebSocket connection with exponential backoff (1s, 2s, 4s, 8s, capped at 15s). The moment the socket reconnects, polling stops immediately — the socket is authoritative whenever it's up. The poll endpoint itself is rate-limited (30 requests/60s, keyed per customer — not per order, see §13's own write-up of why) and stops entirely once a poll response itself reveals a terminal status, so a customer whose socket never recovers doesn't poll a finished order forever.

## 17. Rider Permissions & Android Configuration (🆕 — Phase 42)

Two permission layers, both already implemented — see §11 for the full background-tracking write-up; this section is the quick-reference.

**Foreground permission (required):** `expo-location`'s `locationWhenInUsePermission` (`rider-mobile/app.json`). Requested the first time `useLocationReporter` activates (the rider goes online or accepts a delivery); a rider who declines it gets neither foreground nor background tracking — surfaced as the explicit `permission-denied` state in `locationTrackingStore`, never a silent failure.

**Background permission (additive, not required):** `locationAlwaysAndWhenInUsePermission`/`isAndroidBackgroundLocationEnabled`/`isAndroidForegroundServiceEnabled` in the same plugin config, backing `useBackgroundLocationTracking` (`rider-mobile/features/location/background-location-task.ts`, `app/(rider)/_layout.tsx`) — real, working background tracking (30s/50m interval, an Android foreground service with a persistent notification), not a placeholder. `startBackgroundLocationTracking()` requests foreground permission first and only then separately requests background permission; a rider who grants foreground but declines background still gets full foreground tracking — background is additive coverage, never a hard requirement to use the app.

**Android manifest:** no manual `AndroidManifest.xml` edits — `expo-location`'s config plugin generates `ACCESS_FINE_LOCATION`/`ACCESS_COARSE_LOCATION`/`ACCESS_BACKGROUND_LOCATION`/`FOREGROUND_SERVICE`/`FOREGROUND_SERVICE_LOCATION` from the `app.json` block above at prebuild time (verified against `expo-location`'s actual config-plugin source — see §11).

A correction from earlier in this master command's own work: Phases 32/38/39's audits described the rider side as "foreground-only" and "no persistent state to lose," reasoning only from `use-location-reporter.ts` without re-checking that background tracking already existed (correctly documented all the way back in §11, itself predating this master command). That characterization was wrong for the background-tracking path specifically; §11 remains the accurate source and nothing in Phases 32/38/39's actual code changes depended on the incorrect premise — this section exists to make sure the record is consistent going forward, not to imply any code needed fixing.

## 18. Production Considerations (🆕 — Phase 42)

Consolidates points already made throughout this document, gathered here as a single pre-launch checklist:

- **Single-process deployment today.** `OrderTrackingConnectionManager` and the ETA cache are both in-process (§13/§35). Scaling to multiple uvicorn workers or instances needs a shared pub/sub (Redis) behind the exact same `broadcast()`/`connect()`/`disconnect()`/`close_room()`/`has_listeners()` interface — confirmed still swappable, deliberately not built until there's an actual multi-process deployment to justify it.
- **Self-host the routing/geocoding providers before real traffic.** `OSRM_API_BASE_URL` and `PHOTON_API_BASE_URL` default to free public demo instances, rate-limited server-side to 1 req/s and explicitly licensed for non-commercial use only — see `.env.example`.
- **The location-history retention purge is not scheduled.** `purge_rider_location_history()` (§9 Privacy rules, `docs/location-privacy.md`) exists and is safe to run, but nothing calls it automatically — this codebase has no cron/scheduled-task infrastructure at all yet. Wire it into whatever scheduler is added first, or run it as a periodic manual/ops job.
- **CORS.** The WebSocket and REST tracking endpoints are same-origin from a native app's perspective (no browser CORS involved) but the browser-based web apps (`business-web`, `admin-web`) do need their origins listed in `CORS_ORIGINS` if either is ever extended to touch tracking data — neither does today.
- **JWT secret and token lifetimes.** `JWT_SECRET_KEY` must be a real random value in production (never the example placeholder); `ACCESS_TOKEN_EXPIRE_MINUTES` bounds how long a leaked/copied WebSocket URL (with its `?token=`) remains usable — see §8 Security boundaries.
- **Structured logs are stdout/stderr text today**, not shipped anywhere — §14 Observability's `event=` lines are ready to be picked up by any log aggregator that can tail process output, but nothing here assumes one exists.

## Summary for implementers of later phases

Phases 3–6, 9–17, 20, 21, 28 (partially) are implementation-hardening or documentation work against a system that already runs end-to-end. Phases 7, 8, 18 (partially), 19, 22–27, 29, 34, 39, 42 involve genuinely new logic or surfaces, scoped concretely above rather than left open-ended.
