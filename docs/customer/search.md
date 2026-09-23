# Customer Search — Phase 6

> **Post-split note:** the app was later restructured (see `docs/architecture/role-architecture.md`) into separate `customer-mobile`/`rider-mobile`/`business-web`/`admin-web` apps. Any path below referencing the old root `src/app/...`, `src/services/...`, `src/features/...` etc. now lives at the equivalent `customer-mobile/...` path.

## Backend

`GET /api/v1/customer/search` — public endpoint (no auth). Query params: `q`, `category_id`, `restaurant_id`, `page` (default 1), `limit` (default 20, max 100).

Returns `{ restaurants, products, categories, page, limit }`, each list independently paginated with the same `page`/`limit`.

- **Restaurants**: reuses the Phase 4 `list_active_restaurants` search (name/description/address, case-insensitive), filtered by `category_id` when given (the cuisine `Category` from Phase 4).
- **Products**: new `search_products` in `services/products.py` — joins to `Restaurant` so only products from an active restaurant are returned, and only `is_active`/`is_available` items, matching Phase 5's visibility rule. Filterable by `restaurant_id` and/or `category_id` (here `category_id` means the product's `MenuCategory`, since that's what a product actually belongs to).
- **Categories**: new `search_categories` in `services/categories.py` — name match against the active cuisine categories.

`category_id` is intentionally applied to both the restaurant query (as cuisine category) and the product query (as menu category) — they're different tables, so passing an ID that only matches one just returns an empty list for the other, which is harmless.

### Indexes

Added a btree index on `products.name` (`backend/alembic/versions/20260909_03_add_product_name_index.py`) so product search doesn't full-scan. `restaurants.name` and `categories.name` were already indexed from earlier phases. Note: like the existing restaurant search, this uses a leading-wildcard `LIKE '%term%'`, which a plain btree index can't fully optimize — a `pg_trgm` or full-text index would be needed for that, but nothing in this codebase uses those yet, so a plain index was used to stay consistent with the existing convention rather than introducing new Postgres extensions.

## Frontend

- `src/services/api/searchApi.ts` — new client for the endpoint.
- `src/app/search.tsx` — new dedicated search screen: debounced (350ms) search-as-you-type, category filter chips (from the same categories used on Home), restaurant and product result sections, recent searches (session-only, in-memory — not persisted to disk), loading/error/empty states.
- `src/app/home.tsx` — the home screen's search bar is now a button that navigates to `/search` instead of doing a local client-side name filter, so there's one real search experience instead of two different ones (a shallow local filter vs. the full backend search). The "Popular near you" list on Home now just shows all fetched restaurants unfiltered.

## Known Limitations

- Recent searches are kept in React state only — they reset on app restart. Persisting them (e.g. via `expo-secure-store`, already used for auth tokens) would be a small follow-up if wanted.
- Search results aren't ranked by relevance — plain substring match ordered by name.

## How to test

```bash
cd backend
. .venv/bin/activate
pytest tests/test_customer_search.py -q
```

Frontend: `npx tsc --noEmit`
