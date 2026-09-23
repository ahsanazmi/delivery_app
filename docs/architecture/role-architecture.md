# Role-based architecture

## Role mapping

- CUSTOMER -> customer-mobile (Expo/React Native, Android)
- RIDER -> rider-mobile (Expo/React Native, Android)
- RESTAURANT_OWNER -> business-web (React + Vite)
- ADMIN -> admin-web (React + Vite)

Each role maps to its own independent app with its own `package.json`/build config. There is no shared frontend package — the small set of cross-cutting concerns (auth session handling, the base API fetch wrapper) are intentionally duplicated per app rather than extracted into a shared package, to avoid premature workspace tooling.

## Shared backend

- One FastAPI backend (`backend/`) remains the source of truth.
- One PostgreSQL database is shared by all clients.
- One `User` model and `UserRole` enum are shared across the system.
- The backend has CORS enabled (`CORS_ORIGINS` setting) for the two browser-based apps (`business-web`, `admin-web`). The two native apps aren't subject to browser CORS.

## Scope

This repository intentionally contains a shared backend and role-specific frontends without creating separate backend apps or databases.

## Status

All four apps are implemented as independent projects. See each app's own README for how to run it.
