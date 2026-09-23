"""Rider Portal — Phase 6: Rider Approval Status enforcement (going online).

Updated for Phase 7: going online now requires more than APPROVED alone
(required documents approved + profile/vehicle info complete) — see
test_rider_online_eligibility.py for tests specific to those new conditions.
The tests here that need a genuinely online-eligible rider use
_make_rider_fully_eligible() to satisfy every condition up front, so this
file still cleanly proves the original APPROVED/SUSPENDED/PENDING behavior."""

from app.core.security import create_access_token, hash_password
from app.models.user import User, UserRole


def _register_and_login_rider(client, email="rider-status@example.com", phone="9500000010", name="Ravi Kumar"):
    client.post(
        "/api/v1/auth/register",
        json={"name": name, "email": email, "password": "secure-pass-123", "phone": phone, "role": "RIDER"},
    )
    login = client.post("/api/v1/auth/login", json={"email": email, "password": "secure-pass-123"})
    return login.json()["access_token"]


def _make_admin(client, email="admin-status@example.com", phone="9500000099"):
    from app.db.session import get_db

    db_gen = client.app.dependency_overrides[get_db]()
    db = next(db_gen)
    admin = User(name="Admin", email=email, phone=phone, password_hash=hash_password("x"), role=UserRole.ADMIN)
    db.add(admin)
    db.commit()
    token = create_access_token(admin.id)
    db.close()
    return token


def _rider_id(client, token):
    return client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"}).json()["id"]


def _approve(client, admin_token, rider_id):
    client.patch(
        f"/api/v1/admin/riders/{rider_id}/verification",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"approval_status": "APPROVED"},
    )


_REQUIRED_DOCS = ("DRIVING_LICENSE", "VEHICLE_REGISTRATION", "IDENTITY_DOCUMENT", "PROFILE_PHOTO")


def _make_rider_fully_eligible(client, admin_token, rider_token, rider_id):
    """Since Phase 7, APPROVED alone isn't enough to go online — every
    required document must also be uploaded and approved, and vehicle info
    must be set. This satisfies all of it, for tests that need a genuinely
    online-eligible rider rather than testing the eligibility rules themselves."""
    rider_headers = {"Authorization": f"Bearer {rider_token}"}
    admin_headers = {"Authorization": f"Bearer {admin_token}"}
    for doc_type in _REQUIRED_DOCS:
        created = client.post(
            "/api/v1/rider/documents", headers=rider_headers,
            json={"document_type": doc_type, "document_url": f"https://example.com/{doc_type.lower()}.jpg"},
        ).json()
        client.patch(
            f"/api/v1/admin/riders/{rider_id}/documents/{created['id']}",
            headers=admin_headers, json={"verification_status": "APPROVED"},
        )
    client.patch(
        "/api/v1/rider/vehicle", headers=rider_headers,
        json={"vehicle_type": "BIKE", "vehicle_number": "KA01AB1234"},
    )


# --------------------------- PENDING: cannot go online ---------------------------


def test_pending_rider_cannot_go_online(client):
    token = _register_and_login_rider(client)
    response = client.patch(
        "/api/v1/rider/status", headers={"Authorization": f"Bearer {token}"}, json={"is_online": True}
    )
    assert response.status_code == 403
    assert "under review" in response.json()["detail"].lower()


def test_new_rider_status_starts_offline(client):
    token = _register_and_login_rider(client)
    response = client.get("/api/v1/rider/status", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200
    body = response.json()
    assert body["approval_status"] == "PENDING"
    assert body["is_online"] is False


def test_pending_rider_can_still_explicitly_go_offline(client):
    """Going offline is always allowed regardless of status — there's no
    reason to ever reject it, even though the account can't be online yet."""
    token = _register_and_login_rider(client)
    response = client.patch(
        "/api/v1/rider/status", headers={"Authorization": f"Bearer {token}"}, json={"is_online": False}
    )
    assert response.status_code == 200
    assert response.json()["is_online"] is False


# --------------------------- APPROVED: can go online ---------------------------


def test_approved_rider_can_go_online(client):
    token = _register_and_login_rider(client, email="approved-online@example.com", phone="9500000011")
    rider_id = _rider_id(client, token)
    admin_token = _make_admin(client)
    _approve(client, admin_token, rider_id)
    _make_rider_fully_eligible(client, admin_token, token, rider_id)

    response = client.patch(
        "/api/v1/rider/status", headers={"Authorization": f"Bearer {token}"}, json={"is_online": True}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["approval_status"] == "APPROVED"
    assert body["is_online"] is True

    # And can go back offline just as easily.
    offline = client.patch(
        "/api/v1/rider/status", headers={"Authorization": f"Bearer {token}"}, json={"is_online": False}
    )
    assert offline.status_code == 200
    assert offline.json()["is_online"] is False


# --------------------------- SUSPENDED: cannot accept deliveries / forced offline ---------------------------


def test_suspending_an_online_rider_forces_them_offline(client):
    token = _register_and_login_rider(client, email="suspend-online@example.com", phone="9500000012")
    rider_id = _rider_id(client, token)
    admin_token = _make_admin(client, email="admin2-status@example.com", phone="9500000098")
    _approve(client, admin_token, rider_id)
    _make_rider_fully_eligible(client, admin_token, token, rider_id)
    client.patch("/api/v1/rider/status", headers={"Authorization": f"Bearer {token}"}, json={"is_online": True})

    suspend = client.patch(
        f"/api/v1/admin/riders/{rider_id}/verification",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"approval_status": "SUSPENDED"},
    )
    assert suspend.status_code == 200
    assert suspend.json()["approval_status"] == "SUSPENDED"

    status_check = client.get("/api/v1/rider/status", headers={"Authorization": f"Bearer {token}"})
    assert status_check.json()["is_online"] is False


def test_suspended_rider_cannot_go_back_online(client):
    token = _register_and_login_rider(client, email="suspended-retry@example.com", phone="9500000013")
    rider_id = _rider_id(client, token)
    admin_token = _make_admin(client, email="admin3-status@example.com", phone="9500000097")
    _approve(client, admin_token, rider_id)
    client.patch(
        f"/api/v1/admin/riders/{rider_id}/verification",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"approval_status": "SUSPENDED"},
    )

    response = client.patch(
        "/api/v1/rider/status", headers={"Authorization": f"Bearer {token}"}, json={"is_online": True}
    )
    assert response.status_code == 403


