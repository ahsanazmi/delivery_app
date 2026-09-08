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
