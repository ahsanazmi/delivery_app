# Customer Profile — Phase 2

> **Post-split note:** the app was later restructured (see `docs/architecture/role-architecture.md`) into separate `customer-mobile`/`rider-mobile`/`business-web`/`admin-web` apps. Any path below referencing the old root `src/app/...`, `src/services/...`, `src/features/...` etc. now lives at the equivalent `customer-mobile/...` path.

This document describes the customer profile endpoints and the frontend behavior implemented in Phase 2.

## Backend endpoints

- GET `/api/v1/customer/profile` — returns the current authenticated user's profile (requires `Authorization: Bearer <access_token>`).
- PATCH `/api/v1/customer/profile` — update the current user's profile. Accepts JSON with any of:
  - `name` (string, 2-120 chars)
  - `email` (valid email)
  - `profile_image` (string URL, max length 2048)

Authorization: only users with role `CUSTOMER` may update their own profile. The server enforces role checks and returns 403 for unauthorized roles.

No database schema changes were made — the existing `users` table is used.

## Frontend

- File: `src/app/profile.tsx` — profile screen with view and edit modes.
- File: `src/services/api/profileApi.ts` — client helpers `getProfile` and `updateProfile`.
- File: `src/features/auth/session-context.tsx` — session provider persists tokens in secure storage and exposes `refresh()` to reload the current user after profile updates.

Usage:

1. Sign in via the auth flow.
2. Open the Profile screen — view account information.
3. Tap Edit profile to change name/email, then Save — the UI validates input and calls `PATCH /api/v1/customer/profile`.
4. After successful update, the session is refreshed and new profile data is shown.

## How to run tests

- Backend tests (auth + profile):

```bash
cd backend
. .venv/bin/activate
pytest tests/test_auth.py tests/test_customer_profile.py -q
```

All tests passed during Phase 2 development.
