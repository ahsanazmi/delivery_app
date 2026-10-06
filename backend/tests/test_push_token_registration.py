"""Notifications & Communication System Phase 15 — Push Token Registration.

The HTTP surface (POST/DELETE /api/v1/notifications/register — this
codebase's own existing route, kept rather than renamed to the phase's
own illustrative /device-token path, the same "defer to the actual
codebase convention over an example path" call made throughout this
protocol) plus upsert_push_token's own new cross-user guarantee, each
checked against this phase's own named scenarios: new device, existing
token, duplicate token, logout, token refresh, inactive token — and the
phase's own explicit security requirement, that the authenticated user
always owns the registration, never an arbitrary user_id.
"""

from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.core.security import create_access_token, hash_password
from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.models.push_token import PushToken
from app.models.user import User, UserRole
from app.services.notifications import delete_push_token, upsert_push_token
from app.services.push_notifications import send_push_to_user


@pytest.fixture()
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    Base.metadata.drop_all(engine)


def _user(db, email, role=UserRole.CUSTOMER):
    user = User(name="User", email=email, password_hash=hash_password("x"), role=role)
    db.add(user)
    db.commit()
    return user


class FakeResponse:
    def __init__(self, data, status_code=200):
        self._data = data
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        return {"data": self._data}


# ---------------------------------------------------------------------------
# Service-level: the six named scenarios
# ---------------------------------------------------------------------------


def test_new_device(db):
    user = _user(db, "new-device@example.com")
    token = upsert_push_token(db, user.id, "ExponentPushToken[a]", device_identifier="device-a")
    assert token.user_id == user.id
    assert token.is_active is True


def test_existing_token_is_updated_not_duplicated(db):
    user = _user(db, "existing-token@example.com")
    first = upsert_push_token(db, user.id, "ExponentPushToken[a]")
    second = upsert_push_token(db, user.id, "ExponentPushToken[a]", platform="ios")

    assert second.id == first.id
    rows = list(db.scalars(select(PushToken).where(PushToken.user_id == user.id)))
    assert len(rows) == 1
    assert rows[0].platform == "ios"


def test_duplicate_token_across_two_users_deactivates_the_previous_owner(db, monkeypatch):
    """The real anomaly this phase's "duplicate token" scenario names: a
    shared/reused device where a second person signs in without the app
    ever requesting a fresh push token. Without this guarantee, both
    accounts would keep receiving each other's pushes on that one
    device."""
    user_a = _user(db, "device-owner-a@example.com")
    user_b = _user(db, "device-owner-b@example.com")

    row_a = upsert_push_token(db, user_a.id, "ExponentPushToken[shared]")
    assert row_a.is_active is True

    row_b = upsert_push_token(db, user_b.id, "ExponentPushToken[shared]")
    assert row_b.is_active is True
    assert row_b.user_id == user_b.id

    db.refresh(row_a)
    assert row_a.is_active is False

    captured = {}

    def fake_post(url, json, timeout, headers):
        captured["messages"] = json
        return FakeResponse([{"status": "ok"}])

    monkeypatch.setattr("app.services.push.expo_provider.httpx.post", fake_post)
    send_push_to_user(db, user_a.id, "Title", "Body")
    assert "messages" not in captured  # user A's now-deactivated row was never sent to

    send_push_to_user(db, user_b.id, "Title", "Body")
    assert captured["messages"] == [
        {"to": "ExponentPushToken[shared]", "title": "Title", "body": "Body", "data": {}, "sound": "default"}
    ]


def test_logout(db, monkeypatch):
    user = _user(db, "logout@example.com")
    upsert_push_token(db, user.id, "ExponentPushToken[a]")

    delete_push_token(db, user.id, "ExponentPushToken[a]")

    called = False

    def fake_post(*args, **kwargs):
        nonlocal called
        called = True
        return FakeResponse([])

    monkeypatch.setattr("app.services.push.expo_provider.httpx.post", fake_post)
    send_push_to_user(db, user.id, "Title", "Body")
    assert called is False

    # The row itself is preserved (soft-deactivated), not deleted.
    rows = list(db.scalars(select(PushToken).where(PushToken.user_id == user.id)))
    assert len(rows) == 1
    assert rows[0].is_active is False


