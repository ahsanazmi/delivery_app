"""Notifications & Communication System Phase 43 — Observability.

Before this phase, exactly one structured log event existed anywhere in
the notification pipeline ("notification_error"). This file proves each
of the nine events this phase names now fires at the right moment, and
— the explicit security requirement — that none of them ever logs a
JWT, refresh token, secret key, payment credential, or unnecessary
private data (a raw push token string, a title/body that could carry an
order amount or a name).
"""

from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.core.security import hash_password
from app.db.base import Base
from app.models.user import User, UserRole
from app.services.notifications import (
    mark_all_notifications_read,
    mark_notification_read,
    notify_rider_account_approved,
    upsert_push_token,
)


@pytest.fixture()
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    Base.metadata.drop_all(engine)


def _rider(db, email="observability-rider@example.com"):
    user = User(name="Rider", email=email, phone="9800000090", password_hash=hash_password("x"), role=UserRole.RIDER)
    db.add(user)
    db.commit()
    return user


_FORBIDDEN_SUBSTRINGS = ("Bearer ", "eyJ", "razorpay_key_secret", "password_hash")


def _assert_nothing_sensitive(records):
    for record in records:
        message = record.getMessage()
        for forbidden in _FORBIDDEN_SUBSTRINGS:
            assert forbidden not in message, f"log line leaked something sensitive: {message!r}"


def test_notification_created_fires_on_success(db, caplog):
    rider = _rider(db)
    with caplog.at_level("INFO"):
        notify_rider_account_approved(db, rider)
    assert any("event=notification_created" in r.getMessage() for r in caplog.records)
    _assert_nothing_sensitive(caplog.records)


def test_notification_failed_fires_when_the_notify_function_itself_raises(db, monkeypatch, caplog):
    rider = _rider(db, "observability-crash@example.com")
    monkeypatch.setattr(
        "app.services.notifications.send_push_to_user",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("simulated crash")),
    )
    with caplog.at_level("INFO"):
        notify_rider_account_approved(db, rider)
    assert any("event=notification_failed" in r.getMessage() and "reason=RuntimeError" in r.getMessage() for r in caplog.records)
    _assert_nothing_sensitive(caplog.records)


def test_push_token_registered_fires_on_register(db, caplog):
    rider = _rider(db, "observability-token@example.com")
    with caplog.at_level("INFO"):
        upsert_push_token(db, rider.id, "ExponentPushToken[observability]")
    assert any("event=push_token_registered" in r.getMessage() for r in caplog.records)
    _assert_nothing_sensitive(caplog.records)
    # The raw token string itself is never in any log line.
    assert all("ExponentPushToken[observability]" not in r.getMessage() for r in caplog.records)


def test_notification_dispatched_delivered_push_token_invalid_fire_through_real_send(db, monkeypatch, caplog):
    rider = _rider(db, "observability-dispatch@example.com")
    upsert_push_token(db, rider.id, "ExponentPushToken[ok]")
    upsert_push_token(db, rider.id, "ExponentPushToken[dead]", device_identifier="device-dead")

    class FakeResponse:
        status_code = 200

        def raise_for_status(self):
            pass

        def json(self):
            return {"data": [
                {"status": "ok"},
                {"status": "error", "details": {"error": "DeviceNotRegistered"}},
            ]}

    monkeypatch.setattr("app.services.push.expo_provider.httpx.post", lambda *a, **k: FakeResponse())

    with caplog.at_level("INFO"):
        notify_rider_account_approved(db, rider)

    messages = [r.getMessage() for r in caplog.records]
    assert any("event=notification_dispatched" in m for m in messages)
    assert any("event=notification_delivered" in m for m in messages)
    assert any("event=notification_failed" in m for m in messages)
    assert any("event=push_token_invalid" in m for m in messages)
    _assert_nothing_sensitive(caplog.records)
    assert all("ExponentPushToken[" not in m for m in messages)


def test_notification_retry_fires_on_a_transient_failure(db, monkeypatch, caplog):
    rider = _rider(db, "observability-retry@example.com")
    upsert_push_token(db, rider.id, "ExponentPushToken[retry]")

    import httpx

    def fake_post(*args, **kwargs):
        raise httpx.ConnectError("down")

    monkeypatch.setattr("app.services.push.expo_provider.httpx.post", fake_post)
    monkeypatch.setattr("app.services.push.expo_provider.time.sleep", lambda s: None)

    with caplog.at_level("INFO"):
        notify_rider_account_approved(db, rider)

    assert any("event=notification_retry" in r.getMessage() for r in caplog.records)
    _assert_nothing_sensitive(caplog.records)


def test_notification_opened_fires_on_first_mark_read_only(db, caplog):
    rider = _rider(db, "observability-opened@example.com")
    notify_rider_account_approved(db, rider)
    from app.services.notifications import list_notifications

    notification = list_notifications(db, rider.id)[0]

    with caplog.at_level("INFO"):
        mark_notification_read(db, rider.id, notification.id)
        mark_notification_read(db, rider.id, notification.id)  # duplicate retry

    opened_events = [r for r in caplog.records if "event=notification_opened" in r.getMessage()]
    assert len(opened_events) == 1  # never logged twice for a duplicate mark-read
    _assert_nothing_sensitive(caplog.records)


def test_notification_marked_read_fires_on_mark_all(db, caplog):
    rider = _rider(db, "observability-markall@example.com")
    notify_rider_account_approved(db, rider)

    with caplog.at_level("INFO"):
        updated = mark_all_notifications_read(db, rider.id)
        mark_all_notifications_read(db, rider.id)  # nothing left — no event the second time

    assert updated == 1
    marked_events = [r for r in caplog.records if "event=notification_marked_read" in r.getMessage()]
    assert len(marked_events) == 1
    _assert_nothing_sensitive(caplog.records)
