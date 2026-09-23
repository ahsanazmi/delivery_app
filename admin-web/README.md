# Admin Web App

The platform admin panel (plain React + Vite). Separate from `business-web` — the ADMIN role has its own app, distinct from the RESTAURANT_OWNER-facing business portal. Talks directly to the shared FastAPI backend — no separate backend or database.

## Structure

- `src/pages/` — `Login`, `Dashboard` (stats, recent orders, assign rider, mark delivered)
- `src/features/auth/` — session/auth state (web adaptation: `localStorage` instead of `expo-secure-store`)
- `src/services/api/` — `apiClient.ts` (fetch wrapper reading `VITE_API_BASE_URL`), `authApi.ts`, `adminApi.ts`

## Run

```bash
npm install
cp .env.example .env   # adjust VITE_API_BASE_URL if the backend isn't on localhost:8000
npm run dev
```

Runs on http://localhost:5174 by default. The backend must have this origin allowed in `CORS_ORIGINS`.