def test_token_refresh(db):
    """The same device's push token rotates at the OS level — recognized
    via device_identifier, never mistaken for a second device."""
    user = _user(db, "refresh@example.com")
    original = upsert_push_token(db, user.id, "ExponentPushToken[old]", device_identifier="device-x")

    refreshed = upsert_push_token(db, user.id, "ExponentPushToken[new]", device_identifier="device-x")

    assert refreshed.id == original.id
    rows = list(db.scalars(select(PushToken).where(PushToken.user_id == user.id)))
    assert len(rows) == 1
    assert rows[0].token == "ExponentPushToken[new]"


def test_inactive_token_is_reactivated_on_reregistration(db):
    user = _user(db, "inactive@example.com")
    upsert_push_token(db, user.id, "ExponentPushToken[a]", device_identifier="device-a")
    delete_push_token(db, user.id, "ExponentPushToken[a]")

    row = db.scalar(select(PushToken).where(PushToken.user_id == user.id))
    assert row.is_active is False

    revived = upsert_push_token(db, user.id, "ExponentPushToken[a]", device_identifier="device-a")
    assert revived.is_active is True
    assert revived.id == row.id


# ---------------------------------------------------------------------------
# HTTP surface + security — the authenticated user owns the registration
# ---------------------------------------------------------------------------


def _client_with_db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)

    def override_get_db():
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    return engine


def test_registration_always_belongs_to_the_authenticated_caller_never_an_arbitrary_user_id():
    engine = _client_with_db()
    try:
        with Session(engine) as seed:
            real_user = _user(seed, "real-caller@example.com")
            victim = _user(seed, "victim@example.com")
            token = create_access_token(real_user.id)
            real_user_id, victim_id = real_user.id, victim.id

        with TestClient(app) as client:
            response = client.post(
                "/api/v1/notifications/register",
                headers={"Authorization": f"Bearer {token}"},
                # An attacker-supplied user_id in the payload — PushTokenCreate
                # has no such field at all, so this can only ever be silently
                # ignored, never honored.
                json={"token": "ExponentPushToken[attack]", "platform": "expo", "user_id": str(victim_id)},
            )
            assert response.status_code == 200
            assert response.json()["user_id"] == str(real_user_id)

        with Session(engine) as check:
            row = check.scalar(select(PushToken).where(PushToken.token == "ExponentPushToken[attack]"))
            assert row.user_id == real_user_id
            victim_rows = check.scalars(select(PushToken).where(PushToken.user_id == victim_id)).all()
            assert victim_rows == []
    finally:
        app.dependency_overrides.clear()
        Base.metadata.drop_all(engine)


def test_unregister_over_http_cannot_deactivate_another_users_token():
    engine = _client_with_db()
    try:
        with Session(engine) as seed:
            attacker = _user(seed, "attacker@example.com")
            victim = _user(seed, "victim2@example.com")
            upsert_push_token(seed, victim.id, "ExponentPushToken[victim]")
            attacker_token = create_access_token(attacker.id)
            victim_id = victim.id

        with TestClient(app) as client:
            response = client.request(
                "DELETE",
                "/api/v1/notifications/register",
                headers={"Authorization": f"Bearer {attacker_token}"},
                params={"token": "ExponentPushToken[victim]"},
            )
            assert response.status_code == 204  # always a no-op success, never leaks whether the token exists

        with Session(engine) as check:
            victim_row = check.scalar(select(PushToken).where(PushToken.user_id == victim_id))
            assert victim_row.is_active is True  # untouched
    finally:
        app.dependency_overrides.clear()
        Base.metadata.drop_all(engine)
