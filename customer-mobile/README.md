# Customer Mobile App

The customer-facing Android app (Expo Router + React Native). Talks directly to the shared FastAPI backend — no separate backend or database.

## Structure

- `app/` — screens: `index`, `splash`, `login`, `home`, `search`, `cart`, `checkout`, `orders`, `orders/[id]`, `profile`, `restaurants/index`, `restaurants/[id]`, `category/[id]`
- `features/auth/` — session/auth state, login/register UI
- `features/cart/` — client-side cart state (server is the source of truth for pricing/availability)
- `features/restaurants/` — restaurant list/card components
- `services/api/` — one file per backend resource (`apiClient.ts` is the shared fetch wrapper)

## Run

```bash
npm install
cp .env.example .env.development   # set EXPO_PUBLIC_API_BASE_URL if auto-detect doesn't work
npm run android
```
