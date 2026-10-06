"""Notifications & Communication System Phase 35 — Security/IDOR Audit.

A consolidated, explicitly-named sweep across every vector this phase's
own checklist names. Most of these were already independently enforced
by earlier phases (every list/mark-read/unread-count function has been
user_id-scoped since Phase 9, every router role-gated since it was
written) — this file is the single place that proves all of them
together, in one auditable sweep, rather than leaving the evidence
scattered across a dozen different phase-specific test files.
"""

from decimal import Decimal
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.core.security import _create_token, create_access_token, hash_password
from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.models.delivery_partner import ApprovalStatus, DeliveryPartner
from app.models.notification import Notification, NotificationType, NotificationChannel, NotificationStatus
from app.models.restaurant import Restaurant
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


def _user(engine, email, role, phone=None):
    with Session(engine) as db:
        user = User(name="U", email=email, phone=phone, password_hash=hash_password("x"), role=role)
        db.add(user)
        db.commit()
        db.refresh(user)
        return user


def _notification_for(engine, user, *, role, notification_type=NotificationType.SYSTEM):
    with Session(engine) as db:
        notification = Notification(
            user_id=user.id, role=role, type=notification_type, title="T", body="B",
            channel=NotificationChannel.IN_APP, status=NotificationStatus.SENT,
        )
        db.add(notification)
        db.commit()
        db.refresh(notification)
        return notification


def _headers(user):
    return {"Authorization": f"Bearer {create_access_token(user.id)}"}


# ---------------------------------------------------------------------------
# Customer A -> Customer B
# ---------------------------------------------------------------------------


def test_customer_a_cannot_mark_customer_bs_notification_read(engine):
    customer_a = _user(engine, "idor-cust-a@example.com", UserRole.CUSTOMER)
    customer_b = _user(engine, "idor-cust-b@example.com", UserRole.CUSTOMER)
    notification = _notification_for(engine, customer_b, role=UserRole.CUSTOMER)

    with TestClient(app) as client:
        response = client.post(
            f"/api/v1/customer/notifications/{notification.id}/read", headers=_headers(customer_a)
        )
        assert response.status_code == 404

        listing = client.get("/api/v1/customer/notifications", headers=_headers(customer_a))
        assert all(n["id"] != str(notification.id) for n in listing.json())


# ---------------------------------------------------------------------------
# Rider A -> Rider B
# ---------------------------------------------------------------------------


def test_rider_a_cannot_mark_rider_bs_notification_read(engine):
    rider_a = _user(engine, "idor-rider-a@example.com", UserRole.RIDER, phone="9800000050")
    rider_b = _user(engine, "idor-rider-b@example.com", UserRole.RIDER, phone="9800000051")
    notification = _notification_for(engine, rider_b, role=UserRole.RIDER)

    with TestClient(app) as client:
        response = client.post(
            f"/api/v1/rider/notifications/{notification.id}/read", headers=_headers(rider_a)
        )
        assert response.status_code == 404


# ---------------------------------------------------------------------------
# Restaurant A -> Restaurant B
# ---------------------------------------------------------------------------


def test_restaurant_a_cannot_mark_restaurant_bs_notification_read(engine):
    owner_a = _user(engine, "idor-owner-a@example.com", UserRole.RESTAURANT_OWNER, phone="9800000052")
    owner_b = _user(engine, "idor-owner-b@example.com", UserRole.RESTAURANT_OWNER, phone="9800000053")
    notification = _notification_for(engine, owner_b, role=UserRole.RESTAURANT_OWNER)

    with TestClient(app) as client:
        response = client.post(
            f"/api/v1/restaurant/notifications/{notification.id}/read", headers=_headers(owner_a)
        )
        assert response.status_code == 404


# ---------------------------------------------------------------------------
# Admin unauthorized notification access
# ---------------------------------------------------------------------------


def test_non_admin_cannot_reach_admin_notification_endpoints(engine):
    customer = _user(engine, "idor-notadmin@example.com", UserRole.CUSTOMER)

    with TestClient(app) as client:
        for method, path in [
            ("GET", "/api/v1/admin/notifications"),
            ("GET", "/api/v1/admin/notifications/unread-count"),
            ("POST", "/api/v1/admin/notifications/read-all"),
            ("POST", "/api/v1/admin/notifications/cleanup"),
        ]:
            response = client.request(method, path, headers=_headers(customer))
            assert response.status_code == 403, f"{method} {path} should be admin-only"


def test_one_admin_cannot_read_another_admins_notification(engine):
    """An admin's own feed is scoped to their own user_id too — no
    admin-only "view anyone's notifications" endpoint exists at all."""
    admin_a = _user(engine, "idor-admin-a@example.com", UserRole.ADMIN)
    admin_b = _user(engine, "idor-admin-b@example.com", UserRole.ADMIN)
    notification = _notification_for(engine, admin_b, role=UserRole.ADMIN)

    with TestClient(app) as client:
        response = client.post(
            f"/api/v1/admin/notifications/{notification.id}/read", headers=_headers(admin_a)
        )
        assert response.status_code == 404


