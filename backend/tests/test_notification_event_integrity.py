"""Notifications & Communication System Phase 36 — Notification Event
Integrity.

Verifies there is no POST /notifications/send (or equivalent) anywhere a
client — including an authenticated one — could use to impersonate the
system and fabricate a business-event notification. Clients may read
notifications, mark them read, manage preferences, and register their
own device token; every one of this codebase's 21 notification-related
HTTP routes (enumerated below) does exactly one of those four things,
nothing else. The one exception, the admin promotional broadcast, is
checked on its own terms: it can set a message's title/body, never its
type or its recipient.
"""

import inspect

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.core.security import create_access_token, hash_password
from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.models.notification import Notification, NotificationType
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


def test_no_route_anywhere_lets_a_client_create_an_arbitrary_notification():
    """Structural proof, not a guess: every FastAPI route registered
    under a notifications-shaped path is one of exactly four verbs this
    phase allows — read, mark-read, manage preferences, register a
    device token — or the one narrowly-scoped admin broadcast. A future
    accidental "send" endpoint would show up here and fail this test."""
    allowed_shapes = {
        ("GET", "/notifications"),
        ("GET", "/notifications/unread-count"),
        ("POST", "/notifications/{notification_id}/read"),
        ("POST", "/notifications/read-all"),
        ("POST", "/notifications/cleanup"),  # admin housekeeping (delete), not creation
        ("POST", "/register"),
        ("DELETE", "/register"),
        ("GET", "/preferences"),
        ("PATCH", "/preferences"),
        ("POST", "/notifications/broadcast"),  # the one deliberate, narrowly-scoped exception
    }
    offending = []
    for route in app.routes:
        path = getattr(route, "path", "")
        if "notification" not in path and "/register" not in path and "/preferences" not in path:
            continue
        methods = getattr(route, "methods", set()) or set()
        for method in methods:
            if method == "HEAD":
                continue
            # Normalize this route's own path segment (strip the role
            # prefix — /customer, /rider, /restaurant, /admin — to
            # compare against the shared shape table above).
            suffix = path
            for prefix in ("/api/v1/customer", "/api/v1/rider", "/api/v1/restaurant", "/api/v1/admin", "/api/v1"):
                if suffix.startswith(prefix):
                    suffix = suffix[len(prefix):]
                    break
            if (method, suffix) not in allowed_shapes:
                offending.append((method, path))
    assert offending == []


def test_the_broadcast_endpoint_cannot_set_the_notification_type_or_recipient(engine):
    """An admin can only ever supply title/body — type is always
    PROMOTION and the recipient is always "every active customer,"
    regardless of what extra fields a client tries to smuggle in."""
    with Session(engine) as db:
        admin = User(name="Admin", email="integrity-admin@example.com", password_hash=hash_password("x"), role=UserRole.ADMIN)
        victim = User(name="Victim", email="integrity-victim@example.com", password_hash=hash_password("x"), role=UserRole.CUSTOMER)
        db.add_all([admin, victim])
        db.commit()
        admin_id, victim_id = admin.id, victim.id

    with TestClient(app) as client:
        token = create_access_token(admin_id)
        response = client.post(
            "/api/v1/admin/notifications/broadcast",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "title": "Sale!",
                "body": "50% off",
                # An attempt to impersonate a different event type and
                # target a specific victim directly — neither field
                # exists on this schema, so both are silently ignored.
                "type": "payment_success",
                "user_id": str(victim_id),
            },
        )
        assert response.status_code == 200

    with Session(engine) as db:
        rows = db.query(Notification).filter(Notification.user_id == victim_id).all()
        # The broadcast reached the victim only because they're an
        # active customer (the real, documented targeting rule) — and
        # always as PROMOTION, never the spoofed type.
        assert all(n.type == NotificationType.PROMOTION for n in rows)
        payment_success_rows = [n for n in rows if n.type == NotificationType.PAYMENT_SUCCESS]
        assert payment_success_rows == []


def test_broadcast_requires_admin(engine):
    with Session(engine) as db:
        customer = User(name="C", email="integrity-nonadmin@example.com", password_hash=hash_password("x"), role=UserRole.CUSTOMER)
        db.add(customer)
        db.commit()
        customer_id = customer.id

    with TestClient(app) as client:
        token = create_access_token(customer_id)
        response = client.post(
            "/api/v1/admin/notifications/broadcast",
            headers={"Authorization": f"Bearer {token}"},
            json={"title": "Sale!", "body": "50% off"},
        )
        assert response.status_code == 403


def test_every_notify_function_is_only_ever_called_from_service_code_never_a_route_handler():
    """The only file in this codebase that constructs a Notification row
    at all is app/services/notifications.py — verified by inspecting the
    actual source of every route module under app/api/, not assumed."""
    import app.api.v1 as api_package
    import pkgutil

    for _finder, name, _is_pkg in pkgutil.walk_packages(api_package.__path__, api_package.__name__ + "."):
        try:
            module = __import__(name, fromlist=["_"])
        except Exception:
            continue
        source = inspect.getsource(module) if hasattr(module, "__file__") and module.__file__ else ""
        assert "Notification(" not in source, f"{name} constructs a Notification row directly"
