import os

os.environ["DATABASE_URL"] = "sqlite://"
os.environ["JWT_SECRET_KEY"] = "test-secret-key-that-is-long-enough-to-be-safe"
# Payment System Phase 5 — the backend's own .env now carries real (test
# mode) Razorpay credentials for live/manual verification. The automated
# suite must never depend on network access or a real third-party account
# to pass, so it always sees Razorpay as unconfigured regardless of what a
# developer's local .env has — RazorpayProvider then honestly raises
# ProviderNotConfiguredError instead of making a real HTTP call. Any test
# that needs to exercise the "configured" path sets these explicitly
# itself (e.g. via monkeypatch or by passing key_id/key_secret directly to
# RazorpayProvider()).
os.environ["RAZORPAY_KEY_ID"] = ""
os.environ["RAZORPAY_KEY_SECRET"] = ""
os.environ["RAZORPAY_WEBHOOK_SECRET"] = ""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from app.core.rate_limit import _attempts as _rate_limit_attempts
from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.models import User  # noqa: F401


@pytest.fixture(autouse=True)
def _reset_rate_limits():
    """The rate limiter's in-memory buckets are module-level state shared
    across the whole test session — without this, tests that legitimately
    call /auth/login or /auth/register several times would eventually trip
    the same limiter meant to stop real brute-force attempts."""
    _rate_limit_attempts.clear()
    yield


@pytest.fixture()
def client():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)

    def override_get_db():
        from sqlalchemy.orm import Session
        with Session(engine, autoflush=False) as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()
    Base.metadata.drop_all(engine)


@pytest.fixture()
def no_delivery_radius_limit(monkeypatch):
    """For tests whose fixtures predate the delivery-radius rule and place
    the customer's address far from the restaurant (e.g. 12.1,77.1 vs
    Bengaluru, ~110 km) — they test order/location/rider behaviour, not
    the radius, so checkout's range check is switched off for them.
    tests/test_delivery_radius.py covers the rule itself."""
    monkeypatch.setattr("app.services.checkout.delivery_range_issue", lambda *args, **kwargs: None)
