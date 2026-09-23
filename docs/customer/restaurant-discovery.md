# Customer Restaurant Discovery — Phase 4

> **Post-split note:** the app was later restructured (see `docs/architecture/role-architecture.md`) into separate `customer-mobile`/`rider-mobile`/`business-web`/`admin-web` apps. Any path below referencing the old root `src/app/...`, `src/services/...`, `src/features/...` etc. now lives at the equivalent `customer-mobile/...` path.

This document describes the customer discovery endpoints and frontend behavior implemented in Phase 4.

## Backend endpoints

- GET `/api/v1/customer/restaurants` — list customer-visible restaurants. Query params: `category_id`, `q` (search name/description/address), `open_only` (default `false`, shows closed restaurants too so the client can display their status), `offset`, `limit`.
- GET `/api/v1/customer/restaurants/{id}` — restaurant detail.
- GET `/api/v1/customer/categories` — list active categories, ordered by `display_order`.
- GET `/api/v1/customer/categories/{id}` — category detail.

Both endpoints are public (no authentication required), matching the existing shared `/api/v1/restaurants` endpoint's convention.

Only restaurants with `is_active = true` are returned; inactive restaurants are hidden entirely. Closed restaurants (`is_open = false`) remain visible with their status flagged, since the phase requires the UI to display open/closed state.

## Database changes

- New `categories` table: `id`, `name` (unique), `image_url`, `display_order`, `is_active`, timestamps.
- `restaurants` table gained two columns: `category_id` (nullable FK to `categories.id`, `ON DELETE SET NULL`) and `delivery_time_minutes` (integer, default `30`).
- Migration: `backend/alembic/versions/20260909_01_add_categories_and_restaurant_discovery_fields.py`. Verified upgrade/downgrade against the local Postgres instance.

Restaurant "opening hours" and "service area" filtering described in the phase text were **not** implemented — no such data exists anywhere in the schema yet, and adding it would require designing a new time-range/geofence model that wasn't specified. Only the existing `is_active`/`is_open` flags are enforced. See Known Limitations.

## Response shape

`CustomerRestaurantRead` intentionally excludes internal fields (`owner_id`, `is_active`) that the shared `RestaurantRead` schema exposes to restaurant owners/admins, and exposes `average_rating` as `rating` to match the phase spec. `address` was kept in the response (beyond the phase's minimum field list) because the existing customer UI already depends on it.

## Frontend

The customer mobile app's active home/discovery screens live at the repository root (`src/app/`), not under `customer-mobile/` — the same layout Phase 2 (profile) used, since `customer-mobile/` remains an intentionally empty scaffold per `docs/architecture/role-architecture.md`. Route names also follow the existing app's conventions (`home.tsx`, `restaurants/index.tsx`, `restaurants/[id].tsx`) rather than the phase text's literal `index.tsx`/`restaurants.tsx`/`restaurant/[id].tsx`, to avoid duplicating routes already wired into navigation and redirects.

- `src/services/api/restaurantsApi.ts` — now calls `/api/v1/customer/restaurants*` instead of the old shared `/api/v1/restaurants*`, and supports a `categoryId` filter.
- `src/services/api/categoriesApi.ts` — new client for `/api/v1/customer/categories*`.
- `src/types/restaurant.ts` — `Restaurant` type updated to match `CustomerRestaurantRead`; added `Category` type.
- `src/app/home.tsx` — categories section now renders real backend categories (with a small emoji lookup for known cuisine names) instead of a hardcoded list, and tapping one navigates to the new category screen. Restaurant cards now show the real open/closed status and delivery time instead of an always-"Open" badge.
- `src/app/category/[id].tsx` — new screen: shows a category's restaurants, reusing the existing `RestaurantList` component. Registered in `src/app/_layout.tsx`.
- `src/app/restaurants/[id].tsx`, `src/features/restaurants/restaurant-list.tsx`, `src/components/RestaurantCard.tsx` — updated `average_rating` references to the renamed `rating` field.

The restaurant-owner dashboard (`src/app/restaurant/index.tsx`) was left untouched — it uses its own `restaurantApi.ts`/`RestaurantSummary` type against the original shared `/api/v1/restaurants` endpoint, which still exposes `owner_id`/`is_active` for that role.

## How to run tests

```bash
cd backend
. .venv/bin/activate
pytest tests/test_customer_discovery.py -q
```

Frontend type check:

```bash
npx tsc --noEmit
```

## Known Limitations

- No opening-hours or service-area/geofence enforcement — not modeled in the database yet.
- No product/menu data yet (Phase 5) — restaurant detail screen still renders a static sample menu.
- Categories have no seed data or admin-management endpoint yet; they must be inserted directly for now.
