"""Notifications & Communication System Phase 14 — Push Token Domain.

Covers the actual domain-model upgrade: device_identifier, is_active,
last_seen_at, updated_at on PushToken, and upsert_push_token's own new
matching rules — proving this codebase never assumes one user has at
most one device.
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


def _customer(db, email="customer-p14@example.com"):
    user = User(name="Customer", email=email, password_hash=hash_password("x"), role=UserRole.CUSTOMER)
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


def test_registering_two_devices_for_one_user_creates_two_rows(db):
    customer = _customer(db)
    upsert_push_token(db, customer.id, "ExponentPushToken[phone]", device_identifier="device-phone")
    upsert_push_token(db, customer.id, "ExponentPushToken[tablet]", device_identifier="device-tablet")

    rows = list(db.scalars(select(PushToken).where(PushToken.user_id == customer.id)))
    assert len(rows) == 2
    assert {r.device_identifier for r in rows} == {"device-phone", "device-tablet"}
    assert all(r.is_active for r in rows)


def test_both_devices_receive_a_push(db, monkeypatch):
    customer = _customer(db)
    upsert_push_token(db, customer.id, "ExponentPushToken[phone]", device_identifier="device-phone")
    upsert_push_token(db, customer.id, "ExponentPushToken[tablet]", device_identifier="device-tablet")

    captured = {}

    def fake_post(url, json, timeout, headers):
        captured["messages"] = json
        return FakeResponse([{"status": "ok"}, {"status": "ok"}])

    monkeypatch.setattr("app.services.push.expo_provider.httpx.post", fake_post)
    send_push_to_user(db, customer.id, "Title", "Body")

    assert {m["to"] for m in captured["messages"]} == {"ExponentPushToken[phone]", "ExponentPushToken[tablet]"}


def test_reregistering_the_same_device_with_a_rotated_token_updates_the_existing_row(db):
    """A push token itself rotates periodically at the OS level — this must
    never be mistaken for a second device."""
    customer = _customer(db)
    first = upsert_push_token(db, customer.id, "ExponentPushToken[old]", device_identifier="device-phone")

    second = upsert_push_token(db, customer.id, "ExponentPushToken[new]", device_identifier="device-phone")

    assert second.id == first.id
    rows = list(db.scalars(select(PushToken).where(PushToken.user_id == customer.id)))
    assert len(rows) == 1
    assert rows[0].token == "ExponentPushToken[new]"


def test_old_rotated_token_is_never_used_once_replaced(db, monkeypatch):
    customer = _customer(db)
    upsert_push_token(db, customer.id, "ExponentPushToken[old]", device_identifier="device-phone")
    upsert_push_token(db, customer.id, "ExponentPushToken[new]", device_identifier="device-phone")

    captured = {}

    def fake_post(url, json, timeout, headers):
        captured["messages"] = json
        return FakeResponse([{"status": "ok"}])

    monkeypatch.setattr("app.services.push.expo_provider.httpx.post", fake_post)
    send_push_to_user(db, customer.id, "Title", "Body")

    assert captured["messages"] == [
        {"to": "ExponentPushToken[new]", "title": "Title", "body": "Body", "data": {}, "sound": "default"}
    ]


def test_registering_without_a_device_identifier_falls_back_to_token_matching(db):
    """Backward compatibility — an older client that never sends
    device_identifier must keep working exactly as this table always has."""
    customer = _customer(db)
    first = upsert_push_token(db, customer.id, "ExponentPushToken[legacy]")
    second = upsert_push_token(db, customer.id, "ExponentPushToken[legacy]", platform="ios")

    assert second.id == first.id
    assert second.device_identifier is None
    rows = list(db.scalars(select(PushToken).where(PushToken.user_id == customer.id)))
    assert len(rows) == 1


def test_upsert_touches_last_seen_at_and_reactivates(db):
    customer = _customer(db)
    token = upsert_push_token(db, customer.id, "ExponentPushToken[a]", device_identifier="device-a")
    first_seen = token.last_seen_at

    delete_push_token(db, customer.id, "ExponentPushToken[a]")
    db.refresh(token)
    assert token.is_active is False

    revived = upsert_push_token(db, customer.id, "ExponentPushToken[a]", device_identifier="device-a")
    assert revived.id == token.id
    assert revived.is_active is True
    assert revived.last_seen_at >= first_seen


def test_deactivated_device_no_longer_receives_pushes(db, monkeypatch):
    customer = _customer(db)
    upsert_push_token(db, customer.id, "ExponentPushToken[a]", device_identifier="device-a")
    delete_push_token(db, customer.id, "ExponentPushToken[a]")

    called = False

    def fake_post(*args, **kwargs):
        nonlocal called
        called = True
        return FakeResponse([])

    monkeypatch.setattr("app.services.push.expo_provider.httpx.post", fake_post)
    send_push_to_user(db, customer.id, "Title", "Body")
    assert called is False


def test_register_push_token_over_http_accepts_device_identifier():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)

    def override_get_db():
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    try:
        with Session(engine) as seed:
            customer = _customer(seed, email="customer-p14-http@example.com")
            token = create_access_token(customer.id)

        with TestClient(app) as client:
            response = client.post(
                "/api/v1/notifications/register",
                headers={"Authorization": f"Bearer {token}"},
                json={"token": "ExponentPushToken[http]", "platform": "expo", "device_identifier": "device-http"},
            )
            assert response.status_code == 200
            body = response.json()
            assert body["device_identifier"] == "device-http"
            assert body["is_active"] is True
            assert "last_seen_at" in body and "updated_at" in body
    finally:
        app.dependency_overrides.clear()
        Base.metadata.drop_all(engine)
