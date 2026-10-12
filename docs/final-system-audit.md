# Final System Audit — Phase 1

**Date:** 2026-10-08 · **HEAD:** `5b19ccb58` plus 9 uncommitted files (see A11) · **Scope:** `backend/`, `customer-mobile/`, `rider-mobile/`, `business-web/`, `admin-web/`

This is the baseline for the 54-phase End-to-End System Testing & Production Validation protocol. Phase 1 is read-only plus non-destructive checks. Nothing touched the local dev database or Render. One throwaway in-memory SQLite harness was used to reproduce findings. **No application code was changed.**

---

## 1. How the audit was done

| Check | Method |
|---|---|
| Route inventory and auth coverage | Walked the live FastAPI app (`app.main.app`) and resolved every route's dependency tree |
| Backend tests | `pytest` full suite (SQLite, as configured in `tests/conftest.py`) |
| Frontend health | `tsc --noEmit` and each app's test runner (`jest` / `vitest`) |
| Migrations | `alembic heads` / `alembic branches` (static, no DB) |
| Secrets | `git ls-files` + pattern scan of tracked files and history. Only filenames and variable **names** were inspected; no values were printed |
| Code markers | TODO/FIXME/stub/mock/placeholder/`print()`/`console.log`/hard-coded hosts across all apps |
| Money types | Scan for `Float` columns and `float` money fields/arithmetic |
| Reproductions | Isolated TestClient + in-memory SQLite harness (scratchpad only) |

### Repository vs. the master command

The master command's structure diagram differs from the repo in three ways:

* **`admin-web/` exists** and is the Admin Portal (one frontend app per role, per `docs/architecture/role-architecture.md`). It is included in this audit and every later phase.
* **Maps are not Google.** Geocoding uses **Photon** (komoot public instance), routing/ETA uses **OSRM** (project-osrm.org public demo), and map rendering uses **MapLibre** with an OSM style URL. No Google Maps key exists anywhere. Phases that say "Google API failure" will test Photon/OSRM failure instead.
* **Order lifecycle:** the backend also allows `CONFIRMED → RIDER_ASSIGNED` and `PREPARING → RIDER_ASSIGNED`, but only through admin manual assignment. Riders can only accept from `READY_FOR_PICKUP`. This is a deliberate admin override, not a defect. Note that once an order is assigned early, the restaurant can never mark it `READY_FOR_PICKUP`.

---

## 2. Inventory

| Component | Size | Stack |
|---|---|---|
| backend | 221 routes · 31 models · 52 services · 68 migrations (single head `20261011_57`) · 185 test files | FastAPI 0.141.1, Starlette 1.6, SQLAlchemy 2.0.52, Alembic 1.19.1, Pydantic 2.13, PyJWT 2.13, pwdlib, psycopg 3.3 |
| customer-mobile | 89 source files · 21 test files | Expo Router / React Native |
| rider-mobile | 56 source files · 10 test files | Expo Router / React Native |
| business-web | 37 source files · 7 test files | React + Vite |
| admin-web | 51 source files · 6 test files | React + Vite |

### Route authorization map (resolved from the dependency graph)

| Gate | Routes |
|---|---:|
| `require_admin` | 75 |
| `require_customer` | 43 |
| `require_roles(RESTAURANT_OWNER[, ADMIN])` | 35 |
| `require_rider` | 34 |
| Authenticated, any role (ownership checked inline) | 11 |
| Public (no auth dependency) | 23 |

All 23 public routes were reviewed. They are `auth/register|login|refresh`, the health endpoints, the catalogue/search/location reads, the Razorpay webhook (HMAC-verified), public review reads, **legacy `POST /reviews`** (it does require a customer token; see A1), and the tracking WebSocket. The WebSocket authenticates inline: token, `is_active`, CUSTOMER role, and order ownership. The 11 "any role" routes either act on the caller's own data or call `assert_restaurant_manager()`. No duplicate method+path registrations.

---

## 3. Test baseline

| Suite | Result |
|---|---|
| Backend (`pytest`, SQLite) | **1588 passed · 1 failed · 10 skipped** (200 s) |
| customer-mobile (`jest`) | 130 / 130 passed · `tsc` 0 errors |
| rider-mobile (`jest`) | 58 / 58 passed · `tsc` 0 errors |
| business-web (`vitest`) | 26 / 26 passed · `tsc` 0 errors |
| admin-web (`vitest`) | 26 / 26 passed · `tsc` 0 errors |

* **The 1 failure is a flaky test, not a vulnerability (A9).** `test_admin_with_a_tampered_token_is_rejected` changes only the token's last base64url character. For a 32-byte HS256 signature, that character carries 2 padding bits, so `A`↔`B` (and similar pairs) decode to the same bytes. Measured: 134 of 2000 such "tampered" tokens decode (≈1/16, as predicted). Changing a data-bearing signature character is rejected correctly.
* The 10 skips are benign self-transitions in `test_order_transition_matrix.py`.
* **The backend suite runs only on SQLite (A12).** SQLite silently ignores `SELECT … FOR UPDATE` (6 call sites), and `StaticPool` uses one shared connection. The existing "concurrency" tests therefore do not prove Postgres locking behaviour, and NUMERIC precision and Postgres-specific constraints are not exercised either.

---

## 4. Module status

| Module | Status | Notes |
|---|---|---|
| Authentication | Mostly complete | Register/login/refresh/me work. Logout is a no-op and refresh tokens are never revoked (A3). **No password change or reset for any role** (A4). Login has a per-IP rate limit (A5). |
| Authorization / role isolation | Complete | Every portal is role-gated. Owner restaurant resolution proves ownership (`resolve_owner_restaurant`). Customer resources are scoped by `user_id`. |
| Users / profile | Complete | No password operations (A4). |
| Restaurants / menu / categories | Complete | Hours and the manual open toggle are both enforced at checkout. Legacy `/restaurants` router duplicates `/customer/restaurants` (A19). |
| Cart / checkout | Complete | Prices come from the DB and totals are computed server-side as `Decimal`. Coupon re-validated. **Tax is fixed at ₹0** (A14). |
| Orders | Complete | Single `transition_order_status` choke point with a conditional UPDATE (optimistic concurrency). Cart-claim guard against double submit. No failed-delivery path after `PICKED_UP` (A22). |
| Payments: Razorpay | Complete, testing in progress | See `docs/razorpay-test-audit.md`. Phases 1–8 and 10–14 PASS; Phase 9 (real device success payment) PENDING. Open: P1 late capture after expiry, P5, P6, P7, P8, P9 (A20). |
| COD | Complete | Collection amount is server-derived; the request body accepts nothing. Settlement is admin-only and audited. |
| Refunds | Complete | Admin-only, row-locked, remaining-amount check, audited. |
| Rider assignment / delivery | Complete | Atomic conditional claim (`rider_id IS NULL AND status = READY_FOR_PICKUP`). |
| Maps / location | Complete (free providers) | Photon + OSRM **public** instances (A13). Service area is by customer-typed postal code and fails open when no zones exist (A17). |
| Live tracking / WebSocket | Complete, one scaling defect suspected | Auth and ownership correct. **DB connection held for the socket's lifetime** (A2). Token in query string (A16). In-process fan-out, single worker only (A21). |
| Notifications | Complete | Savepoint-isolated writes. Push sent via background tasks, so a failure doesn't roll back the order. Expo push. |
| Reviews & ratings | **Incomplete, with one security defect** | Order-based review flow is in progress (uncommitted). **Legacy `POST /reviews` lets any customer post unlimited fake reviews** (A1). No admin moderation, report, or delete endpoints. `Restaurant.average_rating` is never computed (A7). |
| Admin | Complete, audit gaps | 41+ mutating admin routes; ~12 audited operations (A6). |
| Database / migrations | Single head, no branches | One intentional no-op downgrade (enum value add). Drift vs. models not yet checked against Postgres (→ Phase 3). |
| Environment / config | Good | Boot guards for weak JWT secret, `DEBUG`, test Razorpay key, and missing webhook secret in production. CORS is an explicit list. Docs/OpenAPI disabled in production. |
| Frontends | Clean | 0 TS errors. No TODO/mock/`console.log`. No secrets. Mobile uses SecureStore. Web apps use `localStorage` (A15). |
| Deployment | **Undocumented in repo** | No `render.yaml`/Procfile/Dockerfile. Start command, worker count, and proxy-header settings are unknown (A5, A24). |
| Backup / recovery | **Not documented** | No backup or restore procedure anywhere in the repo (A25). |

### Code-marker sweep

* **TODO/FIXME/HACK:** none in any app.
* **Stubs/placeholders:** `backend/app/api/v1/routes.py` (a `POST /orders` stub returning `order_id: 123`) is **not mounted** and is dead code (A19).
* **Floating-point money:** none. No `Float` columns; all money is `Numeric`/`Decimal`. `distance_km` is the only `float` and isn't money.
* **Hard-coded hosts:** only dev fallbacks (`10.0.2.2:8000`, `localhost:8000`) and the Render URL in EAS profiles.
* **Dead/weaker code:** `services/payments.verify_payment` (signature-only verifier, not routed; Razorpay audit P8).

### Secrets

* No secret value is committed, now or in history. Tracked env files are `*.env.example` plus `customer-mobile/.env.development` and `rider-mobile/.env.development`, which contain only `EXPO_PUBLIC_API_BASE_URL`. A root `.env.production` once in history contained only `EXPO_PUBLIC_API_BASE_URL`.
* `docs/payments/phase-40-…md` contains the Razorpay **test Key ID** (public by design; Razorpay audit P10). No key secret or webhook secret.
* Frontends reference only `EXPO_PUBLIC_API_BASE_URL`, `EXPO_PUBLIC_MAP_STYLE_URL`, `VITE_API_BASE_URL`, and `VITE_MAP_STYLE_URL`. All are safe for client exposure.

---

## 5. Findings

Severity: **P0** blocks launch · **P1** serious · **P2** moderate · **P3** minor. "Confirmed" means reproduced or proven from code; "Hypothesis" means a later phase must confirm it.

| ID | Sev | Finding | Evidence | Phase |
|---|---|---|---|---|
| **A1** | **P1** | **Fake-review injection.** Legacy `POST /api/v1/reviews` takes a client-supplied `target_type/target_id/restaurant_id/rider_id` and inserts a PUBLISHED review with no order, delivery, ownership, or uniqueness check. These reviews show in the public `/reviews/restaurant|rider|food/*` lists and `/reviews/average/*`. No frontend calls this route. | **Confirmed:** 5/5 reviews accepted for a random, non-existent restaurant; public list = 5; average = 1.0 | 23 (fix), 48 |
| **A2** | **P1** | **Tracking WebSocket pins a DB connection for its whole lifetime.** `order_tracking_socket` takes a sync `DbSession`. After the first snapshot query, the implicit transaction stays open (idle in transaction) until the client disconnects. Default pool is 5 + 10 overflow, so roughly 15 concurrent trackers per worker could starve every REST request (30 s pool timeout, then 500). It also runs sync DB calls on the event loop. | Confirmed from code (`customer/tracking.py`, `db/session.py`); impact needs load proof | 21, 46 |
| **A3** | P2 | Logout doesn't invalidate anything. Refresh tokens last 30 days, are never rotated, and can't be revoked. A stolen refresh token keeps working after logout. Deactivation (`is_active=false`) is the only kill switch. | **Confirmed:** refresh after logout returns 200 | 5, 32 |
| **A4** | **P1** | **No password change or reset for any role.** A user who forgets their password is locked out permanently. Admins can't reset one either; only the `create_admin` CLI sets passwords. | Confirmed (route inventory) | 5, 8 |
| **A5** | **P1** (hyp.) | The rate limiter keys on `request.client.host`. Behind Render's proxy, without `--proxy-headers --forwarded-allow-ips`, every client may share the proxy's IP. That would make the login limit **10/min platform-wide** and register 5/min. It is also per-process, so it doesn't hold across workers or instances. | Code confirmed; deployment start command unknown | 4, 43 |
| **A6** | P2 | Admin audit-log coverage is partial. **Audited:** user activate/deactivate, restaurant approve/reject/deactivate/reactivate, rider approval, platform settings, admin assign/cancel order, COD settle, refund. **Not audited:** commission rules (financial), coupons, categories, service areas, customer/owner edits, rider profile/verification/document approve/reject, broadcast notifications, **admin login**. There are no update/delete routes on audit logs (good), and no DB-level immutability. | Confirmed (call-site scan) | 40 |
| **A7** | P2 | Reviews are incomplete. There's no admin moderation endpoint (although the model has HIDDEN/FLAGGED/REMOVED), no customer delete, and no report-review. `Restaurant.average_rating` is never written, so restaurant ratings stay at the default while the restaurant list sorts by it. | Confirmed | 23 |
| **A8** | P3 | `GET /reviews/average/{bad_type}/x` returns **500**: an unhandled `ValueError` from `ReviewTarget(...)`. | **Confirmed** | 29 |
| **A9** | P3 | Flaky test `test_admin_with_a_tampered_token_is_rejected` fails about 6% of runs (see §3). Test defect only. | **Confirmed** (134/2000) | 5 |
| **A10** | **P1** (hyp.) | The customer-mobile `eas.json` **`production`** profile has no `EXPO_PUBLIC_API_BASE_URL` (only `preview` does), so a production build falls back to `http://10.0.2.2:8000`. The local `customer-mobile/.env.production` is git-ignored, so EAS won't upload it. Rider-mobile's (untracked) `eas.json` sets it for both profiles. Safe only if the variable is set in the EAS dashboard. | Config confirmed; EAS dashboard unknown | 2, 43 |
| **A11** | **P1** | **Validated fixes are uncommitted and undeployed.** 9 modified files (Razorpay P3/P4 fixes, verification non-ASCII 500 fix, unpaid-reject gate, review hardening) plus 4 new review test files and `rider-mobile/eas.json`. Render runs code without these fixes. | `git status` | 43, 47 |
| **A12** | P2 | Backend tests are SQLite-only. Row locks (`with_for_update` ×6), NUMERIC precision, partial indexes, and enum types are never exercised on Postgres, so concurrency tests prove less than their names suggest. | Confirmed (`conftest.py`) | 3, 28 |
| **A13** | **P1** | Production depends on **public free instances**: OSRM's demo server (usage policy: non-commercial, ~1 req/s) and komoot Photon (fair use, ~1 req/s, globally throttled in-process). This is a licensing and capacity risk at launch. | Confirmed (`config.py`) | 20, 45 |
| **A14** | P2 | Tax is fixed at ₹0. No GST is applied to food orders. This is a business/compliance decision that needs an owner. | Confirmed (`cart.calculate_cart_totals`) | 12, 31 |
| **A15** | P2 | business-web and admin-web store access + **30-day refresh** tokens in `localStorage`. Any XSS gives full account takeover, including admin. React escaping mitigates this; there's no CSP. | Confirmed | 32, 33 |
| **A16** | P2 | WebSocket auth uses `?token=` in the URL, so access tokens can land in proxy/uvicorn access logs (15-minute lifetime limits the damage). An open socket isn't closed when its token expires. | Confirmed from code | 21, 41 |
| **A17** | P2 | Delivery eligibility uses the customer-typed postal code and isn't cross-checked against the pin's coordinates. It **fails open** when no service area is configured. | Confirmed (`service_areas.is_address_serviceable`) | 20 |
| **A18** | P2 | No file upload exists. Rider KYC documents and restaurant images are arbitrary client-supplied URLs, so document verification depends on whatever an external link serves. | Confirmed (no `UploadFile`) | 32, 39 |
| **A19** | P3 | Dead or duplicate surface: unmounted `api/v1/routes.py` stub; legacy routers `/restaurants`, `/reviews`, `/coupons`, `/notifications` alongside the role portals; `services/payments.verify_payment`. A1 shows why legacy routes are a risk. | Confirmed | 38 |
| **A20** | **P1** | Razorpay items still open from `docs/razorpay-test-audit.md`: **P1 late capture after the 30-minute expiry** (customer charged, order unpaid unless the webhook repairs it), P5 webhook can overwrite refund state, P6/P7 attempt-trail gaps, P8 dead verifier, P9 `/payments/create` trusts the client `method`. Phase 9's real device payment is still pending. | Prior audit | 13, 27, 31 |
| **A21** | P2 | WebSocket fan-out and the rate limiter are in-process. They are correct only with **one** uvicorn worker on **one** instance; scaling out silently breaks live tracking and rate limits. | Documented in code | 43, 46 |
| **A22** | P2 | No failed-delivery path. From `PICKED_UP`/`OUT_FOR_DELIVERY` the only transition is forward; even an admin can't cancel or return an order whose customer is unreachable. | Confirmed (`VALID_TRANSITIONS`) | 19, 26 |
| **A23** | P3 | Login skips password hashing for unknown accounts, so response timing can reveal which emails or phones are registered. | Confirmed from code | 5, 32 |
| **A24** | P2 | Deployment isn't defined in the repo (no `render.yaml`, Procfile, or Dockerfile). Render's start command, workers, migrations-on-deploy, and env are configured only in the dashboard, so they can't be reviewed or rolled back from the repo. | Confirmed | 43, 44 |
| **A25** | P2 | No backup, retention, or restore procedure is documented anywhere. | Confirmed | 42 |

