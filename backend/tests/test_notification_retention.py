"""Notifications & Communication System Phase 34 — Notification
History/Retention.

No cleanup mechanism existed at all before this phase — list_notifications'
own 100-row cap only ever bounded what one query returns, never how large
the table itself grew. purge_old_notifications is the actual fix: read
notifications past 90 days are purged; unread ones are deliberately kept
far longer (365 days) — "do not delete active/important operational
notifications prematurely" — and never purged at all once a fresh,
still-unread notification exists just past the read-retention boundary.
"""

from datetime import UTC, datetime, timedelta
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
from app.models.notification import Notification, NotificationType
from app.models.user import User, UserRole
from app.services.notifications import purge_old_notifications


@pytest.fixture()
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    Base.metadata.drop_all(engine)


def _customer(db, email="customer-p34@example.com"):
    user = User(name="Cust", email=email, password_hash=hash_password("x"), role=UserRole.CUSTOMER)
    db.add(user)
    db.commit()
    return user


def _notification(db, user, *, is_read, age_days):
    created_at = datetime.now(UTC) - timedelta(days=age_days)
    notification = Notification(
        user_id=user.id, role=UserRole.CUSTOMER, type=NotificationType.SYSTEM,
        title="T", body="B", is_read=is_read, created_at=created_at,
        read_at=created_at if is_read else None,
    )
    db.add(notification)
    db.commit()
    db.refresh(notification)
    return notification


def test_read_notifications_older_than_the_retention_window_are_purged(db):
    customer = _customer(db)
    old_read_id = _notification(db, customer, is_read=True, age_days=91).id

    deleted = purge_old_notifications(db)

    assert deleted == 1
    assert db.query(Notification).filter(Notification.id == old_read_id).first() is None


def test_read_notifications_within_the_retention_window_are_kept(db):
    customer = _customer(db)
    recent_read = _notification(db, customer, is_read=True, age_days=89)

    deleted = purge_old_notifications(db)

    assert deleted == 0
    assert db.get(Notification, recent_read.id) is not None


def test_unread_notifications_are_never_purged_on_the_read_retention_schedule(db):
    """"Do not delete active/important operational notifications
    prematurely" — an unread notification far past the 90-day read
    window, but still within the much longer unread backstop, survives."""
    customer = _customer(db)
    old_unread = _notification(db, customer, is_read=False, age_days=200)

    deleted = purge_old_notifications(db)

    assert deleted == 0
    assert db.get(Notification, old_unread.id) is not None


def test_unread_notifications_past_the_long_backstop_are_eventually_purged(db):
    """Bounds worst-case table growth from a notification that will
    truly never be read — a much longer window than the routine
    read-retention cleanup, never a short/aggressive one."""
    customer = _customer(db)
    ancient_unread_id = _notification(db, customer, is_read=False, age_days=400).id

    deleted = purge_old_notifications(db)

    assert deleted == 1
    assert db.query(Notification).filter(Notification.id == ancient_unread_id).first() is None


def test_purge_is_idempotent_and_safe_to_call_repeatedly(db):
    customer = _customer(db)
    _notification(db, customer, is_read=True, age_days=200)

    first = purge_old_notifications(db)
    second = purge_old_notifications(db)  # nothing left to delete

    assert first == 1
    assert second == 0


def test_cleanup_endpoint_requires_admin():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)

    def override_get_db():
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    try:
        with Session(engine) as seed:
            customer = _customer(seed, "cleanup-http@example.com")
            token = create_access_token(customer.id)

        with TestClient(app) as client:
            response = client.post(
                "/api/v1/admin/notifications/cleanup", headers={"Authorization": f"Bearer {token}"}
            )
            assert response.status_code == 403
    finally:
        app.dependency_overrides.clear()
        Base.metadata.drop_all(engine)


def test_cleanup_endpoint_over_http():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)

    def override_get_db():
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    try:
        with Session(engine) as seed:
            admin = User(name="Admin", email="admin-cleanup@example.com", password_hash=hash_password("x"), role=UserRole.ADMIN)
            seed.add(admin)
            seed.commit()
            customer = _customer(seed, "cleanup-target@example.com")
            _notification(seed, customer, is_read=True, age_days=200)
            token = create_access_token(admin.id)

        with TestClient(app) as client:
            response = client.post(
                "/api/v1/admin/notifications/cleanup", headers={"Authorization": f"Bearer {token}"}
            )
            assert response.status_code == 200
            assert response.json()["deleted"] == 1
    finally:
        app.dependency_overrides.clear()
        Base.metadata.drop_all(engine)
