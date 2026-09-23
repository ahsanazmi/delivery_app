# Rider Mobile App

The rider-facing Android app (Expo Router + React Native). Talks directly to the shared FastAPI backend — no separate backend or database.

## Structure

- `app/` — screens: `login`, `index` (available orders), `[id]` (delivery detail)
- `features/auth/` — session/auth state (shared pattern with `customer-mobile`, duplicated rather than shared via a package)
- `services/api/` — `apiClient.ts` (fetch wrapper), `authApi.ts`, `riderApi.ts`

## Run

```bash
npm install
cp .env.example .env.development   # set EXPO_PUBLIC_API_BASE_URL if auto-detect doesn't work
npm run android
```
