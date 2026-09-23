"""Integration Phase 7 — Rider Assignment Integration.

The self-service accept flow (rider_service.get_online_eligibility_blocker,
enforced again at accept_delivery time) has always refused a suspended,
unapproved, or deactivated rider. Admin's own direct assignment
(assign-rider / reassign-rider) used to only check `role == RIDER`,
completely bypassing that standard — an admin could hand an order to a
rider who was never approved, was suspended mid-review, or whose account
had been deactivated. This file locks in the fix: both admin-facing
endpoints must refuse exactly the same set of ineligible riders.
"""

import uuid
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.core.security import create_access_token, hash_password
from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.models.delivery_partner import ApprovalStatus, DeliveryPartner
from app.models.order import Order, OrderStatus
from app.models.user import User, UserRole

ORDERS_URL = "/api/v1/admin/orders"


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


def _admin(db):
    admin = User(name="Admin", email=f"admin-p7-{uuid.uuid4().hex[:8]}@example.com", phone=f"96{uuid.uuid4().hex[:8]}", password_hash=hash_password("x"), role=UserRole.ADMIN)
    db.add(admin)
    db.commit()
    return admin


def _rider(db, *, approval_status: ApprovalStatus | None, is_active: bool = True, suffix: str):
    rider = User(
        name=f"Rider {suffix}", email=f"rider-p7-{suffix}@example.com", phone=f"9600000{suffix}",
        password_hash=hash_password("x"), role=UserRole.RIDER, is_active=is_active,
    )
    db.add(rider)
    db.commit()
    if approval_status is not None:
        db.add(DeliveryPartner(user_id=rider.id, approval_status=approval_status))
        db.commit()
    return rider


def _order(db, *, status=OrderStatus.READY_FOR_PICKUP, rider_id=None):
    order = Order(
        user_id=uuid.uuid4(), rider_id=rider_id, customer_name="Cust", customer_email="cust@example.com",
        restaurant_id="rest-1", restaurant_name="Some Restaurant",
        order_number=f"ORD-{uuid.uuid4().hex[:20]}", status=status,
        subtotal=Decimal("100.00"), delivery_fee=Decimal("30.00"), total=Decimal("130.00"),
        payment_method="cod", address_line="123 Main St", city="Testville", postal_code="123456",
    )
    db.add(order)
    db.commit()
    db.refresh(order)
    return order


@pytest.mark.parametrize(
    "approval_status,is_active,suffix",
    [
        (None, True, "01"),  # never onboarded — defaults to PENDING
        (ApprovalStatus.PENDING, True, "02"),
        (ApprovalStatus.REJECTED, True, "03"),
        (ApprovalStatus.SUSPENDED, True, "04"),
        (ApprovalStatus.APPROVED, False, "05"),  # approved but deactivated account
    ],
)
def test_admin_cannot_assign_an_ineligible_rider(engine, approval_status, is_active, suffix):
    with Session(engine) as seed:
        admin = _admin(seed)
        rider = _rider(seed, approval_status=approval_status, is_active=is_active, suffix=suffix)
        order = _order(seed)
        admin_token = create_access_token(admin.id)
        rider_id, order_id = rider.id, order.id

    with TestClient(app) as client:
        response = client.patch(
            f"{ORDERS_URL}/{order_id}/assign-rider",
            headers={"Authorization": f"Bearer {admin_token}"},
            json={"rider_id": str(rider_id), "reason": "Dispatch"},
        )
        assert response.status_code == 400

    with Session(engine) as verify:
        order = verify.get(Order, order_id)
        assert order.rider_id is None
        assert order.status == OrderStatus.READY_FOR_PICKUP


def test_admin_can_assign_an_approved_active_rider(engine):
    with Session(engine) as seed:
        admin = _admin(seed)
        rider = _rider(seed, approval_status=ApprovalStatus.APPROVED, suffix="06")
        order = _order(seed)
        admin_token = create_access_token(admin.id)
        rider_id, order_id = rider.id, order.id

    with TestClient(app) as client:
        response = client.patch(
            f"{ORDERS_URL}/{order_id}/assign-rider",
            headers={"Authorization": f"Bearer {admin_token}"},
            json={"rider_id": str(rider_id), "reason": "Dispatch"},
        )
        assert response.status_code == 200
        assert response.json()["rider_id"] == str(rider_id)
        assert response.json()["status"] == "rider_assigned"


@pytest.mark.parametrize(
    "approval_status,is_active,suffix",
    [
        (ApprovalStatus.PENDING, True, "10"),
        (ApprovalStatus.SUSPENDED, True, "11"),
        (ApprovalStatus.APPROVED, False, "12"),
    ],
)
def test_admin_cannot_reassign_to_an_ineligible_rider(engine, approval_status, is_active, suffix):
    with Session(engine) as seed:
        admin = _admin(seed)
        current_rider = _rider(seed, approval_status=ApprovalStatus.APPROVED, suffix=f"{suffix}a")
        new_rider = _rider(seed, approval_status=approval_status, is_active=is_active, suffix=f"{suffix}b")
        order = _order(seed, status=OrderStatus.RIDER_ASSIGNED, rider_id=current_rider.id)
        admin_token = create_access_token(admin.id)
        new_rider_id, order_id, current_rider_id = new_rider.id, order.id, current_rider.id

    with TestClient(app) as client:
        response = client.post(
            f"{ORDERS_URL}/{order_id}/reassign-rider",
            headers={"Authorization": f"Bearer {admin_token}"},
            json={"new_rider_id": str(new_rider_id), "reason": "Dispatch change"},
        )
        assert response.status_code == 400

    with Session(engine) as verify:
        order = verify.get(Order, order_id)
        assert order.rider_id == current_rider_id
