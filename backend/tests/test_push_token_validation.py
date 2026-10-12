"""E2E Validation Phase 22 — push tokens are validated as Expo push tokens
(the only kind this backend can deliver to). Live testing found "abc", ""
and "ExponentPushToken[]" stored as active tokens, and a 600-char value
crashing with a 500 on the 512-char column."""

import pytest

from app.core.security import create_access_token, hash_password
from app.db.session import get_db
from app.models.user import User, UserRole


def _headers(client, email):
    db = next(client.app.dependency_overrides[get_db]())
    user = User(name="Push User", email=email, password_hash=hash_password("x"), role=UserRole.CUSTOMER)
    db.add(user)
    db.commit()
    token = create_access_token(user.id)
    db.close()
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.parametrize("token", ["abc", "", "ExponentPushToken[]", "ExponentPushToken[has space]", "x" * 600])
def test_a_value_that_is_not_an_expo_push_token_is_rejected(client, token):
    response = client.post("/api/v1/notifications/register", headers=_headers(client, f"bad{abs(hash(token))}@example.com"), json={"token": token, "platform": "android"})
    assert response.status_code == 422


@pytest.mark.parametrize("token", ["ExponentPushToken[xxxxxxxxxxxxxxxxxxxxxx]", "ExpoPushToken[abc-123_X]"])
def test_real_expo_push_tokens_are_accepted(client, token):
    response = client.post("/api/v1/notifications/register", headers=_headers(client, f"ok{abs(hash(token))}@example.com"), json={"token": token, "platform": "ios"})
    assert response.status_code == 200
