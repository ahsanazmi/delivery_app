def test_register_login_refresh_and_me(client):
    registration = client.post(
        "/api/v1/auth/register",
        json={"name": "Asha Sharma", "email": "asha@example.com", "password": "secure-pass-123", "phone": "9876543210"},
    )
    assert registration.status_code == 201
    assert registration.json()["role"] == "CUSTOMER"
    assert "password_hash" not in registration.text

    duplicate = client.post(
        "/api/v1/auth/register",
        json={"name": "Asha Sharma", "email": "asha@example.com", "password": "secure-pass-123"},
    )
    assert duplicate.status_code == 409

    login = client.post("/api/v1/auth/login", json={"email": "asha@example.com", "password": "secure-pass-123"})
    assert login.status_code == 200
    tokens = login.json()

    me = client.get("/api/v1/users/me", headers={"Authorization": f"Bearer {tokens['access_token']}"})
    assert me.status_code == 200
    assert me.json()["email"] == "asha@example.com"

    refreshed = client.post("/api/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
    assert refreshed.status_code == 200
    assert refreshed.json()["access_token"] != tokens["access_token"]


def test_register_rejects_restaurant_owner_and_admin_roles(client):
    for role in ("RESTAURANT_OWNER", "ADMIN"):
        registration = client.post(
            "/api/v1/auth/register",
            json={
                "name": "Blocked Role User",
                "email": f"blocked-{role.lower()}@example.com",
                "password": "secure-pass-123",
                "phone": f"90000{'1' if role == 'ADMIN' else '2'}00000",
                "role": role,
            },
        )
        assert registration.status_code == 400
        assert "customer" in registration.json()["detail"].lower()


def test_register_allows_rider_role(client):
    """Unlike RESTAURANT_OWNER/ADMIN, RIDER is open self-registration —
    delivery partners sign up like customers, then get vetted in a later
    Rider Portal phase before they can actually go online."""
    registration = client.post(
        "/api/v1/auth/register",
        json={
            "name": "Rider User",
            "email": "rider@example.com",
            "password": "secure-pass-123",
            "phone": "9999999999",
            "role": "RIDER",
        },
    )
    assert registration.status_code == 201
    assert registration.json()["role"] == "RIDER"


def test_login_accepts_phone_and_customer_role_default(client):
    registration = client.post(
        "/api/v1/auth/register",
        json={
            "name": "Phone User",
            "email": "phone-user@example.com",
            "password": "secure-pass-123",
            "phone": "8888888888",
        },
    )
    assert registration.status_code == 201
    assert registration.json()["role"] == "CUSTOMER"

    login = client.post("/api/v1/auth/login", json={"phone": "8888888888", "password": "secure-pass-123"})
    assert login.status_code == 200
    assert "access_token" in login.json()


def test_login_accepts_phone_number_in_email_field(client):
    registration = client.post(
        "/api/v1/auth/register",
        json={
            "name": "Phone Login User",
            "email": "phone-login-user@example.com",
            "password": "secure-pass-123",
            "phone": "7777777777",
        },
    )
    assert registration.status_code == 201

    login = client.post("/api/v1/auth/login", json={"email": "7777777777", "password": "secure-pass-123"})
    assert login.status_code == 200
    assert "access_token" in login.json()


def test_register_accepts_blank_phone_and_lowercase_role(client):
    registration = client.post(
        "/api/v1/auth/register",
        json={
            "name": "Lowercase Role User",
            "email": "lowercase-role@example.com",
            "password": "secure-pass-123",
            "phone": "",
            "role": "customer",
        },
    )
    assert registration.status_code == 201
    assert registration.json()["role"] == "CUSTOMER"


def test_auth_me_and_logout_aliases(client):
    client.post(
        "/api/v1/auth/register",
        json={"name": "Logout User", "email": "logout@example.com", "password": "secure-pass-123", "phone": "6666666666"},
    )
    tokens = client.post(
        "/api/v1/auth/login",
        json={"email": "logout@example.com", "password": "secure-pass-123"},
    ).json()

    me = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {tokens['access_token']}"})
    assert me.status_code == 200
    assert me.json()["email"] == "logout@example.com"

    logout = client.post("/api/v1/auth/logout", headers={"Authorization": f"Bearer {tokens['access_token']}"})
    assert logout.status_code == 200
    assert logout.json()["message"] == "Logged out successfully"


def test_rejects_invalid_credentials_and_missing_token(client):
    assert client.get("/api/v1/users/me").status_code == 401
    assert client.post("/api/v1/auth/login", json={"email": "missing@example.com", "password": "wrong"}).status_code == 401


def test_role_guard_rejects_unauthorized_role():
    from fastapi import HTTPException

    from app.api.v1.deps import require_roles
    from app.models.user import User, UserRole

    customer = User(name="Customer", email="customer@example.com", password_hash="not-used")
    customer.role = UserRole.CUSTOMER
    try:
        require_roles(UserRole.ADMIN)(customer)
    except HTTPException as error:
        assert error.status_code == 403
    else:
        raise AssertionError("Customer role should not pass the admin guard")
