# Business Web App

The restaurant-owner-facing web portal (plain React + Vite, not Expo/React Native). Talks directly to the shared FastAPI backend — no separate backend or database.

Architecture note: the ADMIN role now has its own separate app (`../admin-web`), not this one.

## Structure

- `src/pages/` — `Login`, `Dashboard`
- `src/features/auth/` — session/auth state (web adaptation: uses `localStorage` instead of `expo-secure-store`)
- `src/services/api/` — `apiClient.ts` (fetch wrapper reading `VITE_API_BASE_URL`), `authApi.ts`, `restaurantApi.ts`

## Run

```bash
npm install
cp .env.example .env   # adjust VITE_API_BASE_URL if the backend isn't on localhost:8000
npm run dev
```

Runs on http://localhost:5173 by default. The backend must have this origin allowed in `CORS_ORIGINS`.
