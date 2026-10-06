"""Notifications & Communication System Phase 25 — Notification
Preference API.

GET/PATCH /api/v1/notifications/preferences already existed from Phase
24 (built as PUT there; switched to PATCH here to match this codebase's
own established convention for a partial update of a settings-shaped
resource — see /admin/settings, /rider/status — and this phase's own
example). This file covers what's actually new: key validation (an
unknown field, or a wrong-typed value, must be rejected with a 422, not
silently ignored or coerced) and authentication/authorization at the
HTTP boundary specifically for this endpoint.
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.core.security import create_access_token, hash_password
from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.models.user import User, UserRole


@pytest.fixture()
def engine():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)

    def override_get_db():
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    yield engine
    app.dependency_overrides.clear()
    Base.metadata.drop_all(engine)


def _headers_for_new_user(engine, email="prefs-api@example.com") -> dict[str, str]:
    with Session(engine) as seed:
        user = User(name="U", email=email, password_hash=hash_password("x"), role=UserRole.CUSTOMER)
        seed.add(user)
        seed.commit()
        token = create_access_token(user.id)
    return {"Authorization": f"Bearer {token}"}


def test_patch_rejects_an_unknown_preference_key(engine):
    headers = _headers_for_new_user(engine)
    with TestClient(app) as client:
        response = client.patch(
            "/api/v1/notifications/preferences", headers=headers, json={"not_a_real_category": False}
        )
        assert response.status_code == 422


def test_patch_rejects_a_non_boolean_value_for_a_known_key(engine):
    headers = _headers_for_new_user(engine, "prefs-api-type@example.com")
    with TestClient(app) as client:
        response = client.patch(
            "/api/v1/notifications/preferences", headers=headers, json={"promotions": "yes please"}
        )
        assert response.status_code == 422


def test_patch_accepts_a_valid_known_key(engine):
    headers = _headers_for_new_user(engine, "prefs-api-valid@example.com")
    with TestClient(app) as client:
        response = client.patch(
            "/api/v1/notifications/preferences", headers=headers, json={"system_notifications": False}
        )
        assert response.status_code == 200
        assert response.json()["system_notifications"] is False


def test_get_requires_authentication(engine):
    with TestClient(app) as client:
        response = client.get("/api/v1/notifications/preferences")
        assert response.status_code in (401, 403)


def test_patch_requires_authentication(engine):
    with TestClient(app) as client:
        response = client.patch("/api/v1/notifications/preferences", json={"promotions": False})
        assert response.status_code in (401, 403)


def test_patch_has_no_field_through_which_another_users_preferences_could_be_targeted(engine):
    """"Never allow a user to modify another user's preferences" —
    structurally enforced by NotificationPreferenceUpdate having no
    user_id field at all (and extra="forbid" rejecting an attempt to
    smuggle one in), on top of the endpoint always writing to
    current_user.id from the JWT."""
    with Session(engine) as seed:
        victim = User(name="Victim", email="victim-p25@example.com", password_hash=hash_password("x"), role=UserRole.CUSTOMER)
        seed.add(victim)
        seed.commit()
        victim_id = victim.id

    headers = _headers_for_new_user(engine, "attacker-p25@example.com")
    with TestClient(app) as client:
        response = client.patch(
            "/api/v1/notifications/preferences",
            headers=headers,
            json={"promotions": False, "user_id": str(victim_id)},
        )
        assert response.status_code == 422  # rejected outright by extra="forbid"

        victim_headers = {"Authorization": f"Bearer {create_access_token(victim_id)}"}
        victim_view = client.get("/api/v1/notifications/preferences", headers=victim_headers)
        assert victim_view.json()["promotions"] is True  # untouched