**Confirmed sound (no action):** the role gate on every portal; restaurant-owner ownership proofs; customer resource scoping; WebSocket auth and ownership; server-authoritative prices, totals, COD amount, and order state; conditional-UPDATE transition guard; atomic rider claim; cart-claim double-submit guard; Decimal/NUMERIC everywhere; HMAC webhook verification before parsing; webhook/payment idempotency via unique constraints; production boot guards; generic 500 handler (no stack traces to clients); docs disabled in production; no secrets in git; mobile tokens in SecureStore.

---

## 6. Phase 1 summary

1. **Complete:** auth (core), role authorization, restaurants/menu, cart, checkout, orders and state machine, COD, refunds, rider assignment and delivery, tracking, notifications, admin portal, all four frontends (type-clean, tests green).
2. **Incomplete:** password change/reset (A4), refresh-token revocation (A3), review moderation/report/delete and restaurant rating aggregation (A7), audit-log coverage (A6), tax (A14), failed-delivery path (A22), file uploads (A18), backup/restore documentation (A25), deployment-as-code (A24).
3. **Broken:** legacy fake-review endpoint (A1); unhandled 500 on review averages (A8); flaky auth test (A9).
4. **Requires testing:** Postgres locking and concurrency (A12, A2); proxy IP / rate limiting on Render (A5); customer production build URL (A10); Razorpay Phase 9 device payment and P1 late capture (A20); Photon/OSRM failure and limits (A13).
5. **Security risks:** A1 (P1), A3, A15, A16, A17, A18, A23; A5 can be turned into a login denial-of-service if confirmed.
6. **Production blockers (P0/P1):** **A1, A2, A4, A5\*, A10\*, A11, A13, A20** (\* = hypothesis to confirm). No P0 has been confirmed yet.

**Phase 1 result: PASS (audit complete). The system is NOT production-ready**: 6 confirmed P1 findings plus 2 suspected.

Files changed: `docs/final-system-audit.md` (new). No code changes.

---

## Phase 2 — Environment Validation (2026-10-08) — **PASS after fix** (with open configuration findings)

No secret values were printed. Only names, set/empty status, lengths, and key-mode prefixes were inspected. Render's environment can't be read from here, so its configuration was inferred from read-only HTTP probes.

### Backend (local `backend/.env`)

| Item | Result |
|---|---|
| `.env` present, git-ignored, never tracked | ✅ (`backend/.gitignore:1`; not in history) |
| `.env.example` covers every `Settings` field | ✅ (except `PROJECT_NAME`/`API_V1_PREFIX`, which are constants) |
| `ENVIRONMENT` / `DEBUG` / `LOG_LEVEL` | `development` / `False` / `WARNING` ✅ |
| `JWT_SECRET_KEY` | ✅ set, 64 chars, not a known placeholder · HS256 · access 15 min · refresh 30 days |
| `DATABASE_URL` | ✅ `postgresql+psycopg` → `localhost:5433/say_hi_chai`. Password equals the docker-compose default (fine for local only) |
| Razorpay | ✅ Key ID is **TEST** mode (`rzp_test_***`). Key secret configured; keys authenticate (read-only `GET /v1/orders` → 200). Webhook secret configured (15 chars) |
| `EXPO_ACCESS_TOKEN` | unset (optional; only raises Expo rate limits) |
| CORS | ✅ explicit list of 6 local Vite origins, no wildcard |
| Maps providers | Photon `photon.komoot.io`, OSRM `router.project-osrm.org` (public; see A13) |
| `.env` file mode | ⚠️ `664`: readable by other local users (E7) |

### Database (local)

The Postgres container (`backend-postgres-1`) was stopped (exited cleanly 11 h earlier). It was **restarted with its existing volume**; nothing was created or deleted. Connection took 20 ms. PostgreSQL 17.10, UTF8, UTC, 37 public tables, `alembic_version = 20261011_57` (= repo head). Existing dev data: 84 users (33 customers, 32 riders, 14 owners, 5 admins), 47 orders.

### Render backend (`delivery-app-rjux.onrender.com`, read-only probes)

| Probe | Result |
|---|---|
| `GET /health` | ✅ 200 (DB round trip OK) |
| HTTP → HTTPS | ✅ 301 to https |
| WebSocket over `wss://` (no token / bad token) | ✅ handshake rejected (403). Note: closing before `accept()` turns the app's `4401`/`4404` into a plain 403; the client doesn't depend on those codes (it reconnects with backoff and falls back to polling) |
| Razorpay webhook with a bogus signature | ✅ 400 "Invalid webhook signature", so **`RAZORPAY_WEBHOOK_SECRET` is configured on Render** (an unset secret would return 503) |
| CORS preflight from `https://evil.example` | ✅ rejected (400, no allow-origin) |
| CORS preflight from `http://localhost:5173` | rejected, so Render's `CORS_ORIGINS` excludes local dev (expected). **Which web origins it does allow is unknown**: no deployed business-web/admin-web URL exists in the repo (E5) |
| `GET /docs`, `GET /api/v1/openapi.json` | ❌ **200, publicly exposed** (E1) |
| Security headers | No `Strict-Transport-Security` / `X-Content-Type-Options` (served via Cloudflare → uvicorn) (P3, → Phase 32) |
| `GET /api/v1/customer/location/search` | ❌ **503 "Address search is temporarily unavailable"**, fixed below (E0) |

### Frontends

