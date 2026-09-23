# Customer Restaurant Menu — Phase 5

> **Post-split note:** the app was later restructured (see `docs/architecture/role-architecture.md`) into separate `customer-mobile`/`rider-mobile`/`business-web`/`admin-web` apps. Any path below referencing the old root `src/app/...`, `src/services/...`, `src/features/...` etc. now lives at the equivalent `customer-mobile/...` path.

This document describes the menu/product endpoints and frontend behavior implemented in Phase 5.

## Backend endpoints

- GET `/api/v1/customer/restaurants/{restaurant_id}/categories` — the restaurant's menu sections (e.g. "Starters", "Mains"), ordered by `display_order`. 404s if the restaurant doesn't exist or is inactive.
- GET `/api/v1/customer/restaurants/{restaurant_id}/products` — products for a restaurant, optionally filtered by `category_id`. Only returns products that are `is_active = true` AND `is_available = true`, per the phase requirement that the backend "must only expose products that are customer-visible and available." A temporarily sold-out or removed item simply disappears from this list.
- GET `/api/v1/customer/products/{id}` — single product detail, same availability filter (404 if unavailable/inactive so a stale deep link can't be added to a cart).

All are public (no auth), matching the Phase 4 discovery endpoints' convention.

## Database changes

- New `menu_categories` table: `id`, `restaurant_id` (FK, cascade delete), `name`, `display_order`, `is_active`, timestamps. This is deliberately a separate model from Phase 4's `Category` (cuisine tag used for home-page browsing) — a menu section like "Desserts" is scoped to one restaurant, not a site-wide cuisine filter.
- New `products` table: `id`, `restaurant_id` (FK, cascade delete), `category_id` (nullable FK to `menu_categories`, `SET NULL` on delete), `name`, `description`, `image_url`, `price` (`Numeric(10,2)`, `CHECK price >= 0`), `is_available`, `is_active`, timestamps.
- Indexes: `restaurant_id` and `category_id` on both tables, plus a composite `(restaurant_id, is_available)` index on `products` for the common "list a restaurant's available items" query.
- Migration: `backend/alembic/versions/20260909_02_add_menu_categories_and_products.py`. Verified upgrade AND downgrade against the local Postgres instance, then re-applied to head.

## Frontend

- `src/services/api/productsApi.ts` — new client for the three endpoints above.
- `src/types/product.ts` — added backend-shaped `MenuCategory`/`Product` types alongside the existing UI-facing `ProductCardData`.
- `src/app/restaurants/[id].tsx` — replaced the hardcoded `sampleMenu` array with real data: fetches the restaurant, its menu categories, and its products in parallel, groups products into sections by category (any product without a matching category falls into a generic "Menu" section), and renders each with the existing `ProductCard` component (image, price, availability, add/increase/decrease quantity via the existing local `cart-context`). Also added a delivery-time stat and fixed the open/closed status to reflect `restaurant.is_open` (previously showed a static "OPEN NOW" always).

Cart behavior itself (`features/cart/cart-context.tsx`) is unchanged — it's still local, client-only state. Phase 7 is where it becomes server-backed with authoritative price/availability validation.

## Known Limitations

- No veg/non-veg data exists on `Product` yet (not in the phase's field list), so `ProductCard`'s veg indicator is hardcoded to "veg" for every item — cosmetic only, not a business rule.
- No admin/restaurant-owner endpoint to create menu categories or products yet — they must be inserted directly in the DB for now.
- The cart is still fully client-side (Phase 7 will make it server-authoritative for pricing/availability).

## How to test

```bash
cd backend
. .venv/bin/activate
pytest tests/test_customer_menu.py -q
```

Frontend type check:

```bash
npx tsc --noEmit
```