# ---------------------------------------------------------------------------
# Modified notification ID
# ---------------------------------------------------------------------------


def test_a_random_nonexistent_notification_id_404s_cleanly(engine):
    customer = _user(engine, "idor-randomid@example.com", UserRole.CUSTOMER)

    with TestClient(app) as client:
        response = client.post(
            f"/api/v1/customer/notifications/{uuid4()}/read", headers=_headers(customer)
        )
        assert response.status_code == 404


# ---------------------------------------------------------------------------
# Modified order ID (in a notification's own data payload)
# ---------------------------------------------------------------------------


def test_tampering_with_a_notifications_order_id_never_grants_order_access(engine):
    """A notification's own order_id (and its data["order_id"] push
    payload field) is only ever a navigation hint — never trusted as
    proof of access on its own (Deep Linking, Phase 27). Proven here at
    the actual resource boundary: tracking another customer's order
    using an order_id copied out of a notification still 404s."""
    from app.services.addresses import create_address
    from app.services.cart import add_item, create_cart_for_user
    from app.services.orders import create_order
    from app.models.product import Product

    with Session(engine) as db:
        customer_a = User(name="A", email="idor-orderid-a@example.com", password_hash=hash_password("x"), role=UserRole.CUSTOMER)
        customer_b = User(name="B", email="idor-orderid-b@example.com", password_hash=hash_password("x"), role=UserRole.CUSTOMER)
        owner = User(name="Owner", email="idor-owner-order@example.com", password_hash=hash_password("x"), role=UserRole.RESTAURANT_OWNER)
        db.add_all([customer_a, customer_b, owner])
        db.commit()
        restaurant = Restaurant(
            owner_id=owner.id, name="Diner", phone="9876543210", address="1 Road",
            latitude=Decimal("12.1"), longitude=Decimal("77.1"),
            minimum_order=Decimal("0.00"), delivery_fee=Decimal("0.00"),
        )
        db.add(restaurant)
        db.commit()
        product = Product(restaurant_id=restaurant.id, name="Item", price=Decimal("100.00"))
        db.add(product)
        db.commit()
        cart = create_cart_for_user(db, customer_b.id)
        add_item(db, cart, product.id, 1)
        address = create_address(db, customer_b.id, {
            "label": "Home", "recipient_name": "B", "phone": "9999999999",
            "address_line": "1 Road", "city": "Bengaluru", "state": "Karnataka", "postal_code": "560001",
        })
        order_b = create_order(db, customer_b, address.id)
        order_b_id = order_b.id
        customer_a_id = customer_a.id

    with TestClient(app) as client:
        # customer_a, armed only with customer_b's own order_id (as if
        # copied straight out of a tampered notification payload), tries
        # to view it as their own order.
        token = create_access_token(customer_a_id)
        response = client.get(
            f"/api/v1/customer/orders/{order_b_id}", headers={"Authorization": f"Bearer {token}"}
        )
        assert response.status_code == 404


# ---------------------------------------------------------------------------
# Fake push token registration
# ---------------------------------------------------------------------------


def test_cannot_register_a_push_token_under_an_arbitrary_user_id(engine):
    attacker = _user(engine, "idor-pushattacker@example.com", UserRole.CUSTOMER)
    victim = _user(engine, "idor-pushvictim@example.com", UserRole.CUSTOMER)

    with TestClient(app) as client:
        response = client.post(
            "/api/v1/notifications/register",
            headers=_headers(attacker),
            json={"token": "ExponentPushToken[fake]", "platform": "expo", "user_id": str(victim.id)},
        )
        assert response.status_code == 200
        assert response.json()["user_id"] == str(attacker.id)  # never victim.id — no such field exists


# ---------------------------------------------------------------------------
# Unauthenticated API
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", "/api/v1/customer/notifications"),
        ("GET", "/api/v1/customer/notifications/unread-count"),
        ("POST", "/api/v1/customer/notifications/read-all"),
        ("GET", "/api/v1/rider/notifications"),
        ("GET", "/api/v1/restaurant/notifications"),
        ("GET", "/api/v1/admin/notifications"),
        ("GET", "/api/v1/notifications/preferences"),
        ("PATCH", "/api/v1/notifications/preferences"),
        ("POST", "/api/v1/notifications/register"),
    ],
)
def test_every_notification_endpoint_rejects_unauthenticated_requests(engine, method, path):
    with TestClient(app) as client:
        response = client.request(method, path, json={} if method in ("POST", "PATCH") else None)
        assert response.status_code in (401, 403)


# ---------------------------------------------------------------------------
# Expired JWT
# ---------------------------------------------------------------------------


def test_an_expired_access_token_is_rejected(engine):
    from datetime import timedelta

    customer = _user(engine, "idor-expired@example.com", UserRole.CUSTOMER)
    expired_token = _create_token(customer.id, "access", timedelta(minutes=-5))

    with TestClient(app) as client:
        response = client.get(
            "/api/v1/customer/notifications", headers={"Authorization": f"Bearer {expired_token}"}
        )
        assert response.status_code == 401
