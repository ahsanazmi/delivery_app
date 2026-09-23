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
