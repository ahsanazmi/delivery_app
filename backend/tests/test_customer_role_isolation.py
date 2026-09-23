"""Integration Phase 2 — Role Isolation for the customer namespace.

Every /api/v1/customer/* route previously depended on the bare
CurrentUser (any authenticated role), so a RIDER/RESTAURANT_OWNER/ADMIN
token could reach these endpoints and get a 200 instead of the 403 role
isolation demands, even though it could never see another customer's data
(queries scope by current_user.id, which has no customer-role rows under
a non-customer account). This file locks in the fix: require_customer()
gates every one of these routes now.
"""

from app.core.security import create_access_token, hash_password
from app.db.session import get_db
from app.models.user import User, UserRole


def _make_user(client, role: UserRole, email: str, phone: str) -> str:
    db_gen = client.app.dependency_overrides[get_db]()
    db = next(db_gen)
    user = User(name="Test User", email=email, phone=phone, password_hash=hash_password("Passw0rd!"), role=role)
    db.add(user)
    db.commit()
    token = create_access_token(user.id)
    db.close()
    return token


CUSTOMER_GET_ENDPOINTS = [
    "/api/v1/customer/orders",
    "/api/v1/customer/profile",
    "/api/v1/customer/addresses",
    "/api/v1/customer/favorites",
    "/api/v1/customer/cart",
    "/api/v1/customer/coupons",
    "/api/v1/customer/notifications",
    "/api/v1/customer/checkout",
    "/api/v1/customer/payment-methods",
]


def test_customer_namespace_rejects_rider_restaurant_owner_and_admin_tokens(client):
    for role, email, phone in (
        (UserRole.RIDER, "riderprobe@example.com", "9200000001"),
        (UserRole.RESTAURANT_OWNER, "ownerprobe@example.com", "9200000002"),
        (UserRole.ADMIN, "adminprobe@example.com", "9200000003"),
    ):
        token = _make_user(client, role, email, phone)
        headers = {"Authorization": f"Bearer {token}"}
        for path in CUSTOMER_GET_ENDPOINTS:
            response = client.get(path, headers=headers)
            assert response.status_code == 403, f"{role} should not reach {path}, got {response.status_code}"


def test_customer_token_still_reaches_customer_namespace(client):
    token = _make_user(client, UserRole.CUSTOMER, "custok@example.com", "9200000004")
    headers = {"Authorization": f"Bearer {token}"}
    for path in CUSTOMER_GET_ENDPOINTS:
        response = client.get(path, headers=headers)
        assert response.status_code == 200, f"CUSTOMER should reach {path}, got {response.status_code}"


def test_customer_tracking_websocket_rejects_a_non_customer_token(client):
    from starlette.websockets import WebSocketDisconnect

    token = _make_user(client, UserRole.RIDER, "riderws@example.com", "9200000005")
    try:
        with client.websocket_connect(f"/api/v1/customer/ws/orders/00000000-0000-0000-0000-000000000000?token={token}"):
            raise AssertionError("A rider token should not be accepted by the customer tracking socket")
    except WebSocketDisconnect as exc:
        assert exc.code == 4401