def test_suspended_rider_still_cannot_pick_up_or_deliver():
    """Confirms assert_rider_approved covers SUSPENDED identically to
    PENDING/REJECTED. Originally written against the legacy dual-hop
    PATCH /rider/orders/{id}/pickup endpoint (removed in Phase 25's
    security audit, which also newly added this same approval check to the
    granular pickup_delivery() it was replaced by — that check didn't exist
    there before, so a suspended rider could previously keep progressing a
    delivery they'd accepted before being suspended). Updated to exercise
    the current granular endpoint instead."""
    # Re-uses the same helper pattern as test_rider_verification.py's
    # unapproved-rider test, but ends in SUSPENDED instead of never-approved.
    from decimal import Decimal

    from app.db.session import get_db
    from app.models.order import OrderStatus
    from app.models.product import Product
    from app.models.restaurant import Restaurant
    from app.services.addresses import create_address
    from app.services.cart import add_item, create_cart_for_user
    from app.services.orders import assign_rider_to_order, create_order, transition_order_status
    from fastapi.testclient import TestClient
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    from sqlalchemy.pool import StaticPool

    from app.db.base import Base
    from app.main import app

    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)

    def override_get_db():
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    try:
        with Session(engine) as db:
            owner = User(name="Owner", email="owner-s@example.com", phone="9500000020", password_hash=hash_password("x"), role=UserRole.RESTAURANT_OWNER)
            db.add(owner)
            db.commit()
            restaurant = Restaurant(
                owner_id=owner.id, name="Diner", phone="9876500002", address="Road",
                latitude=Decimal("12.1"), longitude=Decimal("77.1"),
                minimum_order=Decimal("0.00"), delivery_fee=Decimal("30.00"),
            )
            db.add(restaurant)
            db.commit()
            customer = User(name="Cust", email="cust-s@example.com", phone="9500000021", password_hash=hash_password("x"), role=UserRole.CUSTOMER)
            db.add(customer)
            db.commit()
            product = Product(restaurant_id=restaurant.id, name="Item", price=Decimal("100.00"))
            db.add(product)
            db.commit()
            cart = create_cart_for_user(db, customer.id)
            add_item(db, cart, product.id, 1)
            address = create_address(db, customer.id, {
                "label": "Home", "recipient_name": "Cust", "phone": "9999999999",
                "address_line": "1 Road", "city": "Bengaluru", "state": "Karnataka", "postal_code": "560001",
            })
            order = create_order(db, customer, address.id)
            transition_order_status(db, order, OrderStatus.CONFIRMED)
            transition_order_status(db, order, OrderStatus.PREPARING)
            transition_order_status(db, order, OrderStatus.READY_FOR_PICKUP)

            rider = User(name="Rider", email="suspended-pickup@example.com", phone="9500000022", password_hash=hash_password("x"), role=UserRole.RIDER)
            db.add(rider)
            db.commit()
            assign_rider_to_order(db, order, rider.id)
            order_id = order.id
            rider_id = rider.id
            rider_token = create_access_token(rider.id)

        with TestClient(app) as inner_client:
            admin_token = _make_admin(inner_client, email="admin4-status@example.com", phone="9500000096")
            inner_client.patch(
                f"/api/v1/admin/riders/{rider_id}/verification",
                headers={"Authorization": f"Bearer {admin_token}"},
                json={"approval_status": "APPROVED"},
            )
            inner_client.patch(
                f"/api/v1/admin/riders/{rider_id}/verification",
                headers={"Authorization": f"Bearer {admin_token}"},
                json={"approval_status": "SUSPENDED"},
            )

            response = inner_client.post(
                f"/api/v1/rider/deliveries/{order_id}/pickup", headers={"Authorization": f"Bearer {rider_token}"}
            )
            assert response.status_code == 403
    finally:
        app.dependency_overrides.clear()
        Base.metadata.drop_all(engine)


# --------------------------- Isolation / auth ---------------------------


def test_customer_and_restaurant_owner_cannot_access_rider_status(client):
    from app.db.session import get_db

    db_gen = client.app.dependency_overrides[get_db]()
    db = next(db_gen)
    customer = User(name="C", email="c-status@example.com", phone="9500000051", password_hash=hash_password("x"), role=UserRole.CUSTOMER)
    owner = User(name="O", email="o-status@example.com", phone="9500000052", password_hash=hash_password("x"), role=UserRole.RESTAURANT_OWNER)
    db.add_all([customer, owner])
    db.commit()
    customer_token = create_access_token(customer.id)
    owner_token = create_access_token(owner.id)
    db.close()

    assert client.get("/api/v1/rider/status", headers={"Authorization": f"Bearer {customer_token}"}).status_code == 403
    assert client.get("/api/v1/rider/status", headers={"Authorization": f"Bearer {owner_token}"}).status_code == 403


def test_unauthenticated_request_is_rejected(client):
    assert client.get("/api/v1/rider/status").status_code == 401
    assert client.patch("/api/v1/rider/status", json={"is_online": True}).status_code == 401