| App | API URL source | Result |
|---|---|---|
| customer-mobile | dev: auto from Expo `hostUri`; local release build: git-ignored `.env.production` → Render; EAS `preview` → Render; **EAS `production` → not set** | ⚠️ A10 still open (an EAS production build would call `http://10.0.2.2:8000`) |
| rider-mobile | same, and **both** EAS `preview`/`production` → Render (but `eas.json` is untracked) | ⚠️ commit `rider-mobile/eas.json` |
| business-web / admin-web | git-ignored `.env`: `VITE_API_BASE_URL=http://10.34.146.213:8000` | ⚠️ **stale LAN IP**: this machine is now `192.168.137.237`, so both web apps can't reach a local backend (E4) |
| all | WebSocket URL derived from the API URL (`http→ws`, `https→wss`) | ✅ |
| all | Map style defaults to Carto Voyager (reachable, 200); `*_MAP_STYLE_URL` optional | ✅ (web `.env.example` files don't list `VITE_MAP_STYLE_URL`, P3) |
| all | Client-exposed variables are only `*_API_BASE_URL` and `*_MAP_STYLE_URL` | ✅ no secrets client-side |

### External providers (reachability from here)

Photon search/reverse 200 · OSRM route 200 · Carto style 200 · Expo push API 200 · Razorpay API 200.

### Notifications configuration

**Push is not configured (E2).** Neither app config has `extra.eas.projectId` or an `owner`. There's no `google-services.json`/FCM in either native Android project, and the EAS CLI isn't logged in on this machine. Both apps' push code deliberately skips registration when no projectId exists, and the local DB has **0 push tokens**. In-app notifications are unaffected. rider-mobile's `app.json` also lacks the `expo-notifications` config plugin (icon/colour).

### Issue found and fixed

**E0 (P1): address search and reverse geocoding were down on Render (and on any backend using the public Photon).**
* Reproduced: Render `/customer/location/search` → 503, and locally `search_places("Connaught Place")` raised `PlaceSearchUnavailableError`, while `curl` against Photon returned 200.
* Root cause: `photon.komoot.io` returns **403 to httpx's default `User-Agent`** (`python-httpx/…`) and 200 to an identifying one (same query, verified live). OSRM doesn't do this (200 either way).
* Fix: `_call_photon` now sends `User-Agent: "Say Hi Chai API (address search)"` (`backend/app/services/location_search.py`). Added regression test `test_photon_calls_send_an_identifying_user_agent_not_the_httpx_default`; widened one test fake to accept the new kwarg.
* Verified: the patched `search_places` → 2 real results; `reverse_geocode` → "Outer Circle, New Delhi, Delhi" (postal 110001). **Render stays broken until this is deployed** (see A11).

### Open environment findings (not fixed in this phase)

| ID | Sev | Finding | Phase |
|---|---|---|---|
| **E1** | **P1** | Render runs with `ENVIRONMENT≠production` (`/` reports `docs: /docs`; Swagger and OpenAPI are public). Every production boot guard (weak/placeholder JWT secret, `DEBUG`, missing webhook secret) is therefore **inactive on the deployed backend**. The cause is structural: `ENVIRONMENT=production` refuses `rzp_test_` keys, so a Test-Mode deployment can't use it. Proposed: an `ENVIRONMENT=staging` value that keeps every guard and hides docs but allows test keys. That needs a code change plus a Render setting. | 45 |
| **E2** | **P1** | Push notifications aren't configured (no EAS projectId, no FCM). No device can receive push. | 22, 43 |
| E3 | P1 | = A10: customer-mobile EAS `production` profile has no API URL. | 43 |
| E4 | P2 | business-web/admin-web local `.env` points at a stale LAN IP. Use `http://localhost:8000` (or the current IP when testing from another device). This is a per-machine file, left for you to change. | — |
| E5 | P2 | No deployed web frontends are known. Render's `CORS_ORIGINS` must list their HTTPS origins once they exist. | 43 |
| E6 | P3 | `rider-mobile/eas.json` is untracked. | 43 |
| E7 | P3 | `backend/.env` mode `664`; tighten to `600`. | — |

Files changed: `backend/app/services/location_search.py`, `backend/tests/test_location_search.py`, `docs/final-system-audit.md`.

---

## Phase 3 — Database Migration Validation (2026-10-08) — **PASS after fix**

Destructive steps (full downgrade, re-upgrade) ran only in a throwaway database, `say_hi_chai_migtest`, on the local Postgres 17.10 server, which was dropped afterwards. The dev database `say_hi_chai` only received the one additive migration below. Its row counts were identical before and after (84 users, 47 orders, 1 coupon). Render was not touched.

### Alembic state

| Check | Result |
|---|---|
| `alembic current` (dev) | `20261011_57 (head)` before → `20261012_58 (head)` after the fix ✅ |
| `alembic heads` / `branches` | single head, no branches; `history` is one linear chain of 68 (now 69) revisions ✅ |
| Empty DB → `upgrade head` | ✅ all 68 steps, exit 0 |
| `downgrade base` | ✅ all 68 steps, exit 0. Leaves **0 tables, 0 enum types, empty `alembic_version`** (no residue) |
| Re-`upgrade head` after full downgrade | ✅ 68 steps, exit 0 |
| New migration `20261012_58`: up → down → up | ✅ |
| Offline mode (`alembic upgrade --sql`) | ❌ unsupported. 16 migrations inspect the live connection (idempotent "if exists" guards). Only matters if a DBA needs a SQL script (P3) |
| Downgrade quality | Every revision has a real `downgrade()`, except `20260911_12`, an intentional no-op (Postgres can't drop an enum value) |

### Schema vs. models

Two comparators were run against the dev DB and the freshly migrated DB. The two DBs gave **identical results**, so the dev DB is a faithful product of the migrations.

1. **Alembic autogenerate** (`compare_type` + `compare_server_default`): 64 diffs, classified as follows.
   * 52 × server default exists in the DB where the model has only a Python `default=`. Harmless: the DB is stricter.
   * 8 × unique **constraint** in the DB vs unique **index** in the model (`categories.name`, `coupons.code`, `delivery_partners.user_id`, `notification_preferences.user_id`, `orders.order_number`, `users.email`, `users.phone`). The same uniqueness is enforced either way; the strict comparator confirms the column sets match.
   * **2 × coupon CHECK constraints missing in the DB**, and **`push_tokens.last_seen_at` missing its `now()` default**. These are real; fixed below.
2. **Strict comparator** (custom; covers what autogenerate skips): tables, columns, type/length/NUMERIC precision, nullability, **FK target + `ON DELETE` rule**, CHECK expressions, unique sets, plain and **partial** indexes, enum labels.
   * Result: only the 2 coupon CHECKs. Two further `restaurants` lat/long CHECK hits were false positives: they exist, but Postgres renders them with casts.
   * Every money column is `NUMERIC` with the precision the models declare. Every enum's labels match the model.

### Foreign keys and indexes (dev DB)

* 55 FKs: **every FK column has a supporting index** ✅ (no slow joins or cascading deletes from missing indexes).
* Delete rules: 42 `CASCADE`, 11 `SET NULL`, 2 `RESTRICT`.
* **`CASCADE` chains through financial tables** (D2): `users → orders → order_items/payments → payment_attempts/refunds/cod_collections`, and `users → rider_earnings/rider_settlements/cod_collections → cod_settlement_allocations`. No code path hard-deletes users, orders, payments or restaurants (verified), so today this is only a risk from manual SQL or a future "delete account" feature, which would silently erase money history.
* The app's own hard deletes are safe:
  * products, cart items, categories and service areas cascade only into carts/postal codes, or SET NULL;
  * a coupon delete would cascade into `coupon_redemptions`, but `delete_admin_coupon` refuses (409) once a coupon has been redeemed;
  * the legacy `/coupons` router has no delete.

### Issue found and fixed

**D1 (P2): model constraints never migrated.**
* `Coupon` declares `ck_coupons_discount_value_nonnegative` and `ck_coupons_min_order_nonnegative`, but no migration created them, so Postgres accepted negative coupon values. Both coupon-creation APIs validate (`gt=0`/`ge=0`), so this was missing defence in depth, not an open hole.
* Separately, `push_tokens.last_seen_at` was NOT NULL with no default, although the model declares `server_default=now()`. This is latent: registration sets the value explicitly.
* The test suite couldn't catch either problem: it builds the schema with `create_all()` on SQLite and never runs migrations (A12).
* Fix: new migration `backend/alembic/versions/20261012_58_add_missing_model_constraints.py` adds both CHECKs and the default, with a symmetric downgrade. Existing data had 0 violating rows.
* Verified in the scratch DB:
  * negative `discount_value` → rejected by `ck_coupons_discount_value_nonnegative`;
  * negative `min_order` → rejected by `ck_coupons_min_order_nonnegative`;
  * a valid row inserts.
* Regression guard: `backend/tests/test_migration_model_consistency.py` (static, no DB) asserts that every named CHECK constraint on the models is created by some migration. It was confirmed to **fail** with the new migration removed and to pass with it.

### Open findings

| ID | Sev | Finding | Phase |
|---|---|---|---|
| D2 | P2 | `ON DELETE CASCADE` from `users`/`orders` into payments, refunds, COD and rider earnings/settlements. A single user hard delete erases financial records. Prefer `RESTRICT` on financial children plus soft-delete only. | 30, 31 |
| D3 | P2 | Unknown whether Render runs `alembic upgrade head` on deploy (no deploy config in repo, A24). `20261012_58` and future migrations need it. | 43 |
| D4 | P3 | Offline `--sql` migrations unsupported (16 live-inspection migrations). | 44 |
| D5 | P3 | `alembic.ini` hard-codes a dev connection string with credentials (overridden by `env.py` from `DATABASE_URL`; dev defaults only). | 32 |
| — | P3 | Legacy `CouponCreate` (admin `POST /coupons`) lacks the "percent ≤ 100" check that `AdminCouponCreate` has. | 39 |

Files changed: `backend/alembic/versions/20261012_58_add_missing_model_constraints.py` (new), `backend/tests/test_migration_model_consistency.py` (new), `docs/final-system-audit.md`.
Regression: **1591 passed, 10 skipped** (backend).

---

## Phase 4 — Backend Health Test (2026-10-08) — **PASS after fix**

**Setup:**
* A local uvicorn ran on `127.0.0.1:8765` against **`say_hi_chai_p4`**, a clone of the dev DB made with `CREATE DATABASE … TEMPLATE say_hi_chai` (the dev DB itself is untouched).
* `LOG_LEVEL=INFO`.
* Razorpay keys were blanked, so no real test orders or refunds were created.
* Photon/OSRM were pointed at a dead local port, which also exercises their failure path.

### Startup, health, routes, OpenAPI

| Check | Result |
|---|---|
| Startup | ✅ ready in ~5.4 s; clean log (no warnings or errors) |
| `GET /health` | ✅ 200 `{"status":"ok"}` (real DB round trip) |
| `GET /`, `/docs`, `/redoc`, `/api/v1/openapi.json` | ✅ 200 (dev mode; production hides docs, but see E1) |
| Unknown path / wrong method | ✅ 404 / 405 |
| Route registration | ✅ 220 HTTP operations + 1 WebSocket = 221 (matches Phase 1) |
| OpenAPI | ✅ 3.1.0, 181 paths, 201 schemas, no missing or duplicate `operationId`, no unresolved `$ref`, `HTTPBearer` security scheme |
| DB unreachable (second instance pointed at a dead port) | ✅ process still starts; `/health` → **503** `{"status":"unhealthy","database":"unreachable"}`; API routes → generic 500 `{"detail":"Internal server error"}` with no driver message or credentials in the response. The log contains host and port only (no password) |
| Provider outage (Photon/OSRM down) | ✅ geocoding routes → **503** "temporarily unavailable"; ETA/route-dependent endpoints degrade without errors |

### Unexpected-500 sweep

Every one of the 220 operations was called as **no-auth, customer, restaurant owner, rider, and admin**. The tokens belonged to real clone users with orders, a restaurant, or deliveries. Each call was tried with **real IDs from the clone, random UUIDs, and malformed IDs** (`not-a-uuid'"<>`), plus required query params (valid or junk).

| Sweep | Requests | Status mix | Unexpected 5xx |
|---|---:|---|---:|
| Reads (GET) | 1220 | 200·401·403·404·422, plus 503 only from the dead geocoder | **5 → 0 after fix** |
| Writes (POST/PATCH/PUT/DELETE × no body / `{}` / malformed JSON / type-confused body) | 6040 | 200·204·400·401·403·404·409·422 | **0** |

### Exception handling and logging

| Check | Result |
|---|---|
| 500 response | ✅ `{"detail":"Internal server error"}`, `application/json`; no stack trace, exception text or paths |
| 500 logging | ✅ `ERROR app.main: Unhandled exception on <METHOD> <path>` with the full traceback. ⚠️ Each 500 is logged **twice** (the app handler, plus uvicorn's "Exception in ASGI application") (P3, noise) |
| Auth failures | ✅ logged as user id, role and path only; **no** bearer tokens or passwords in ~4,500 auth-failure lines |
| **Tokens in logs** | ❌ **A16 confirmed:** uvicorn's access log records the WebSocket URL including **`?token=<full access JWT>`**. It is the only JWT anywhere in the log (→ fix in Phase 21/41) |
| Format | plain text `"%(asctime)s %(levelname)s %(name)s: %(message)s"`; events as `event=… key=value`; no request/correlation id |
| Observability level | ⚠️ `log_event()` writes at **INFO**, but the default `LOG_LEVEL` is **WARNING**, so payment/tracking/WebSocket/notification events are dropped unless `LOG_LEVEL=INFO` (Render's value unknown) (→ Phase 41) |
| WebSocket happy path | ✅ customer token + own active order → accepted; immediate snapshot; `ping` → `pong` |

### Issue found and fixed

**A8 (P3): `GET /api/v1/reviews/average/{target_type}/{target_id}` → 500 for an unknown `target_type`.**
* Reproduced for every role.
* Cause: `target_type: str`, converted by `ReviewTarget(target_type)` inside the handler, so the `ValueError` went unhandled.
* Fix: the path parameter is now typed `ReviewTarget`, so FastAPI returns **422** with the allowed values (`backend/app/api/v1/endpoints/reviews.py`).
* Test: `backend/tests/test_review_average_endpoint.py` (fails without the fix, passes with it). The re-sweep found 0 unexpected 5xx.

### Open (not fixed here)

| ID | Sev | Finding | Phase |
|---|---|---|---|
| H1 | P3 | A DB outage surfaces as 500 on API routes; 503 + `Retry-After` would be more accurate. | 26 |
| H2 | P3 | Double traceback logging per 500. | 41 |
| H3 | P2 | `log_event` (INFO) is invisible at the default `LOG_LEVEL=WARNING`. | 41 |
| A16 | P2 | Confirmed: WebSocket access tokens are written to the access log. | 21 |

Files changed: `backend/app/api/v1/endpoints/reviews.py`, `backend/tests/test_review_average_endpoint.py` (new), `docs/final-system-audit.md`.
Regression: **1593 passed, 10 skipped**.

---

## Phase 5 — Authentication E2E (2026-10-08) — **PASS after fixes**, with 2 open P1/P2 gaps needing decisions

**Setup:**
* Live HTTP calls against the local backend on the `say_hi_chai_p4` clone.
* Fresh test users for each role: customer and rider through `POST /auth/register`; restaurant owner, admin and a deactivated customer inserted directly, since those roles are admin-provisioned.
* Tests were paced around the real rate limiters (register 5/min, login 10/min per IP).

### Results — 57 live checks (51 pass initially; 3 fixed; 2 open, plus A3's access-token check, which is expected stateless-JWT behaviour)

| Area | Checks | Result |
|---|---|---|
| **Registration** | customer 201; rider self-service 201; response has no password/hash; email lower-cased; default role CUSTOMER; duplicate email 409; duplicate phone 409; self-register ADMIN → 400; self-register RESTAURANT_OWNER → 400; short password / no-`@` email / 1-char name / unknown role / missing password → 422; 6th attempt per minute → 429 | ✅ 15/15 |
| | `someone@localhost` | ❌→✅ **A26 fixed** (was 500 plus a permanently broken account) |
| **Login** | all four roles → 200 + token pair; `/auth/me` returns the right role for each; login by phone; upper-case email; wrong password / unknown account / deactivated account → 401 with an **identical body**; neither identifier → 422; 11th attempt per minute → 429 | ✅ 15/15 |
| | Timing: wrong password on a real account 43 ms vs unknown account 2 ms | ❌→✅ **A23 fixed** (now 42 ms vs 42 ms) |
| **Tokens** | refresh → new pair, which works; access-as-refresh 401; refresh-as-access 401; expired access 401; expired refresh 401; foreign-secret signature 401; `alg=none` 401; non-UUID `sub` 401 (not 500); missing `sub` 401; non-existent user 401; tampered signature 401; garbage token 401; no header 401; `Basic` scheme 401; deactivated user's live access and refresh tokens → 401 | ✅ 18/18 |
| | Token **without `exp`** accepted (never expires) | ❌→✅ **A27 fixed** |
| | Payload contains only `sub/type/exp/jti` (no role, email or PII); access lifetime 15 min | ✅ |
| **Logout** | `POST /auth/logout` → 200, but the **refresh token keeps working** (30 days) | ❌ **A3 confirmed, open** |
| **Password reset / change** | no route containing `password`, `reset` or `forgot` exists | ❌ **A4 confirmed, open** |
| **Logs** | 0 passwords, 0 JWTs, 0 password hashes in the server logs for Phases 4–5. Failed logins log the attempted identifier (email), which is deliberate for brute-force detection; note it is personal data | ✅ |

### Issues found and fixed

1. **A26 (P2): registration accepted emails that the API can't return.**
   * `RegisterRequest` only checked for `@`, but `UserRead.email` is a strict `EmailStr`.
   * Reproduced live: `…@localhost` → **500**, yet the row was committed. That user could log in, but `/auth/me`, `/users/me` and `/customer/profile` returned **500 forever**, and the email couldn't be registered again (409).
   * Fix: registration validates with the same `EmailStr` adapter → 422 (`backend/app/schemas/auth.py`). The dev DB has 0 users with such emails.
2. **A23 (P3): user enumeration by timing.** Login for an unknown account skipped password hashing. It now verifies against a dummy hash computed at import (`backend/app/services/auth.py`).
3. **A27 (P3): `exp` not required.** PyJWT validates `exp` only when present. `decode_token` now requires `exp`, `sub` and `type` (`backend/app/core/security.py`). All three callers already convert `PyJWTError` to 401.
4. **A9 (P3): flaky test.** `test_admin_with_a_tampered_token_is_rejected` now flips a data-bearing character in the middle of the signature. It passed 30/30 repeated runs (previously ~1/16 failure).

Regression tests: `backend/tests/test_auth_hardening.py` (4 tests; the 3 covering the fixes **fail without them**, confirmed by stashing the fixes). All three fixes were re-verified on the restarted live server.

### Open — need a product decision, not fixed

| ID | Sev | Finding | Options |
|---|---|---|---|
| **A3** | P2 | Logout doesn't revoke anything; refresh tokens stay valid 30 days, with no rotation. | (a) `token_version` on `users`, bumped by logout → "log out all devices" (one migration, small change); (b) a refresh-token table with rotation and reuse detection (per-device, more work). Access tokens can stay stateless (15 min). |
| **A4** | P1 | No password change or reset for any role. | Authenticated **change-password** needs no provider and is quick. **Forgot-password** needs an email or SMS/OTP provider (none is configured), so it needs a choice of provider. |

Files changed: `backend/app/schemas/auth.py`, `backend/app/services/auth.py`, `backend/app/core/security.py`, `backend/tests/test_auth_hardening.py` (new), `backend/tests/test_admin_authentication.py`, `docs/final-system-audit.md`.
Regression: **1597 passed, 10 skipped**.

---

## Phase 6 — Role Authorization (2026-10-08) — **PASS** (no defects)

**Method:**
* For each of the 220 HTTP operations, the **allowed role set** was derived from the live app's dependency graph, including the role tuples captured inside `require_roles(...)` closures.
* Every operation was then called on the clone server with each disallowed caller (no token, plus whichever of CUSTOMER/RIDER/RESTAURANT_OWNER/ADMIN is not allowed), using real IDs.
* Allowed roles were also checked on every GET, to make sure they aren't wrongly blocked.

### Role matrix

| Check | Calls | Result |
|---|---:|---|
| Disallowed callers on every protected operation | 758 | ✅ **0 unauthorized 2xx**: 198 × 401 (no token), ADMIN 106 × 403, CUSTOMER 144 × 403, RESTAURANT_OWNER 157 × 403, RIDER 153 × 403. **Every denial was exactly 401/403** (none slipped through to 404/422/5xx) |
| Allowed roles on every protected GET | 96 | ✅ 0 blocked by a role gate (88 × 200; 8 × 404 for IDs that role doesn't own) |

The master command's examples are all covered by the matrix: CUSTOMER → admin/rider endpoints 403; RIDER → admin/restaurant endpoints 403; RESTAURANT_OWNER → admin 403; ADMIN → customer-only operations (cart, checkout, place order, reviews) 403, while ADMIN reaches all 75 admin operations.

### State-dependent authorization (live scenarios) — 30/30

| Scenario | Result |
|---|---|
| Owner A → owner B's restaurant through the portal (`dashboard`, `orders`, `products`, `hours`, `status`, `profile` with `?restaurant_id=<B>`), including **valid-body** `PATCH /restaurant/status` and `PUT /restaurant/hours` | ✅ 403 "You do not manage this restaurant" |
| Owner A → legacy `PATCH/DELETE /restaurants/<B>`, `/open-status`, `/images` | ✅ 403 |
| Owner A → accept/reject/preparing/ready/view owner B's order | ✅ 404 (scoped to A's own restaurant) |
| Owner B's restaurant after all attempts | ✅ name, `is_active`, `is_open` unchanged |
| **PENDING (unapproved) rider**: go online / list available / accept a ready order / report location | ✅ 403 for each ("application is still under review", "Go online to …") |
| Tracking WebSocket for an active order as owner / rider / admin | ✅ handshake rejected (403) |
| Tracking WebSocket as the order's own customer | ✅ accepted, snapshot received |

Phase 5 also confirmed that a deactivated user's live tokens are rejected (401) on the next request.

### Observation (not an authorization defect)

| ID | Sev | Finding | Phase |
|---|---|---|---|
| D6 | P2 | `orders.restaurant_id`, `order_items.restaurant_id` and `order_items.product_id` are `VARCHAR(64)` **without foreign keys**, by design as snapshots, but this allows orphans. The dev DB has 0 orphaned orders of 47 today. | 30 |

Files changed: `docs/final-system-audit.md` only. No code changed, so the Phase 5 regression (1597 passed) still applies.

---

## Phase 7 — IDOR Security Testing (2026-10-08) — **PASS after fix**

**Method:**
* Same-role pairs were taken from the clone: customer A/B, approved rider A/B, single-restaurant owner A/B.
* Acting as **A**, every route of that role whose path or query carries a *private* ID was called with **B's** IDs. Private IDs: `order_id`, `address_id`, `payment_id`, `review_id`, `notification_id`, cart `item_id`, `user_id`/`customer_id`; for riders `order_id`, `document_id`, `assignment_id`, `rider_id`; for owners `order_id`, `product_id`, `category_id`, `restaurant_id`.
* Each request carried a **schema-generated valid body**, so an ownership check couldn't hide behind a 422.
* The rider attacker was put online, so "go online first" gates couldn't mask ownership checks.
* All of B's rows were fingerprinted (md5 of `row_to_json`) before and after.

### Path/query ID substitution

| Role pair | Requests with victim IDs | Result | Victim data |
|---|---:|---|---|
| Customer A → Customer B | 19 | ✅ 18 × 404, 1 × 403, **0 × 2xx** | unchanged |
| Rider A → Rider B (B's assigned orders, documents, assignments, notifications) | 12 | ✅ 12 × 404, **0 × 2xx** | unchanged |
| Owner A → Owner B (orders, products, menu categories, restaurant) | 29 | ✅ 27 × 403; 1 × 422 on `PUT /restaurant/hours` (shown to be 403 with a valid body in Phase 6); 1 × 200 on **public** `GET /restaurants/{id}` (legitimate) | unchanged |

### Body-level IDOR and mass assignment — 19/19 after fix

| Attempt | Result |
|---|---|
| Customer A places an order with B's `address_id` (A has a real cart) | ✅ 422 "Select a valid delivery address."; 0 orders created |
| Checkout with `?address_id=<B>` | ✅ B's address is not returned or selected |
| Customer A: `POST /payments/create {order_id: B}`, `POST /customer/orders/{B}/payment` | ✅ 404 "Order not found" |
| Customer A: `GET`/`verify` (valid body)/`retry` on B's `payment_id` | ✅ 404; B's payment status unchanged |
| Customer A edits B's review | ✅ 404; B's review unchanged |
| Customer profile PATCH with smuggled `role:"ADMIN"`, `is_active`, `id:<B>`, `password_hash` | ✅ ignored (role/active unchanged; B untouched) |
| Address create with smuggled `user_id:<B>` | ✅ created under A |
| PENDING rider profile PATCH with `approval_status:"APPROVED"`, `is_online`, `role`, `average_rating` | ✅ all ignored (still PENDING/offline/RIDER/0.00) |
| Owner profile PATCH with `owner_id:<B's owner>`, `approval_status`, `average_rating`, `total_ratings`, `is_active` | ✅ all ignored |
| Owner A creates a product in, or moves a product into, B's **menu category** | ✅ 422 "category_id must belong to your own restaurant" |
| Owner A creates a product with body `restaurant_id:<B>` | ✅ ignored; product lands in A's restaurant |
| Customer changes own profile email to **another account's email** | ❌→✅ **A28 fixed** (was 500) |

### Issue found and fixed

**A28 (P2): customer email change had no uniqueness check.**
* `PATCH /api/v1/customer/profile` with another user's email (any case) hit the `users.email` unique constraint as an unhandled `IntegrityError` → **500**.
* The DB constraint prevented an actual takeover, but the 500-vs-200 difference was an **account-enumeration oracle**.
* The rider profile already returned 409; admin endpoints can't change emails (verified).
* Fix (`backend/app/api/v1/customer/profile.py`): pre-check → **409**, plus an `IntegrityError` → 409 fallback for the concurrent race. Re-saving your own email in different case still works.
* Tests added to `backend/tests/test_customer_profile.py`; they fail without the fix (confirmed). Live re-check: 409 for a taken email, 200 for your own.

### Observation

| ID | Sev | Finding | Phase |
|---|---|---|---|
| I1 | P3 | Public `GET /restaurants/{id}` and the restaurant list include `owner_id` (the owner's user UUID). Not exploitable on its own, since every owner-scoped route re-checks ownership, but it isn't needed by the public. | 32 |

Files changed: `backend/app/api/v1/customer/profile.py`, `backend/tests/test_customer_profile.py`, `docs/final-system-audit.md`.
Regression: **1599 passed, 10 skipped**.

---

## Phase 8 — Customer Registration / Profile (2026-10-08) — **PASS after fixes**, one data-model decision open

Live checks ran against the clone server. Login, logout and token behaviour are in Phase 5; mass assignment and the email-collision fix are in Phase 7.

### Results — 24 live checks (19 pass first time; 3 fixed; 2 open)

| Area | Result |
|---|---|
| Register → GET profile returns own data; no password/hash in the response; legacy `/users/me` agrees | ✅ |
| Duplicate email in a different case with surrounding spaces → 409 | ✅ |
| PATCH validation: 1-char name, 121-char name, invalid email, `@localhost`, 2049-char image, numeric name → 422 | ✅ |
| Empty PATCH and explicit `null`s → 200, nothing changed or cleared | ✅ |
| Rename + email change → trimmed and lower-cased; **persisted in the DB**; login with the new email works, the old email fails; the live token stays valid (`sub` = user id) | ✅ |
| Wrong role (rider token) on `/customer/profile` → 403 | ✅ |
| Whitespace-only name `"   "` → saved as **empty string** | ❌→✅ **A29 fixed** |
| Phone `"abcdefgh"` accepted at registration | ❌→✅ **A30 fixed** |
| **Same phone in another format** (`+91 98914 39016` vs `9891439016`) → a **second account** | ❌ **A31 open (decision)** |
| `profile_image: "javascript:alert(1)"` accepted | ⚠️ P3 note: no executable sink today. admin-web never renders it; business-web/mobile use it only as `<img src>`/`Image uri`. Left as is so the rider app's free-text field isn't broken |
| Customer can change phone via profile | ⚠️ P3 gap: `ProfileUpdate` has no `phone` (riders can change theirs). Feature, not a defect |
| Password change/reset | ❌ A4 (open since Phase 5) |

### Issues found and fixed

* **A29 (P3): blank names.** `min_length=2` ran *before* `.strip()`, so `"   "` passed and was saved as `""`. Affected registration, customer profile and rider profile.
* **A30 (P2): phone format never validated.** Any 8–20 characters were accepted.
* Fix: shared `PersonName` and `PhoneNumber` types in `backend/app/schemas/user.py`, used by `RegisterRequest`, the customer `ProfileUpdate` and `RiderProfileUpdate`.
  * Names are stripped **before** the length check.
  * Phones must be digits with optional spaces, dashes or parentheses and an optional leading `+`, with **8–15 digits**.
  * The stored phone value is unchanged (the stripped input), so existing exact-match phone logins keep working.
* Tests: `test_auth_hardening.py` (+3) and `test_customer_profile.py` (+1) fail without the fixes (confirmed). Common formats (`9876543210`, `+91 98765 43211`, `(022) 2345-6789`) still register. Live re-check: garbage phone 422, blank name 422, valid `+91 …` 201.

### Open — needs a decision

| ID | Sev | Finding | Why not fixed here |
|---|---|---|---|
| **A31** | P2 | Phones aren't normalized, so the same number in different formats creates separate accounts, and phone login needs the exact original formatting. | Dev data is already mixed: 54 × 10-digit, 27 × 11-digit, 22 other formats across users/addresses/restaurants, and **8 groups of users already share the same last 10 digits**. Canonicalizing (e.g. E.164 `+91XXXXXXXXXX`) needs a data migration with a conflict-resolution rule plus matching login and lookup changes. |

Files changed: `backend/app/schemas/user.py`, `backend/app/schemas/auth.py`, `backend/app/schemas/rider.py`, `backend/app/api/v1/customer/profile.py`, `backend/tests/test_auth_hardening.py`, `backend/tests/test_customer_profile.py`, `docs/final-system-audit.md`.
Regression: **1603 passed, 10 skipped**.

---

## Phase 9 — Customer Address System (2026-10-08) — **PASS after fixes** (and two serious hidden bugs surfaced)

Live checks ran against the clone server with **real** Photon/OSRM (Phase 2 User-Agent fix), keeping geocoding calls to a handful.

### Address system — 44 live checks: 40 → **43 after fixes** (1 open = A17)

| Area | Result |
|---|---|
| Forward geocoding (`/customer/location/search`) → results with lat/lon | ✅ |
| Reverse geocoding (`/customer/location/reverse`) → city/postal/formatted address/`place_id` | ✅ |
| Geocoding input validation: lat 91, lon −181, `abc`, missing lon, `NaN`, `Infinity`, empty `q`, 201-char `q` → 422 | ✅ |
| **Map-picker flow:** create from reverse-geocode data → coordinates persisted **exactly** (7 dp, no float drift); `formatted_address` + `place_id` stored as sent; API echoes identical coordinates | ✅ |
| Create validation: out-of-range lat/lon, 8 decimal places, `NaN`/`Infinity`, missing city, short line, lat without lon → 422 | ✅ |
| **First address becomes default when `is_default` is omitted** | ❌→✅ **A32 fixed** |
| Second address not default; set-default switches; exactly one default; default listed first | ✅ |
| Edit fields and coordinates → persisted; invalid latitude → 422 | ✅ |
| PATCH `{"latitude": null}` alone → **half a pin saved** | ❌→✅ **A33 fixed** |
| Delete (soft) → gone from list; GET/PATCH/set-default on it → 404; row kept | ✅ |
| **Deleting the default promotes a remaining address** | ❌→✅ **A34 fixed** |
| Customer B → A's address: GET/PATCH/default/DELETE → 404; not in B's list; A's data untouched | ✅ |
| Pin in Delhi saved with a Lucknow postal code | ❌ **A17 open**: postal code isn't cross-checked against coordinates (→ Phase 20) |

**Address fixes:**
* **A32 (P2):** the endpoint passed `model_dump()`, which always carries the schema default `is_default=False`, so the service's first-address rule never ran. Customers ended up with **no default address**. Now passed only when the client set it.
* **A33 (P3):** the "both coordinates or neither" rule existed only on create. PATCH now validates the *resulting* pair → 422.
* **A34 (P2):** sessions don't autoflush, so after marking the address inactive, the promotion query still saw it as the active default and "promoted" the address being deleted. Now flushed first, and the deleted row's `is_default` is cleared.
* Files: `backend/app/api/v1/endpoints/addresses.py`, `backend/app/services/addresses.py`.
* Tests: `backend/tests/test_address_defaults_and_coordinates.py` (3 of the 4 tests fail without the fixes).

### Root cause of A34, and a major test-infrastructure finding (A12 extended)

Production sessions use `sessionmaker(autoflush=False)` (`app/db/session.py`). **Every test request session was a plain `Session(engine)`, which defaults to `autoflush=True`.** The shared `conftest.py` fixture plus 78 per-file `override_get_db` overrides in 68 other test files all masked a whole class of production bugs, where a caller changes an object and a later query or `refresh` doesn't see the change.

All 79 request-serving test sessions were switched to `autoflush=False` to match production (seeding sessions left alone). That immediately exposed **13 failing tests**, which led to two serious production defects plus one test artifact:

**A35 (P1): admin rider assignment stranded orders; rejection/cancellation reasons were lost.**
* `assign_rider_to_order` and the reject/cancel paths set `order.rider_id` / `order.cancelled_reason` and then call `transition_order_status`. That function runs a Core `UPDATE … SET status` and then **`db.refresh(order)`**, which reloaded the row and **silently discarded the unflushed fields**.
* **Reproduced on PostgreSQL:** admin assign → HTTP 200, but DB `status=rider_assigned, rider_id=NULL`, so no rider can see or act on the order. Restaurant reject with a reason → `cancelled_reason=NULL`.
* **Your dev DB already contains 5 orders in an active-delivery state with no rider, and 3 cancelled/rejected orders with no reason**, consistent with real occurrences.
* Fix: `transition_order_status` flushes the caller's pending changes before its conditional UPDATE, in the same transaction; a lost race still rolls everything back (`backend/app/services/orders.py`).
* Verified live on Postgres after restart: rider persisted, reason persisted.
* Tests: `backend/tests/test_order_transition_pending_fields.py` (both fail without the fix), plus the 11 existing admin-assignment tests that now run production-like.

**A36 (P1): refunds settled by webhook never updated the payment.**
* `refund.processed` set the refund to COMPLETED, but `recompute_payment_refund_status` sums refunds with a fresh SELECT. Without a flush it saw the refund as still PROCESSING, so the **payment stayed `paid` forever** instead of becoming `partially_refunded`/`refunded`.
* The same bug had already been found and patched *only* inside `create_refund` (its "Partial Refunds Phase 25" comment); the webhook path was missed.
* Fix: `recompute_payment_refund_status` now flushes itself, covering every caller (`backend/app/services/payment/refund_service.py`).
* `tests/test_refund_e2e.py` fails without the fix.
* The dev DB has no refunds yet, so it is latent: it would hit the first real asynchronously settled refund.

**Test artifact (no production bug):** `test_two_concurrent_complete_delivery_calls_never_double_credit_the_rider` simulated a stale concurrent read by *assigning* `order.status`, a dirty change that the new flush wrote to the DB. A real stale read is loaded state, not a pending change, and no production code assigns `order.status` directly (verified). The test now uses `set_committed_value()` and still proves that the losing transition is rejected.

### Open

| ID | Sev | Finding | Phase |
|---|---|---|---|
| A17 | P2 | Postal code isn't cross-checked against the pin. | 20 |
| D7 | P2 | Data repair needed if the same bug hit Render: orders in `rider_assigned/picked_up/out_for_delivery` with `rider_id IS NULL` (5 in dev). They need an admin reassign or cancel, which the app can do once A35 is deployed. | 26/30 |
| — | P3 | No DB-level guarantee of one default address per user (no partial unique index), so a concurrent set-default could leave two. | 28 |

Files changed: `backend/app/api/v1/endpoints/addresses.py`, `backend/app/services/addresses.py`, `backend/app/services/orders.py`, `backend/app/services/payment/refund_service.py`, `backend/tests/conftest.py` and 68 other test files (`autoflush=False` in request sessions), `backend/tests/test_rider_concurrency_and_failure_handling.py`, new `backend/tests/test_address_defaults_and_coordinates.py` and `backend/tests/test_order_transition_pending_fields.py`, `docs/final-system-audit.md`.
Regression (with production-like `autoflush=False` request sessions everywhere): **1609 passed, 10 skipped, 0 failed**.

---

## Phase 10 — Restaurant Discovery (2026-10-08) — **PASS after fixes**

**Method:** controlled visibility states were set directly in the throwaway clone (one approved restaurant, one **PENDING**, one **deactivated**, one **manually closed**, then restored). Every customer discovery endpoint was exercised against them: list, legacy list, detail, menu categories, menu products, product detail, search, global categories, and pagination.

### Results — 39 live checks: 35 → **38 after fixes** (1 open = A7) + 2 extra probes

| Area | Result |
|---|---|
| List shows approved + active only; PENDING and deactivated hidden (customer and legacy lists) | ✅ |
| Manually closed restaurant listed with `is_open=false` | ✅ |
| Detail / menu / menu categories of PENDING or deactivated restaurants → 404 (customer and legacy) | ✅ |
| **Product detail of a PENDING / deactivated restaurant's product** → was **200**, and it could be **added to a cart** | ❌→✅ **A37 fixed** (now 404 for both) |
| Unavailable product hidden from the menu; its detail → 404 | ✅ |
| Customer detail exposes no `owner_id` (legacy `/restaurants` still does, I1) | ✅ |
| Search finds restaurants by name; never returns PENDING restaurants or their products | ✅ |
| Search robustness: no match, `' OR 1=1 --`, `%`, `_`, Unicode (`चाय`) → 200, never 500 | ✅ |
| **`q=%` matched every restaurant** (25 results); `_` matched any character | ❌→✅ **A38 fixed** |
| Global categories → 200; inactive category detail → 404 | ✅ |
| Pagination: `limit=0`/`101`/`abc`, `offset=-1` → 422; no duplicates across pages | ✅ |
| Unknown restaurant id → 404; malformed → 422 | ✅ |
| Restaurant ratings aggregated | ❌ **A7 open**: 0 restaurants have `average_rating > 0`, yet the list sorts by it (→ Phase 23) |
| Products in a **disabled menu section** | ⚠️ **A39 open (product decision)**: the section is hidden from customers, but its products stay in the menu (customer-mobile shows them under a generic "Menu" heading) and stay orderable |
| Customer-app empty/error handling (home, search, restaurant, category) | ✅ loading, error + "Try again", and empty states present; P3: the category screen's empty copy says "No restaurants are open right now" even when a category simply has none |
| API failure (DB down) | covered in Phase 4: generic 500 / `/health` 503 |

### Issues found and fixed

* **A37 (P2): hidden restaurants' products still reachable.**
  * `get_customer_visible_product_or_404` checked only the product's own flags. It's used by `GET /customer/products/{id}` **and** `cart.add_item`, so a product of a PENDING/rejected/suspended or deactivated restaurant could be viewed and **added to a cart**. Checkout's restaurant check still blocked the order.
  * Fix: the lookup now joins `Restaurant` and requires `is_active` + `APPROVED`, the same rule `search_products` uses (`backend/app/services/products.py`).
* **A38 (P3): LIKE wildcards not escaped in customer search.**
  * Fix: new `backend/app/core/search_patterns.py` (`contains_pattern` escapes `\`, `%`, `_`), used with `escape=` in restaurant, product and category search (`restaurants.py`, `products.py`, `categories.py`).
  * Admin-only searches were left as they are (no exposure).
* Tests: `backend/tests/test_discovery_visibility.py` (4 tests; the 3 bug tests fail without the fixes, confirmed). Live re-run: 38/39 (only A7).

Files changed: `backend/app/services/products.py`, `backend/app/services/restaurants.py`, `backend/app/services/categories.py`, `backend/app/core/search_patterns.py` (new), `backend/tests/test_discovery_visibility.py` (new), `docs/final-system-audit.md`.
Regression: **1613 passed, 10 skipped, 0 failed**.

---

## Phase 11 — Cart Validation (2026-10-08) — **PASS after fixes**

Live checks ran against the clone server as a fresh customer. Prices, availability and restaurant status were changed directly in the throwaway clone to simulate owner and admin actions.

### Results — 31 live checks: 29 → **31 after fixes**

| Area | Result |
|---|---|
| Empty cart → 200, no items, zero totals | ✅ |
| **Price manipulation:** add with smuggled `unit_price`, `price`, `subtotal`, `total`, `restaurant_id` → all ignored; server price used; cart bound to the product's own restaurant | ✅ |
| PATCH quantity with smuggled `unit_price` → ignored | ✅ |
| Totals are exact Decimals: 33.33 × 3 = **99.99**; total = subtotal + restaurant's configured fee + tax − discount | ✅ |
| Quantity validation on add/update: 0, −1, −5, 101, 1.5, `"abc"`, 10¹² → 422; omitted → 1 | ✅ |
| **Repeated adds stacked one line to 301 units** | ❌→✅ **A40 fixed** |
| Restaurant restriction: product from another restaurant → 409; cart unchanged | ✅ |
| Owner price change while in cart → cart shows the new price; subtotal recomputed | ✅ |
| Product becoming unavailable → dropped from the cart and reported in `removed_items` | ✅ |
| Unknown or unavailable product → 404; unknown item update/remove → 404 | ✅ |
| **Restaurant suspended or unapproved while in cart → items stayed in the cart** | ❌→✅ **A41 fixed** |
| Remove last item → empty; restaurant unbound (can add from another restaurant); clear cart → empty | ✅ |
| Cart item IDOR (another customer's `item_id`) | ✅ covered in Phase 7 (404) |

### Issues found and fixed

* **A40 (P2): unbounded quantity.**
  * `CartItemCreate` limits a *request* to 1–100, but `add_item` did `quantity += quantity` on an existing line, so repeated adds reached 301 (and any size). That allows absurd orders and COD exposure.
  * Fix: the accumulated quantity is checked against a shared `MAX_ITEM_QUANTITY = 100` (`backend/app/schemas/cart.py`, `backend/app/services/cart.py`).
  * The error is **422, not 409**, because customer-mobile treats *any* 409 from add-to-cart as "cart belongs to another restaurant" and offers to **clear the cart** (`app/restaurants/[id].tsx`). With 422 the app shows its normal "Unable to add item" alert with the backend message (verified live: "You can add at most 100 of one item.").
  * The dev DB has no cart or order lines over 100.
* **A41 (P3): stale cart for unapproved restaurants.**
  * `sync_cart_with_catalog` dropped items when the restaurant was *deactivated* but not when it was suspended, rejected or pending. Checkout still blocked those orders, but the cart showed orderable items.
  * Fix: now requires `APPROVED` too, matching A37. A cart emptied by re-validation also releases its coupon.
* Tests: `backend/tests/test_cart_limits_and_sync.py` (both fail without the fixes, confirmed). Live re-run: 31/31.

Files changed: `backend/app/schemas/cart.py`, `backend/app/services/cart.py`, `backend/tests/test_cart_limits_and_sync.py` (new), `docs/final-system-audit.md`.
Regression: **1615 passed, 10 skipped, 0 failed**.

---

## Phase 12 — Checkout Validation (2026-10-08) — **PASS after fix**, 2 decisions open

**Setup:**
* Controlled fixtures were inserted into the clone: a restaurant (fee ₹30, minimum ₹100, in Lucknow), products at ₹120.00 and ₹45.50, a customer with a pinned address, and 8 coupons (flat, capped percent, larger-than-subtotal, expired, other-restaurant, single-use, inactive, not-yet-started).
* Calls went through the live checkout and order APIs, with COD as the method (Razorpay is blanked on the clone server).

### Results — 34 live checks: 33 pass, 1 open (A44); plus 1 defect found by code review and fixed (A42)

| Area | Result |
|---|---|
| Empty cart → order refused (422) | ✅ |
| Preview: subtotal 211.00, fee 30.00, tax 0.00, total 241.00, address preselected, no issues | ✅ |
| **Order with smuggled `subtotal/delivery_fee/discount/tax/total/items[].price/restaurant_id/status:"delivered"/is_paid/payment_status:"paid"/user_id`** → 201 with **stored totals identical to the preview**; status `placed`, unpaid, own user, real restaurant; order lines at catalogue prices | ✅ |
| Invariant: total = subtotal + fee + tax − discount; cart emptied after the order | ✅ |
| Below minimum order → preview issue "add 54.50 more" + order refused | ✅ |
| Restaurant toggled closed / suspended → refused | ✅ |
| **Today's opening window (IST) already ended → refused; inside the window → accepted** | ✅ (after the A42 fix) |
| Payment method `upi`, `CASH`, `wallet`, `""` → 422; `razorpay` with the provider unconfigured → 422 "choose Cash on Delivery", no order | ✅ |
| Coupons: flat 50 on 120 → 50; 10% capped at 5 → 5; 500 off on 120 → **capped at subtotal**, total = delivery fee (never negative) | ✅ |
| Coupons expired / other restaurant / not yet started → 400; inactive / unknown → 404 | ✅ |
| Order with a coupon and a client `discount:"120.00", total:"0.00"` → stored discount **50**, total **100**; redemption row written | ✅ |
| Per-customer limit 1: second use → 400 | ✅ |
| Coupon became ineligible (min order raised) after applying → **not honoured** at order time (discount 0) | ✅ (see A43) |
| Owner changed price/fee after the preview → order uses **current** server values (₹150 + ₹40 = ₹190; preview had shown ₹150) | ✅ authoritative (see A43) |
| Address outside configured service areas → 422 "Delivery is currently unavailable at this location." | ✅ |
| **Address ~1,200 km away** (Mumbai pin, Lucknow restaurant), no service areas configured → **order accepted** | ❌ **A44 open** |

### Issue found and fixed

**A42 (P1): restaurant opening hours were compared in UTC.**
* Owners enter hours as plain local times (business-web `<input type="time">`, no timezone shown), but `is_within_operating_hours`/`get_today_hours` compared them with **UTC** clock time and weekday.
* A restaurant set to 09:00–21:00 was really accepting orders **14:30–02:30 IST**: closed at breakfast and lunch, open after midnight. Near midnight the wrong weekday's row applied.
* Affects checkout acceptance and the owner's "accepting orders now / today's hours" status.
* Fix:
  * New `BUSINESS_TIMEZONE` setting (default `Asia/Kolkata`, added to `.env.example`).
  * Times and weekday are converted to it before comparing (`backend/app/services/restaurant_hours.py`, `backend/app/core/config.py`).
  * If the host lacks a tz database, it falls back to the exact +05:30 offset (India has no DST), so no new dependency.
* Tests: 2 added to `backend/tests/test_restaurant_hours_and_status.py` (09:30/13:00 IST open, 22:00/01:00 IST closed; Sunday 23:00 UTC = Monday in India). Both fail without the fix; the existing UTC-instant tests still hold. Verified live.
* Exposure: 1 restaurant in the dev DB has hours configured.

### Open — need a decision

| ID | Sev | Finding | Recommendation |
|---|---|---|---|
| **A44** | P1 | **No maximum delivery distance.** `validate_delivery_location` only checks that coordinates are valid. When no service area is configured, any pinned address anywhere is accepted, which means undeliverable COD orders. Postal-code service areas are the only gate, and they trust the typed postal code (A17). The dev DB has 1 service area; all 25 pinned dev orders are ≤1.2 km, so it hasn't happened yet. | Add `MAX_DELIVERY_DISTANCE_KM` (e.g. 15–20 km; optionally per restaurant) enforced whenever both coordinates exist. The value is a business choice. |
| **A43** | P2 | The order silently uses current prices, fees and coupon eligibility, which can differ from the checkout preview the customer saw (₹150 shown → ₹190 placed; coupon dropped). Server-authoritative is correct, but the customer isn't asked to reconfirm. | Let the client send the `expected_total` it showed; return 409 "prices changed, please review" on mismatch. Needs a matching customer-mobile change. |
| — | P3 | Overnight hours (e.g. 18:00–02:00) are rejected by the schema ("aren't supported yet"). | Product decision. |

Files changed: `backend/app/services/restaurant_hours.py`, `backend/app/core/config.py`, `backend/.env.example`, `backend/tests/test_restaurant_hours_and_status.py`, `docs/final-system-audit.md`.
Regression: **1617 passed, 10 skipped, 0 failed**.

---

## Phase 13 — Razorpay Test Mode (2026-10-08) — **PASS after fixes** (real refund not run, by choice)

**Setup:**
* The local backend ran on the clone DB with the **real Razorpay Test Mode keys** (`rzp_test_***`), so order creation and the payment/order fetches inside `/verify` hit Razorpay for real.
* The **real success path** used the genuinely captured device payment from Razorpay Phase 9 (`order_TlN7vEPKJ06PrP` / `pay_TlN9BZ1tXWlnMu`, ₹20). It was bound to a ₹20 order in the clone only; Render was not touched.
* Webhooks were correctly HMAC-signed synthetic events using the real payment entity fetched from Razorpay.
* **No real refund was issued:** the only captured payment is shared with Render, and refunding it at Razorpay would desync Render's records. Refunds were exercised through the `refund.processed`/`refund.failed` webhooks instead. The admin refund API call to Razorpay is covered by the existing mocked-provider suite.
* Earlier Razorpay protocol results (phases 1–14, plus Phase 9 today) stand; see `docs/razorpay-test-audit.md`.

### Results — 34 live checks: 31 → **33 after fixes**, 1 deferred (P7)

| Flow | Result |
|---|---|
| **Create Razorpay order:** place online order → start payment → real Razorpay order with amount = order total in **paise**, INR, `receipt` = backend order id, status `created` | ✅ |
| Response exposes only `razorpay_key_id` (public); no secret anywhere | ✅ |
| Starting payment again → **same** Razorpay order; exactly one payment row (idempotent) | ✅ |
| **Invalid signature** → 400, order unpaid | ✅ |
| Valid HMAC for a payment id Razorpay never issued → rejected, order unpaid | ✅ (P3 note: answered **502 "Unable to reach the payment provider"**, because Razorpay's own 400 is reported as a connectivity error) |
| Verify against a different Razorpay order id → rejected | ✅ |
| **Successful payment** (real captured ₹20): signature ✓ → Razorpay payment & order fetched → amount/currency/state agree → **PAID**, order paid, now **visible to the restaurant** | ✅ |
| **Wrong amount:** internal ₹25 vs Razorpay ₹20 → 400, not paid | ✅ |
| **Payment failure / cancellation:** `payment.failed` webhook → FAILED with Razorpay's reason, order unpaid; **retry** → PENDING on the same Razorpay order | ✅ |
| Webhook with wrong / missing signature → 400, rejected before any state change | ✅ |
| **Late capture (audit P1):** verify after the 30-min window → 410 expired; the real `payment.captured` webhook then **repairs it to PAID** | ✅ (works as long as the webhook is configured, which it is on Render, Phase 2) |
| **Webhook retry:** same event id → stored once; same capture under a new id → `duplicate_ignored` | ✅ |
| **Duplicate payment:** `/verify` again after PAID → 409, still PAID, one payment row | ✅ |
| `payment.failed` after PAID → ignored | ✅ |
| Webhook with wrong amount → `amount_mismatch`, not paid | ✅ |
| **Partial refund:** `refund.processed` ₹5 → refund COMPLETED, payment **PARTIALLY_REFUNDED** (A36 fix verified live); duplicate → ignored; `refund.failed` → refund FAILED, payment unchanged; remaining ₹15 → **REFUNDED** | ✅ |
| **Audit P5:** `payment.captured` arriving after REFUNDED → stayed REFUNDED | ❌→✅ fixed (was flipped back to **PAID**) |
| **Audit P6:** webhook-confirmed capture recorded as a PaymentAttempt | ❌→✅ fixed |
| **Audit P9:** COD payment creatable for an online order | ❌→✅ fixed |
| Audit P7: creation-time attempt stays `pending` forever | ⏸ deferred to Phase 31 (reconciliation semantics) |
| Secrets in server logs (key secret, webhook secret, JWT secret, signatures) | ✅ 0 occurrences (compared in-process; values never printed) |

### Issues found and fixed

* **P5 (P2, financial state corruption, reproduced live):**
  * `payment.captured` only skipped `PAID`, so a late or re-delivered capture flipped a **REFUNDED** payment back to **PAID**, marked the order paid again and re-sent "payment successful" notifications.
  * The `payment.failed` handler had the same flaw: a late failure would downgrade a refunded payment to FAILED.
  * Fix: both now treat `PAID / PARTIALLY_REFUNDED / REFUNDED / REFUND_PENDING` as already captured (`backend/app/services/payment/webhook_service.py`).
* **P6 (P3, audit trail):**
  * A capture confirmed only by webhook left no PaymentAttempt.
  * Fix: the webhook now upserts the attempt for that Razorpay payment id. One attempt per provider payment (`uq_payment_attempts_provider_payment_id`), so an earlier expired/failed verify attempt is brought up to PAID rather than duplicated.
* **P9 (P3, verified live):**
  * Legacy `POST /payments/create` trusted the body's `method`, so a customer could create a **COD** payment for an online order (201), leaving it permanently unpayable online.
  * Fix: the method must equal `order.payment_method`, otherwise 409 (`backend/app/api/v1/endpoints/payments.py`).
* Tests:
  * `backend/tests/test_webhook_capture_after_refund.py` (6 tests: P5 × 3 statuses, failed-after-refund, P6 new + P6 after expiry); all fail without the fixes.
  * `backend/tests/test_payment_api.py`: the existing 503 test now uses a genuinely online order, plus a new P9 409 test that fails without the fix.

### Still open (Razorpay)

* **P7** → Phase 31.
* Real refund against Razorpay → needs either a disposable new device payment or your explicit go-ahead to refund `pay_TlN9BZ1tXWlnMu` (which would desync Render).
* P3 message above → Phase 29.

Files changed: `backend/app/services/payment/webhook_service.py`, `backend/app/api/v1/endpoints/payments.py`, `backend/tests/test_webhook_capture_after_refund.py` (new), `backend/tests/test_payment_api.py`, `docs/final-system-audit.md`.
Regression: **1624 passed, 10 skipped, 0 failed**.

---

## Phase 14 — COD Validation (2026-10-08) — **PASS after fix**

**Setup:**
* Full live lifecycle on the clone server: a fresh customer, restaurant and admin, plus two **fresh approved riders** so the COD balance contains only this test's cash.
* Order: 2 × ₹123.45 + ₹30 fee = **₹276.90**.

### Results — 44 live checks: 42 → **43 after fix**, 1 P3 UX note

| Step | Result |
|---|---|
| **COD checkout:** order 201; client `total`/`cod_amount` ignored → server total **276.90**; unpaid at placement; visible to the restaurant immediately (no online-payment gate) | ✅ |
| **COD/Razorpay separation:** starting "payment" on a COD order creates a COD row with **no Razorpay order**; Razorpay `/verify` on it → 400; legacy create of a Razorpay payment → 409 | ✅ |
| Restaurant accept → preparing → ready; restaurant has no route to mark delivered/paid | ✅ |
| **Rider receives COD:** after accepting, the delivery detail carries `payment_method` + **`cod_amount`**; rider-mobile shows a "Cash to collect ₹X" box and a confirm dialog | ✅ |
| Before accepting, the available-deliveries list shows **neither payment method nor cash amount** | ⚠️ A46 (P3 UX) |
| Collect before accepting / while only RIDER_ASSIGNED → 403/404/409; rider B can't accept or collect rider A's order; customer can't call `cod-collect` (403) | ✅ |
| **Complete before collecting cash → 409**, stays OUT_FOR_DELIVERY | ✅ |
| **Amount manipulation:** collect with body `amount/collected_amount/total = 1.00` → ignored; recorded **276.90** (order total) | ✅ |
| Exactly one `CodCollection` (276.90, rider A); COD Payment PAID, `collected_by_rider_id` = rider A; repeat collect → idempotent | ✅ |
| Delivery completion → DELIVERED + paid | ✅ |
| **Rider wallet:** COD collected 276.90, earnings 30.00, balance −246.90 (owes the platform) | ✅ |
| **Admin reconciliation:** outstanding 276.90 | ✅ |
| Settle `0` / `-5` / `abc` / `NaN` / `Infinity` → 422 | ✅ |
| **Settle ₹0.001 → 500** | ❌→✅ **A45 fixed** (now 422) |
| Settle 276.91 (> outstanding) → 409; partial 100.00 → outstanding 176.90; remainder → 0; settle again → 409 | ✅ |
| Allocations exactly cover the collection (276.90); each settlement audit-logged; rider/customer can't settle (403) | ✅ |
| **Ledger, clone (all riders):** collected Payments = CodCollection rows; no rider settled more than collected | ✅ |

**Dev DB ledger check (read-only):**
* Payments vs collections consistent ✅; over-settlement 0 ✅; delivered-but-unpaid COD 0 ✅; over-allocated collections 0 ✅.
* **3 COD payments are PAID with no collecting rider** (`ORD-20260910-EBFDDB`, `ORD-20260913-D2C386`, `ORD-20260914-25A40D`). These are legacy rows from 10–14 Sept, before the explicit collect step, with no `paid_at` and no collection row. Two also have `rider_id` NULL (the A35 pattern). No rider owes this cash in reconciliation. Current code can't produce this: COD reaches DELIVERED only through rider `complete`, which requires `cod-collect`, and admins have no deliver action. → **D8**, data repair together with D7.

### Issue found and fixed

**A45 (P2): money inputs accepted values the database can't hold.**
* `POST /admin/cod/{rider}/settle` with `0.001` → **500**: rounded to 0.00 on insert → `ck_cod_settlement_allocations_amount_positive` violation.
* The same gap (no `max_digits`/`decimal_places` against `NUMERIC(10,2)`) existed on **13 money input fields**: COD settle, admin refund amount, commission default/override value, and coupon `discount_value`/`min_order`/`max_discount` (admin and legacy schemas). Sub-paisa values round on insert, and values over ₹99,999,999.99 overflow, both as 500s.
* Fix: all 13 now carry `max_digits=10, decimal_places=2` → 422 (`backend/app/schemas/admin.py`, `backend/app/schemas/coupon.py`). Pydantic normalises trailing zeros, so `100.000` is still accepted.
* Test: `test_settle_rejects_amounts_the_money_columns_cannot_hold` (0.001 / 99.999 / 123456789.00) in `backend/tests/test_admin_cod_reconciliation.py`; fails without the fix.

### Open

| ID | Sev | Finding | Phase |
|---|---|---|---|
| A46 | P3 | The available-deliveries list doesn't show "COD — collect ₹X" before the rider accepts (the detail does after). A rider can't decide whether they have change. Needs `payment_method`/`cod_amount` on `AvailableDeliveryRead` and in the rider app list. | UX |
| D8 | P2 | 3 legacy COD payments PAID with no collecting rider (dev); repair with D7. | 30/31 |
| — | P2 | Cash collected at the door for an order later cancelled stays on the rider's balance (correct), but there's no flow to return it to the customer. | 26 |

Files changed: `backend/app/schemas/admin.py`, `backend/app/schemas/coupon.py`, `backend/tests/test_admin_cod_reconciliation.py`, `docs/final-system-audit.md`.
Regression: **1627 passed, 10 skipped, 0 failed**.

---

## Phase 15 — Order Creation (2026-10-08) — **PASS after fixes**

Phase 12 already covers validation of cart, restaurant, address and totals, plus "never trust client money". This phase adds what only **real parallel requests on PostgreSQL** can show (thread pool against the clone server).

| Check | Result |
|---|---|
| **8 truly parallel submits of the same cart** → exactly **one 201**, seven 422 ("cart is empty"), no 5xx; exactly one order row with its items + status history; cart emptied | ✅ (atomic cart-claim guard holds on Postgres) |
| Re-submit after success → 422, still one order | ✅ |
| Payment link: COD order records `payment_method=cod`; the Payment row is created at collection (Phase 14); online orders link at payment start (Phase 13) | ✅ |
| **Coupon with `usage_limit=1` raced by 6 customers at once** | ❌→✅ **A47 fixed**: was **6 redemptions, 6 discounted orders**; now **1 redemption**, five clean 422s |
| **20 customers ordering at the same instant** → all 201, 20 unique order numbers | ✅ (but see A48) |

### Issues found and fixed

* **A47 (P1): coupon usage limits could be exceeded by concurrent orders.**
  * Limits were enforced check-then-insert (count redemptions → insert one) with no lock or constraint, so any concurrent orders all passed. A "first 100 customers" promotion was over-redeemable without bound.
  * Fix: `create_order` now calls `lock_and_recheck_coupon_usage`, which takes `SELECT … FOR UPDATE` on the coupon row and re-counts global and per-customer usage inside the order transaction, right before recording the redemption (`backend/app/services/coupons.py`, `backend/app/services/orders.py`). Concurrent orders using the same coupon queue on the lock; losers are refused (422) and their cart claim rolls back, so they can retry without the coupon.
* **A48 (P2): order-number collisions at scale.**
  * `ORD-YYYYMMDD-` + `token_hex(3)` = 16.7M numbers a day under a unique index. By the birthday bound, ~5,000 orders a day gives roughly a 50% daily chance of a collision, and the unretried `IntegrityError` would fail that customer's order.
  * Fix: 10 hex digits (≈1.1×10¹² a day); the number is still ≤ `String(32)`, and no client parses the format (checked).
* Tests: `backend/tests/test_coupon_usage_limit_at_order_time.py`. It reproduces the race window deterministically (B validated while the coupon is free → A uses it → B's order must be refused) and checks the order-number format. Both fail without the fixes. The Postgres lock itself was verified live.

Files changed: `backend/app/services/coupons.py`, `backend/app/services/orders.py`, `backend/tests/test_coupon_usage_limit_at_order_time.py` (new), `docs/final-system-audit.md`.
Regression: **1629 passed, 10 skipped, 0 failed**.

---

## Phase 16 — Restaurant Order Flow (2026-10-08) — **PASS after fix**

| Check | Result |
|---|---|
| **Action × status matrix:** each restaurant action (`accept`, `reject`, `preparing`, `ready`) called on an order in **each of the 10 statuses** | ✅ **40/40**: exactly 4 succeed (PLACED→CONFIRMED, PLACED→REJECTED, CONFIRMED→PREPARING, PREPARING→READY_FOR_PICKUP); the other 36 are refused (409) **with status unchanged** |
| Restaurant order actions exposed are exactly `accept/preparing/ready/reject` (+ read-only `route`); `pickup/start/complete/deliver/cod-collect/assign-rider/cancel` don't exist for owners (404/405) | ✅ |
| Owner token on rider `pickup/complete` and admin `assign-rider/cancel` → 403 | ✅ restaurant can't set PICKED_UP / OUT_FOR_DELIVERY / DELIVERED |
| Customer notified on accept, preparing and ready (+3) and on rejection | ✅ |
| Status history: confirmed → preparing → ready_for_pickup | ✅ |
| Reject with reason → REJECTED, **reason persisted** (A35 fix live); reason > 500 chars → 422 | ✅ |
| Unpaid online orders can't be accepted or rejected (Razorpay Phase 12 gate) | ✅ (covered earlier) |
| Restaurant order detail sent the **customer's real email** | ❌→✅ **A49 fixed** |

### Issue found and fixed

**A49 (P2, privacy / data minimisation):**
* The restaurant order list deliberately masks the customer's name, but the restaurant **detail** (and every accept/reject/preparing/ready response) returned `customer_email` unmasked. business-web never displays it; it shows name, phone and delivery address, which a kitchen needs.
* Fix: `RestaurantOrderDetailRead` excludes `customer_email` from serialization, so it's gone from responses **and** the OpenAPI schema (`backend/app/schemas/order.py`). Customer and admin views are unchanged.
* business-web: removed the unused field from `ordersApi.ts` and its test fixture (tsc 0 errors, 26/26 tests).
* Test: `test_integration_order_cross_portal_consistency.py` now asserts `customer_email` is **absent** from the restaurant view (it previously asserted equality).

Files changed: `backend/app/schemas/order.py`, `backend/tests/test_integration_order_cross_portal_consistency.py`, `business-web/src/services/api/ordersApi.ts`, `business-web/src/pages/restaurant/OrderDetails.test.tsx`, `docs/final-system-audit.md`.
Regression: **1629 passed, 10 skipped, 0 failed** (backend); business-web 26/26, tsc 0 errors.

---

## Phase 17 — Rider Assignment (2026-10-08) — **PASS** (no defects)

Live on the clone server with five fresh approved online riders, plus one each of offline, PENDING, SUSPENDED and deactivated riders. **The concurrency test used real parallel requests on PostgreSQL.**

| Check | Result |
|---|---|
| READY order offered to online approved riders; **not** to offline / pending / suspended riders | ✅ |
| Rider declines → 200; order stays READY + unassigned; no longer offered to that rider, still offered to others | ✅ |
| **5 riders accept the same order simultaneously** → **exactly one 200**, four 409, no 5xx; order RIDER_ASSIGNED to the single winner; exactly one ACCEPTED assignment row; order leaves everyone's available list | ✅ (atomic conditional UPDATE holds on Postgres) |
| A losing rider can't view (404) or pick up the winner's delivery | ✅ |
| Admin reassign to a PENDING / SUSPENDED / deactivated rider → 400, order unchanged | ✅ |
| Admin reassign to an **offline** approved rider → allowed | ✅ by design: `_assert_rider_assignable_by_admin` requires approval + an active account ("standing"), not presence, so an admin can hand an order to an off-shift rider they've contacted |
| Admin reassign to another approved rider → 200; previous rider loses access (404) and can't pick up; new rider sees it and picks up; audit-logged | ✅ |
| Reassign after pickup → refused | ✅ |
| Admin direct assign: PENDING rider refused; approved rider → **`rider_id` persisted** (A35 fix live); rider sees it; assignment notification created | ✅ |
| Rider can't accept an order that isn't READY | ✅ |

**Observation (product decision, no change):** there is no "one active delivery per rider" rule; a rider holding an assigned order can accept another (200). Fine for batching nearby orders, but there's no upper bound. → P3.

Files changed: `docs/final-system-audit.md` only (no code changed; the Phase 16 regression of 1629 passed stands).

---

## Phase 18 — Rider Delivery Flow (2026-10-08) — **PASS after fix**

| Check | Result |
|---|---|
| **Rider action matrix:** `arrived`, `pickup`, `start`, `complete` × all 10 order statuses × (assigned rider, another rider). Assignment state was kept consistent with the order; the order was prepaid so cash collection didn't gate completion (COD in Phase 14) | ✅ **80/80**: only the assigned rider's valid moves succeed (RIDER_ASSIGNED→arrived/pickup, PICKED_UP→start, OUT_FOR_DELIVERY→complete), plus idempotent retries of the step just done (200, nothing changed); every other combination refused with status unchanged; **another rider always 404/403** |
| Accept → **navigation data** in the delivery detail: restaurant + customer coordinates | ✅ |
| Rider location update during delivery → 200 | ✅ (location rules in Phase 21) |
| Arrived → assignment `ARRIVED_AT_RESTAURANT` → pickup → start → complete → DELIVERED | ✅ |
| Rider credited **exactly once** (earning = delivery fee 30.00); repeat complete → idempotent 200, no second earning | ✅ |
| Assignment ends DELIVERED; customer tracking shows delivered; history `rider_assigned > picked_up > out_for_delivery > delivered` | ✅ |
| **Atomicity of a rider step** (order transition + assignment move + earning) | ❌→✅ **A50 fixed** |

### Issue found and fixed

**A50 (P1): a rider step could half-complete, and on completion leave the rider unpaid.**
* `pickup_delivery`, `start_delivery` and `complete_delivery` called `transition_order_status` first (it **commits**) and only then moved the delivery assignment; `complete` also recorded the earning there.
* If the assignment move failed (an assignment lagging its order, or a crash between the two commits):
  * the rider got a **409 for an order that had already advanced**, and every later step then failed the same way;
  * on completion the order was **DELIVERED with no earning recorded**, and a retry hit the "already DELIVERED" early return, so **the rider was never paid** for that delivery.
* Reproduced by forcing a lagging assignment: `start`/`complete` returned 409 while the order moved to OUT_FOR_DELIVERY/DELIVERED.
* Fix: the assignment move, and on completion `record_delivery_fee_earning`, are staged **before** the order transition, whose single commit persists all of it. An invalid assignment move now refuses with **nothing** committed; a lost race rolls everything back, flushed in the same transaction (A35) (`backend/app/services/rider_deliveries.py`).
* Tests: `backend/tests/test_rider_step_atomicity.py`. A failed complete leaves the order undelivered, assignment untouched and 0 earnings; a failed start doesn't advance the order; the normal path moves both together and pays once. The two failure tests fail without the fix.

**Dev DB (read-only):** no lagging assignments today. **6 of 13 delivered orders have a rider but no earning**: all from 10–11 Sept, **before rider earnings existed** (first earning row: 15 Sept) and with no assignment rows. That's legacy data, not this bug → added to the D7/D8 repair list as **D9**.

Files changed: `backend/app/services/rider_deliveries.py`, `backend/tests/test_rider_step_atomicity.py` (new), `docs/final-system-audit.md`.
Regression: **1632 passed, 10 skipped, 0 failed**.

---

## Phase 19 — Order State Machine (2026-10-08) — **PASS** (no defects)

There is **no endpoint that sets an order status directly**. Every change goes through an actor action, which calls the single `transition_order_status` choke point (`VALID_TRANSITIONS` plus a conditional UPDATE). So "attempt every invalid transition" means every actor action against every status:

| Actor actions × 10 statuses | Combinations | Result |
|---|---:|---|
| Restaurant `accept/reject/preparing/ready` (Phase 16) | 40 | ✅ only PLACED→CONFIRMED/REJECTED, CONFIRMED→PREPARING, PREPARING→READY succeed |
| Rider `arrived/pickup/start/complete`, own + other rider (Phase 18) | 80 | ✅ only the assigned rider's forward steps (+ idempotent retries) |
| **Customer cancel** | 10 | ✅ only from PLACED, CONFIRMED |
| **Admin cancel** | 10 | ✅ only from PLACED, CONFIRMED, PREPARING, READY_FOR_PICKUP, RIDER_ASSIGNED |
| **Admin assign** | 10 | ✅ only from CONFIRMED, PREPARING, READY_FOR_PICKUP (and the rider is persisted, A35) |
| **Admin reassign** | 10 | ✅ only from RIDER_ASSIGNED |
| Service-level `transition_order_status` 10×10 matrix + assignment state machine (existing suites) | 100 | ✅ 100 passed (10 self-transitions skipped) |

Every refusal was a 409 (or 400/422) **with the status unchanged in the DB**.

* The master command's examples, tried through every actor that exists, are all refused: DELIVERED → PREPARING / CANCELLED (restaurant, admin, customer), CANCELLED → CONFIRMED, REJECTED → OUT_FOR_DELIVERY, PREPARING → DELIVERED.
* Cancellation side effects: admin-cancelling an assigned order closes the rider's assignment (CANCELLED); the reason is persisted.

### Design gaps (product decisions, no change)

| ID | Sev | Finding |
|---|---|---|
| A22 | P2 | (re-confirmed) No exit from PICKED_UP / OUT_FOR_DELIVERY other than DELIVERED. Even an admin can't cancel or return an undeliverable order (customer unreachable, accident). |
| **A51** | P2 | After an **early admin assignment** (from CONFIRMED/PREPARING, allowed by design), the restaurant's `ready` is refused (RIDER_ASSIGNED doesn't accept READY_FOR_PICKUP), so the kitchen can never signal "food ready" for that order and the rider may arrive early. Options: an assignment-independent `food_ready_at` flag, or only allowing admin assignment from READY_FOR_PICKUP. |

Files changed: `docs/final-system-audit.md` only (no code changed; the Phase 18 regression of 1632 passed stands).

---

## Phase 20 — Maps & Location (2026-10-08) — **PASS** (no new defects; 2 decisions open)

Run twice against the clone: once with the **real** Photon/OSRM providers, once with both **unreachable** (pointed at a dead local port). Customer addresses and geocoding are covered in Phase 9, and service-area ordering in Phase 12.

| Check | Real providers | Providers down |
|---|---|---|
| Restaurant location: lat 91, lon 181, `NaN`, 8 decimal places → 422; a valid pin is persisted exactly | ✅ | ✅ |
| Checkout `distance_km` vs an independent haversine (4.47 km) | ✅ exact | ✅ (computed locally, no provider needed) |
| Address without a pin → `distance_km` null, checkout still valid | ✅ | ✅ |
| **Order creation** | ✅ 201 | ✅ **201: unaffected by map outages** |
| Restaurant route (`/restaurant/orders/{id}/route`) | ✅ OSRM road route 6.48 km / 9.3 min (≥ straight line) | ✅ honest **503** "Route calculation is temporarily unavailable", no fabricated distance. No client uses this endpoint (A19-class dead surface) |
| Customer tracking + ETA | ✅ 200, `eta_source` | ✅ 200, falls back to `static` ETA |
| Order with no customer pin: route + tracking don't 5xx | ✅ | ✅ |
| Rider location: lat 91, lon −181, missing lon, string → 422 | ✅ | ✅ |
| Server errors logged during the provider-down run | — | ✅ **0** |
| Address 1,209 km away: checkout computes `distance_km = 1209.42` yet reports **no issue** | ❌ A44 | ❌ A44 |

Phase 2 already fixed the outage that actually affected Render (Photon 403s httpx's default User-Agent).

### Open — decisions

| ID | Sev | Finding |
|---|---|---|
| **A44** | P1 | No maximum delivery distance; the distance is already computed at checkout but never enforced. Needs a radius (`MAX_DELIVERY_DISTANCE_KM`, global or per restaurant). |
| A17 | P2 | Service-area eligibility trusts the typed postal code; it isn't cross-checked against the pin. Could be derived via reverse geocoding (rate-limited public Photon) or replaced by radius checks once A44 exists. |
| A13 | P1 | Production depends on the public OSRM demo server (non-commercial use policy) and public Photon (~1 req/s), both throttled in-process. Self-host or use a paid provider before launch. |

Files changed: `docs/final-system-audit.md` only (no code changed; the Phase 18 regression of 1632 passed stands).

---

## Phase 21 — Live Rider Tracking (2026-10-08) — **PASS after fixes** (A2 and A16 confirmed and fixed)

### Results — 19/19 functional checks + 2 resource/security fixes

| Check | Result |
|---|---|
| Subscribe → immediate full snapshot (status, restaurant/delivery pins, rider, history, ETA) | ✅ |
| **Rider GPS update → customer's socket receives the new position live**, with a live ETA (`eta_source=live`) and state LIVE | ✅ |
| **GPS failure / spoofing:** ~500 km jump within seconds at poor accuracy → 422; fix stamped 3 h in the past → 422; 10 min in the future → 422 | ✅ |
| Last fix older than 30 s → **STALE**; older than 120 s → **OFFLINE** | ✅ |
| **Reconnection** → fresh snapshot with the last known position | ✅ |
| Status changes pushed live (picked_up, out_for_delivery, delivered); on delivery the **rider location is withdrawn** (`rider_location: null`), so tracking stops | ✅ |
| **Security:** customer A's REST tracking of order B → 404; A can't subscribe to B's socket; rider B's updates never reach A's socket; A's payloads never contain rider B's id or position | ✅ |
| WebSocket failure: customer-mobile falls back to REST polling with backoff (code review, Phase 2) | ✅ |
| **A2: tracking sockets exhausting the DB pool** | ❌→✅ fixed |
| **A16: access tokens in the server log** | ❌→✅ fixed |

### Issues confirmed and fixed

**A2 (P1, launch-blocking): every tracking WebSocket pinned a DB connection.**
* Reproduced live: 15 open tracking sockets → **15 PostgreSQL sessions "idle in transaction"** (the whole pool: 5 + 10 overflow). The 16th socket **and an ordinary `GET /customer/profile`** then waited **30 s and failed with a 500** ("QueuePool limit … reached"). Fifteen customers watching a delivery would take the whole API down.
* Also: the async handler ran its DB queries and the initial snapshot, which may call OSRM for a live ETA (the routing throttle can sleep up to 3 s), **directly on the event loop**, freezing every other request meanwhile.
* Fix (`backend/app/api/v1/customer/tracking.py`): authorisation lookups and the snapshot run in Starlette's threadpool. `_initial_payload_then_release_db` **closes the session right after the first snapshot** (also on failure). Later updates are pushed by `manager.broadcast` with payloads built by whoever changed the order, so the socket never needs the DB again.
* Verified live: **40 sockets open → 0 idle-in-transaction sessions; REST answered instantly.**

**A16 (P2): live access JWTs written to the server log.**
* The socket authenticates with `?token=` (React Native's WebSocket can't send headers), and uvicorn logs every handshake URL.
* Fix (`backend/app/core/logging.py`): a `RedactTokenQueryParamFilter` on `uvicorn.access` and `uvicorn.error` rewrites `token=` / `access_token=` query values to `[REDACTED]`. No client change is needed.
* Verified live: 0 JWTs in the log; the handshake line reads `?token=[REDACTED]`.
* **Residual:** Render's own edge/proxy logs may still record full URLs. Moving the token to the first WebSocket message would remove it from URLs entirely (needs a customer-mobile change).

Tests: `backend/tests/test_tracking_socket_resources_and_log_redaction.py` (session released after the snapshot, and on snapshot failure; handshake log line redacted; filter installed). They fail without the fixes. All existing WebSocket/tracking tests still pass (36).

Files changed: `backend/app/api/v1/customer/tracking.py`, `backend/app/core/logging.py`, `backend/tests/test_tracking_socket_resources_and_log_redaction.py` (new), `docs/final-system-audit.md`.
Regression: **1636 passed, 10 skipped, 0 failed**.

---

## Phase 22 — Notifications (2026-10-08) — **PASS after fix** (device push still unconfigured: E2)

A full COD lifecycle ran on the clone server with a registered (fake but well-formed) Expo token. **Push requests really went to Expo's API**, which rejected the unknown device.

| Check | Result |
|---|---|
| **Restaurant** notified of a new order (`restaurant_new_order`) | ✅ |
| **Riders** notified when the order is ready (`new_delivery`) | ✅ |
| **Customer** notified across the lifecycle: placed, confirmed, preparing, ready, rider_assigned, picked_up, out_for_delivery, cod_collected, delivered (9) | ✅ |
| **Admins** alerted on a rejected order (order issue); customer told about the rejection | ✅ |
| **Duplicate event** (repeated pickup, an idempotent retry) → no duplicate notification | ✅ |
| **Deep link:** every customer notification carries `{"type":"order_status","order_id":…,"status":…}` | ✅ |
| No secrets or tokens in notification titles/bodies | ✅ |
| **Provider failure:** push to an unregistered device → token **soft-deactivated**, not retried forever; **the order completed normally**, so notification failure never blocks orders | ✅ |
| **Preferences:** `order_updates=false` → no order-update pushes; unknown preference key → 422 | ✅ |
| Inbox per role: list, unread count, mark read, read-all → 0; rider can't mark the customer's notification read | ✅ |
| Re-registering the same token → no duplicate row; unregister (logout) via `?token=` → 2xx | ✅ |
| **Push-token validation** | ❌→✅ **A52 fixed** |
| **Mobile (code check, both apps):** permission request; **permission denied → no registration**; foreground handler (`setNotificationHandler`); Android channel; **tap → deep link**; provider unit tests | ✅ |

### Issue found and fixed

**A52 (P2): push tokens weren't validated.**
* `"abc"`, `""` and `"ExponentPushToken[]"` were stored as active tokens (each wasting a push attempt per event), and a 600-character value overflowed the 512-char column → **500**.
* Fix (`backend/app/schemas/push_token.py`): `token` must be an Expo push token (`Expo(nent)PushToken[…]`), the only kind this backend can deliver to; `platform` ∈ expo/ios/android/web (≤ the 32-char column); `device_identifier` ≤ 255.
* Tests: `backend/tests/test_push_token_validation.py` (5 rejections fail without the fix; real Expo tokens accepted). The 44 existing push-token tests pass.

### Open

| ID | Sev | Finding |
|---|---|---|
| **E2** | P1 | (Phase 2) Push isn't configured in either app (no EAS `projectId`, no FCM), so no real device can receive pushes. Foreground/background delivery on a device can only be tested once that's done. |
| A53 | P3 | `notifications.status` stays `pending` even after a push was attempted or failed. The model documents per-channel status as "not tracked yet", so delivery outcomes aren't visible to admins. |

Files changed: `backend/app/schemas/push_token.py`, `backend/tests/test_push_token_validation.py` (new), `docs/final-system-audit.md`.
Regression: **1643 passed, 10 skipped, 0 failed**.

---

## Phase 23 — Reviews & Ratings (2026-10-08) — **PASS for integrity / FAIL for completeness** (A1 fixed; moderation and aggregation not built)

Live on the clone server. The order-based flow is `POST /customer/orders/{id}/review` with `restaurant_rating` + `delivery_rating` + comment; restaurant and rider are derived from the order.

### Results — 30 checks: 25 pass, 5 = features not implemented

| Check | Result |
|---|---|
| Review own **DELIVERED** order → 201; linked to the order's own restaurant + rider, set server-side; published | ✅ |
| Duplicate review of the same order → 409; GET own review → 200 | ✅ |
| Rating 0 / 6 / 4.5 → 422; comment > 1000 chars → 422 | ✅ |
| Smuggled `restaurant_id` / `rider_id` / `customer_id` / `product_id` → 422 (`extra="forbid"`), so you **can't review an unrelated restaurant, rider or unbought item** | ✅ |
| Review an order that's PLACED / PREPARING / OUT_FOR_DELIVERY / **CANCELLED** / **REJECTED** → refused | ✅ |
| Customer A reviews customer B's delivered order → 404 | ✅ |
| Edit own review → 200 and persisted; B can't edit A's (404); edit with smuggled `order_id` → 422 | ✅ |
| **Legacy `POST /reviews` fake-review hole (A1)** | ❌→✅ **fixed** (now 410) |
| Published review visible publicly for the restaurant; no customer email/phone in public output | ✅ |
| **Rating aggregation:** `restaurants.average_rating/total_ratings`, `delivery_partners.average_rating/total_ratings` | ❌ **A7: not implemented**; columns exist (migration 57) but stay 0.00 / 0 after a 5★ review, while restaurant listing sorts by `average_rating` |
| **Admin moderation** (hide/remove) | ❌ **A54: no endpoint** (the `status` column exists, design in `docs/reviews-ratings-architecture.md` §5) |
| **Customer delete own review** | ❌ A54: no endpoint (design §9) |
| **Report a review** | ❌ A54: no endpoint (design §10) |

### Issue fixed

**A1 (P1): fake-review injection.**
* Legacy `POST /api/v1/reviews` accepted a client-chosen target and inserted a **published** review with no order, delivery or uniqueness check (Phase 1: 5/5 fake reviews accepted for a non-existent restaurant).
* No client uses it, and the dev DB has 0 legacy reviews.
* Fix (`backend/app/api/v1/endpoints/reviews.py`): the route stays registered and role-gated (non-customers still 403), but now always answers **410 Gone**, pointing to the order-based endpoint. The frozen legacy *read* endpoints are unchanged, per the architecture doc's "frozen" decision.
* Test: `test_the_legacy_create_endpoint_can_no_longer_create_a_review` (`backend/tests/test_review_average_endpoint.py`); fails without the fix.

### Not fixed — feature work, not defects (the separate Reviews & Ratings build protocol)

| ID | Sev | Gap |
|---|---|---|
| **A54** | **P1** | **No admin moderation** of public user-generated content: an abusive or defamatory review can't be hidden or removed through the product. Launch blocker for public reviews. Customer delete and report-review are also missing (P2). |
| **A7** | P2 | Ratings never aggregated; every restaurant and rider shows 0.00, and "sort by rating" is meaningless. |

Files changed: `backend/app/api/v1/endpoints/reviews.py`, `backend/tests/test_review_average_endpoint.py`, `docs/final-system-audit.md`.
Regression: **1644 passed, 10 skipped, 0 failed**.

---

## Phase 24 — Customer E2E Happy Path, Razorpay (2026-10-08) — **PASS** (36/36, no defects)

One continuous run through the real APIs on the clone server, with **real Razorpay Test Mode keys and real Photon/OSRM**. The customer registered via the public API. The payment is the genuinely captured device payment from Razorpay Phase 9 (₹20, `pay_TlN9BZ1tXWlnMu`), bound to this order's payment row in the clone only, and verified against Razorpay by the backend's own `/verify`. DB state was snapshotted after each major step:

| Step | API result | DB state after |
|---|---|---|
| 1 Register → login | 201 → token pair | — |
| 2 Restaurant list / detail / menu | listed; Masala Chai ₹20.00 | — |
| 3 Cart | subtotal 20.00 | — |
| 4 Address (pinned) | saved as default | — |
| 5 Checkout | total 20.00, no issues, distance 4.47 km | — |
| 6 Place order (razorpay) | 201; **hidden from the restaurant while unpaid** | placed · unpaid · 2 notifications |
| 7 Razorpay order → **verify real captured payment** | 200 PAID; `payment_success` notification | placed · **paid** · payment PAID with Razorpay id |
| 8 Restaurant accept → preparing → ready | each 200; owner sees earning 20.00 / commission 2.50 / net 17.50 | confirmed → preparing → ready_for_pickup |
| 9–10 Rider accepts | 200 | rider_assigned · assignment ACCEPTED |
| 11 Pickup → start | 200, 200 | picked_up / out_for_delivery · assignment in step |
| 12 **Live tracking** (customer socket) | snapshot; RIDER_ASSIGNED, PICKED_UP, OUT_FOR_DELIVERY pushed live; rider marker `live` + live ETA; approaching position | — |
| 13 Notifications | placed, payment_success, confirmed, preparing, ready, rider_assigned, picked_up, out_for_delivery, **rider_approaching**, delivered | — |
| 14 Delivered | 200; DELIVERED pushed live; rider location withdrawn | delivered · paid · assignment DELIVERED · **1 earning** |
| 15 Review | 201; linked to restaurant + rider | review row |
| Admin | order visible with payment + rider; history `placed > … > delivered` complete and ordered | — |

### Business-rule observations (product decisions, no change)

| ID | Sev | Finding |
|---|---|---|
| **A55** | P2 | **Rider pay = the order's customer-facing `delivery_fee`** (`record_delivery_fee_earning`), so a free-delivery promotion or a ₹0-fee restaurant pays the rider **₹0** (observed: earning 0.00). No dev restaurant has a ₹0 fee today. Rider pay should be decoupled from what the customer is charged. |
| **A56** | P2 | **"New delivery" alerts go to every online approved rider platform-wide**, with no distance filter (notifications jumped 6 → 49 at "ready" in the clone), and the available list is platform-wide. That's noise for riders and scales with the rider count × orders. Filter by distance to the restaurant. |

Files changed: `docs/final-system-audit.md` only (no code changed; the Phase 23 regression of 1644 passed stands).

---

## Phase 25 — Customer COD E2E (2026-10-08) — **PASS** (27/27, no defects)

One continuous cash-on-delivery run through the real APIs on the clone server: 2 × Veg Biryani ₹149.50 + ₹25.00 delivery = **₹324.00**. DB snapshots were taken throughout.

| Step | Result | DB state after |
|---|---|---|
| Register + login (public API); browse restaurant + menu | ✅ | — |
| Checkout total **324.00** (2 × 149.50 + 25.00) | ✅ | — |
| COD order placed: unpaid, **no payment row yet**, visible to the restaurant immediately | ✅ | placed · unpaid |
| Restaurant accept → preparing → ready | ✅ | ready_for_pickup · unpaid |
| Rider accepts; delivery detail shows **`payment_method=cod`, cash to collect 324.00** | ✅ | — |
| Pickup → start; customer **tracks the rider live** (marker `live`) | ✅ | — |
| Complete **before collecting cash → 409** | ✅ | — |
| **Rider collects cash** (body `amount: 10.00` ignored) → recorded **324.00** | ✅ | out_for_delivery · **paid** · payment cod/paid · 1 collection 324.00 |
| Delivered, pushed live to the customer | ✅ | delivered · paid · collection 324.00 |
| Rider earned the delivery fee **once** (25.00) | ✅ | 1 earning row |
| **Rider wallet:** collected 324.00, earned 25.00, **owes 299.00** | ✅ | — |
| **Admin reconciliation:** 324.00 outstanding → settle 324.00 → outstanding **0, SETTLED**; allocation covers the order's collection exactly; audit-logged | ✅ | settlement + allocation rows |
| Rider wallet after settlement: settled 324.00, **balance +25.00** (platform owes the rider their fee) | ✅ | — |
| **COD and Razorpay separate:** the COD payment has no Razorpay order/payment ids | ✅ | — |
| Financials: total = subtotal + fee + tax − discount (299.00 + 25.00 = 324.00); commission recorded (37.38) | ✅ | — |
| Customer review | ✅ | review row |

**Observation:** the rider's +₹25.00 balance after settlement is the platform owing the rider. The model has a PAYOUT settlement type, but paying riders out wasn't exercised here → Phase 31 (financial reconciliation).

Files changed: `docs/final-system-audit.md` only (no code changed; the Phase 23 regression of 1644 passed stands).
