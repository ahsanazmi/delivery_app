def test_customer_profile_get_and_patch(client):
    # register customer
    registration = client.post(
        "/api/v1/auth/register",
        json={"name": "Profile User", "email": "profile@example.com", "password": "secure-pass-123", "phone": "1112223333"},
    )
    assert registration.status_code == 201

    login = client.post("/api/v1/auth/login", json={"email": "profile@example.com", "password": "secure-pass-123"})
    assert login.status_code == 200
    tokens = login.json()

    # GET profile
    me = client.get("/api/v1/customer/profile", headers={"Authorization": f"Bearer {tokens['access_token']}"})
    assert me.status_code == 200
    assert me.json()["email"] == "profile@example.com"

    # PATCH profile
    patched = client.patch(
        "/api/v1/customer/profile",
        json={"name": "Updated Name", "email": "updated@example.com"},
        headers={"Authorization": f"Bearer {tokens['access_token']}"},
    )
    assert patched.status_code == 200
    assert patched.json()["name"] == "Updated Name"
    assert patched.json()["email"] == "updated@example.com"

    # GET again
    me2 = client.get("/api/v1/customer/profile", headers={"Authorization": f"Bearer {tokens['access_token']}"})
    assert me2.status_code == 200
    assert me2.json()["name"] == "Updated Name"
    assert me2.json()["email"] == "updated@example.com"


def _customer_token(client, email):
    assert client.post("/api/v1/auth/register", json={"name": "Profile User", "email": email, "password": "secure-pass-123"}).status_code == 201
    return client.post("/api/v1/auth/login", json={"email": email, "password": "secure-pass-123"}).json()["access_token"]


def test_changing_email_to_another_accounts_email_is_a_409_not_a_500(client):
    # E2E Validation Phase 7 — previously an unhandled IntegrityError (500),
    # which also revealed whether an email was registered.
    _customer_token(client, "taken@example.com")
    token = _customer_token(client, "mover@example.com")
    headers = {"Authorization": f"Bearer {token}"}

    for attempt in ("taken@example.com", "TAKEN@example.com"):
        response = client.patch("/api/v1/customer/profile", json={"email": attempt}, headers=headers)
        assert response.status_code == 409

    assert client.get("/api/v1/customer/profile", headers=headers).json()["email"] == "mover@example.com"


def test_re_saving_your_own_email_is_still_allowed(client):
    token = _customer_token(client, "same@example.com")
    response = client.patch("/api/v1/customer/profile", json={"email": "Same@Example.com", "name": "Same Person"}, headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200
    assert response.json()["email"] == "same@example.com"


def test_a_whitespace_only_name_is_rejected_not_saved_empty(client):
    # E2E Validation Phase 8 — min_length ran before .strip(), saving "".
    token = _customer_token(client, "blankname@example.com")
    headers = {"Authorization": f"Bearer {token}"}
    assert client.patch("/api/v1/customer/profile", json={"name": "   "}, headers=headers).status_code == 422
    assert client.get("/api/v1/customer/profile", headers=headers).json()["name"] == "Profile User"
