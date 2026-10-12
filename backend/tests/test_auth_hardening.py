"""E2E Validation Phase 5 — authentication defects found during live testing."""

import uuid
from datetime import datetime, timedelta, timezone

import jwt

from app.core.config import settings
from app.services import auth as auth_service

PASSWORD = "Str0ng-Pass!"


def test_register_rejects_an_email_the_response_model_would_reject(client):
    # Previously 500: the account was created, then UserRead's EmailStr
    # failed on the response — and /auth/me 500'd for that account forever.
    response = client.post("/api/v1/auth/register", json={"name": "Odd Mail", "email": "someone@localhost", "password": PASSWORD})
    assert response.status_code == 422
    retry = client.post("/api/v1/auth/register", json={"name": "Odd Mail", "email": "someone@example.com", "password": PASSWORD})
    assert retry.status_code == 201


def test_a_token_without_exp_is_rejected(client):
    registered = client.post("/api/v1/auth/register", json={"name": "No Exp", "email": "noexp@example.com", "password": PASSWORD})
    token = jwt.encode({"sub": registered.json()["id"], "type": "access"}, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)
    assert client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"}).status_code == 401


def test_a_well_formed_token_is_still_accepted(client):
    registered = client.post("/api/v1/auth/register", json={"name": "Has Exp", "email": "hasexp@example.com", "password": PASSWORD})
    token = jwt.encode(
        {"sub": registered.json()["id"], "type": "access", "exp": datetime.now(timezone.utc) + timedelta(minutes=5)},
        settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM,
    )
    assert client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"}).status_code == 200


def test_login_for_an_unknown_account_still_spends_a_password_hash(client, monkeypatch):
    # Without this, unknown accounts answered ~20x faster than a wrong
    # password on a real account, revealing which emails are registered.
    calls = []
    real_verify = auth_service.verify_password
    monkeypatch.setattr(auth_service, "verify_password", lambda pw, h: calls.append(h) or real_verify(pw, h))
    response = client.post("/api/v1/auth/login", json={"email": f"nobody-{uuid.uuid4().hex}@example.com", "password": PASSWORD})
    assert response.status_code == 401
    assert calls == [auth_service._DUMMY_PASSWORD_HASH]


def test_register_rejects_a_phone_that_is_not_a_phone_number(client):
    # E2E Validation Phase 8 — any 8-20 characters used to be accepted.
    for bad in ("abcdefgh", "12345678x", "++91 98765 43210", "1234567"):
        response = client.post("/api/v1/auth/register", json={"name": "Bad Phone", "email": f"p{abs(hash(bad))}@example.com", "password": PASSWORD, "phone": bad})
        assert response.status_code == 422, bad


def test_register_still_accepts_common_phone_formats(client):
    for index, good in enumerate(("9876543210", "+91 98765 43211", "(022) 2345-6789")):
        response = client.post("/api/v1/auth/register", json={"name": "Good Phone", "email": f"good{index}@example.com", "password": PASSWORD, "phone": good})
        assert response.status_code == 201, good
        assert response.json()["phone"] == good


def test_register_rejects_a_whitespace_only_name(client):
    response = client.post("/api/v1/auth/register", json={"name": "    ", "email": "blank@example.com", "password": PASSWORD})
    assert response.status_code == 422
