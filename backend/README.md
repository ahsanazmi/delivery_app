FastAPI backend for Say Hi Chai.

Quick start (Linux/macOS):

```bash
cp .env.example .env
docker compose up -d postgres
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
alembic upgrade head
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Dev notes:
- Swagger UI: `http://localhost:8000/docs`
- API root: `http://localhost:8000/api/v1`
- Auth: `POST /auth/register`, `POST /auth/login`, `POST /auth/refresh`
- Current user: `GET /users/me` with `Authorization: Bearer <access_token>`
- Admin-only role assignment: `PATCH /users/{user_id}/role` with `{ "role": "RESTAURANT" | "RIDER" | "ADMIN" | "CUSTOMER" }`
- Restaurants: public `GET /restaurants` and `GET /restaurants/{id}`; restaurant-owner/admin create and manage with `POST`, `PATCH`, `DELETE /restaurants/{id}`, `PATCH /restaurants/{id}/images`, and `PATCH /restaurants/{id}/open-status`

Run the authentication suite with `pytest`. Keep `.env` out of version control;
generate a production secret with `openssl rand -hex 32`.

Create the first administrator locally after migrating the database:

```bash
python -m app.scripts.create_admin --name "Admin Name" --email admin@example.com --phone 9876543210
```
