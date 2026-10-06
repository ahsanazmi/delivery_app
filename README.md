# Say Hi Chai

A local delivery platform: one shared FastAPI backend + one PostgreSQL database, serving four independent apps.

```text
                         ┌─────────────────────────┐
                         │    SHARED FASTAPI        │
                         │       BACKEND            │
                         │                          │
                         │ Customer / Rider /        │
                         │ Restaurant / Admin APIs    │
                         └────────────┬─────────────┘
                                      │
                ┌─────────────────────┼─────────────────────┬───────────────┐
                ▼                     ▼                     ▼               ▼
        customer-mobile        rider-mobile           business-web     admin-web
        📱 Android              📱 Android             💻 Web           💻 Web
        Customer                Rider                  Restaurant       Admin
                                                         Owner
```

## Structure

```text
say_hi_chai/
├── backend/          FastAPI + SQLAlchemy + Alembic + PostgreSQL (shared)
├── customer-mobile/  Customer Android app (Expo Router + React Native)
├── rider-mobile/     Rider Android app (Expo Router + React Native)
├── business-web/     Restaurant-owner web app (React + Vite)
├── admin-web/        Admin web panel (React + Vite)
└── docs/             Architecture notes, per-phase docs
```

Each app is a fully independent project with its own `package.json`/build config — see its README for how to run it. None of them share a backend or database of their own; they all talk to `backend/`.

## Run the backend

```bash
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # adjust DATABASE_URL / CORS_ORIGINS if needed
alembic upgrade head
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Postgres itself runs via `backend/docker-compose.yml` (`docker compose up -d` from `backend/`).

## Run an app

- `customer-mobile/`, `rider-mobile/`: `npm install && npm run android` (or `npm start` for the Expo dev server). Set `EXPO_PUBLIC_API_BASE_URL` in `.env.development` if auto-detection of the backend host doesn't work.
- `business-web/`, `admin-web/`: `npm install && npm run dev`. Set `VITE_API_BASE_URL` in `.env` if the backend isn't on `localhost:8000`. Their dev-server origins (`5173`, `5174` by default) must be listed in the backend's `CORS_ORIGINS`.

## Live rider tracking

The rider live map, ETA, and delivery notifications are documented in `docs/`:

- `docs/live-tracking-architecture.md` — end-to-end design, WebSocket endpoint reference, tracking states, permissions/Android configuration, and production considerations.
- `docs/location-privacy.md` — what's stored, for how long, and who can see it.
- `docs/troubleshooting.md` — symptom-first debugging guide (no rider position showing, stuck ETA, WebSocket won't connect, 429s, etc.) — covers both live tracking and notifications.

## Notifications & communication

In-app notifications, Expo push delivery, per-user preferences, retry/idempotency, and retention for every role (customer, rider, restaurant owner, admin) are documented in `docs/`:

- `docs/notification-architecture.md` — the full pipeline (business event → notification service → in-app record → push delivery → client), API endpoint reference, device-token lifecycle, and security rules.
- `docs/notification-system-audit.md` — the original point-in-time audit this system was built against (now historical; see its own final-status note).
- `docs/troubleshooting.md` — symptom-first debugging guide (push not received, failed/retried deliveries, preference behavior, retention, admin-alert aggregation).

Push delivery uses Expo's push API — no credential is required for local development; set `EXPO_ACCESS_TOKEN` in `backend/.env` only to raise Expo's own rate limits in production (see `backend/.env.example`).
