"""Integration Phase 14/15 — Order Cancellation Testing / Failure Scenarios.

Walks both real cancellation paths this codebase actually supports and
verifies the propagation the phase briefs describe, plus that no record is
left in an inconsistent or orphaned state afterward.

Who can cancel, and when (as implemented, not aspirational):
  - CUSTOMER: only while the order is PLACED or CONFIRMED (self-service,
    see CUSTOMER_CANCELLABLE_STATUSES in app/services/orders.py) — i.e.
    only before the restaurant has started preparing it, and always before
    any rider could possibly be involved.
  - ADMIN: PLACED, CONFIRMED, PREPARING, READY_FOR_PICKUP, or RIDER_ASSIGNED
    (ADMIN_CANCELLABLE_STATUSES — wherever CANCELLED is a valid transition
    target), audited, with a required reason. This is the ONLY path that
    can cancel an order that already has a rider assigned.
  - Nobody can cancel once PICKED_UP or OUT_FOR_DELIVERY — see
    test_rider_suspended_after_pickup_leaves_the_order_stuck_with_no_admin_recovery
    in test_rider_concurrency_and_failure_handling.py for what that means
    in practice.
  - There is no restaurant-facing cancel endpoint at all (only
    reject-before-accepting, which is a different transition: PLACED ->
    REJECTED, not -> CANCELLED).

What happens to payment: for a COD order (the only payment method the real
order-creation flow allows today), no money has been collected at any
cancellable state — is_paid only ever becomes True via the rider's
cod-collect step during OUT_FOR_DELIVERY, which is unreachable once
cancelled. So cancellation never needs to trigger a refund; the Payment
row (if one was ever created via record_order_payment) is simply left at
PENDING, which admin's payment list displays as a synthesized CANCELLED
status (see admin_payments.py) rather than double-counting it under
"pending".

What happens to rider assignment: any non-terminal DeliveryAssignment for
the order's current rider is flipped to CANCELLED as part of the same
transition_order_status() call (_cancel_delivery_assignment), and the
rider is notified separately from the customer's own ORDER_CANCELLED
notification.

What happens to the restaurant's own view: the order simply disappears
from the "pending"/"confirmed"/"preparing" buckets of
GET /restaurant/orders?status=... and appears under "cancelled" instead,
the moment the underlying Order row's status changes — there is no
dedicated restaurant notification channel in this codebase (no
Notification rows or push are ever sent to a RESTAURANT_OWNER anywhere),
so "restaurant notified" in practice means "reflected the moment the
owner's app next polls its own order list/detail", not a push alert.
"""

from decimal import Decimal
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.core.security import create_access_token, hash_password
from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.models import Product, Restaurant, User, UserRole
from app.models.delivery_assignment import AssignmentStatus, DeliveryAssignment
from app.models.delivery_partner import ApprovalStatus, DeliveryPartner
from app.models.notification import Notification, NotificationType
from app.models.payment import Payment
from app.services.addresses import create_address


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


def test_customer_cancellation_propagates_and_leaves_no_orphaned_records(engine):
    with Session(engine) as seed:
        owner = User(name="Owner", email="owner-p14@example.com", phone="9600000001", password_hash=hash_password("x"), role=UserRole.RESTAURANT_OWNER)
        customer = User(name="Customer", email="customer-p14@example.com", phone="9600000002", password_hash=hash_password("x"), role=UserRole.CUSTOMER)
        admin = User(name="Admin", email="admin-p14@example.com", phone="9600000003", password_hash=hash_password("x"), role=UserRole.ADMIN)
        seed.add_all([owner, customer, admin])
        seed.commit()

        restaurant = Restaurant(
            owner_id=owner.id, name="Chai House", phone="9876543210", address="Main Road",
            latitude=Decimal("12.1"), longitude=Decimal("77.1"),
            minimum_order=Decimal("0.00"), delivery_fee=Decimal("30.00"),
        )
        seed.add(restaurant)
        seed.commit()
        product = Product(restaurant_id=restaurant.id, name="Masala Chai", price=Decimal("40.00"))
        seed.add(product)
        seed.commit()
        product_id = product.id

        address = create_address(seed, customer.id, {
            "label": "Home", "recipient_name": "Customer", "phone": "9600000002",
            "address_line": "7 Lake View Road", "city": "Bengaluru", "state": "Karnataka", "postal_code": "560002",
        })
        address_id = address.id

        owner_token = create_access_token(owner.id)
        customer_token = create_access_token(customer.id)
        admin_token = create_access_token(admin.id)
        customer_id = customer.id

    owner_headers = {"Authorization": f"Bearer {owner_token}"}
    customer_headers = {"Authorization": f"Bearer {customer_token}"}
    admin_headers = {"Authorization": f"Bearer {admin_token}"}

    with TestClient(app) as client:
        client.post("/api/v1/customer/cart/items", headers=customer_headers, json={"product_id": str(product_id), "quantity": 1})
        place = client.post("/api/v1/customer/orders", headers=customer_headers, json={"address_id": str(address_id)})
        assert place.status_code == 201
        order_id = place.json()["id"]

        # Record a payment attempt too, matching real usage — this must
        # survive cancellation as a PENDING row, not be deleted or crash anything.
        record_payment = client.post(f"/api/v1/customer/orders/{order_id}/payment", headers=customer_headers)
        assert record_payment.status_code == 200

        # Restaurant accepts (PLACED -> CONFIRMED) — still customer-cancellable.
        assert client.post(f"/api/v1/restaurant/orders/{order_id}/accept", headers=owner_headers).status_code == 200

        # It's currently visible in the restaurant's "confirmed" bucket.
        confirmed_bucket = client.get("/api/v1/restaurant/orders?status=confirmed", headers=owner_headers)
        assert any(o["id"] == order_id for o in confirmed_bucket.json())

        # ---- Customer cancels ----
        # cancel_order_endpoint's `reason` is a plain query param, not a
        # JSON body field (see app/api/v1/customer/orders.py).
        cancel = client.post(
            f"/api/v1/customer/orders/{order_id}/cancel", headers=customer_headers, params={"reason": "Changed my mind"}
        )
        assert cancel.status_code == 200
        assert cancel.json()["status"] == "cancelled"
        assert cancel.json()["cancelled_reason"] == "Changed my mind"

        # ---- "Restaurant notified": no push channel exists, but the
        # order is immediately reflected — gone from every active bucket,
        # present under "cancelled" ----
        confirmed_bucket_after = client.get("/api/v1/restaurant/orders?status=confirmed", headers=owner_headers)
        assert all(o["id"] != order_id for o in confirmed_bucket_after.json())
        pending_bucket_after = client.get("/api/v1/restaurant/orders?status=pending", headers=owner_headers)
        assert all(o["id"] != order_id for o in pending_bucket_after.json())
        cancelled_bucket = client.get("/api/v1/restaurant/orders?status=cancelled", headers=owner_headers)
        assert any(o["id"] == order_id for o in cancelled_bucket.json())
        restaurant_detail = client.get(f"/api/v1/restaurant/orders/{order_id}", headers=owner_headers)
        assert restaurant_detail.json()["status"] == "cancelled"

        # ---- Admin sees the cancellation on the same row ----
        admin_view = client.get(f"/api/v1/admin/orders/{order_id}", headers=admin_headers)
        assert admin_view.json()["status"] == "cancelled"

        # ---- No orphaned DeliveryAssignment: none was ever created,
        # since a customer can only cancel before any rider is involved ----
        order_uuid = UUID(order_id)
        db_gen = client.app.dependency_overrides[get_db]()
        db = next(db_gen)
        assignments = db.query(DeliveryAssignment).filter(DeliveryAssignment.order_id == order_uuid).all()
        assert assignments == []

        # ---- Payment: left PENDING (no refund needed — nothing was ever
        # collected), never deleted, never silently marked PAID/FAILED ----
        payment = db.query(Payment).filter(Payment.order_id == order_uuid).one()
        assert payment.payment_status.value == "pending"

        # Admin's payment view synthesizes the CANCELLED display status
        # rather than showing it as an actionable pending payment.
        payment_view = client.get(f"/api/v1/admin/payments/{payment.id}", headers=admin_headers)
        assert payment_view.json()["status"] == "CANCELLED"

        # ---- Customer was notified ----
        notification_rows = db.query(Notification).filter(
            Notification.user_id == customer_id, Notification.type == NotificationType.ORDER_CANCELLED,
            Notification.order_id == order_uuid,
        ).all()
        assert len(notification_rows) == 1
        db.close()


def test_admin_cancellation_of_a_rider_assigned_order_closes_out_the_assignment(engine):
    """The one path that reaches the phase's full diagram, including
    "Assignment cancelled if applicable" — only ADMIN can cancel an order
    that already has a rider assigned; a customer never can (RIDER_ASSIGNED
    is not in CUSTOMER_CANCELLABLE_STATUSES)."""
    with Session(engine) as seed:
        owner = User(name="Owner", email="owner-p14b@example.com", phone="9600000010", password_hash=hash_password("x"), role=UserRole.RESTAURANT_OWNER)
        customer = User(name="Customer", email="customer-p14b@example.com", phone="9600000011", password_hash=hash_password("x"), role=UserRole.CUSTOMER)
        rider = User(name="Rider", email="rider-p14b@example.com", phone="9600000012", password_hash=hash_password("x"), role=UserRole.RIDER)
        admin = User(name="Admin", email="admin-p14b@example.com", phone="9600000013", password_hash=hash_password("x"), role=UserRole.ADMIN)
        seed.add_all([owner, customer, rider, admin])
        seed.commit()
        seed.add(DeliveryPartner(user_id=rider.id, approval_status=ApprovalStatus.APPROVED, is_online=True))
        seed.commit()

        restaurant = Restaurant(
            owner_id=owner.id, name="Chai House", phone="9876543210", address="Main Road",
            latitude=Decimal("12.1"), longitude=Decimal("77.1"),
            minimum_order=Decimal("0.00"), delivery_fee=Decimal("30.00"),
        )
        seed.add(restaurant)
        seed.commit()
        product = Product(restaurant_id=restaurant.id, name="Masala Chai", price=Decimal("40.00"))
        seed.add(product)
        seed.commit()
        product_id = product.id

        address = create_address(seed, customer.id, {
            "label": "Home", "recipient_name": "Customer", "phone": "9600000011",
            "address_line": "7 Lake View Road", "city": "Bengaluru", "state": "Karnataka", "postal_code": "560002",
        })
        address_id = address.id

        owner_token = create_access_token(owner.id)
        customer_token = create_access_token(customer.id)
        admin_token = create_access_token(admin.id)
        rider_token = create_access_token(rider.id)
        rider_id = rider.id

    owner_headers = {"Authorization": f"Bearer {owner_token}"}
    customer_headers = {"Authorization": f"Bearer {customer_token}"}
    admin_headers = {"Authorization": f"Bearer {admin_token}"}
    rider_headers = {"Authorization": f"Bearer {rider_token}"}

    with TestClient(app) as client:
        client.post("/api/v1/customer/cart/items", headers=customer_headers, json={"product_id": str(product_id), "quantity": 1})
        order_id = client.post("/api/v1/customer/orders", headers=customer_headers, json={"address_id": str(address_id)}).json()["id"]

        client.post(f"/api/v1/restaurant/orders/{order_id}/accept", headers=owner_headers)
        client.post(f"/api/v1/restaurant/orders/{order_id}/preparing", headers=owner_headers)
        client.post(f"/api/v1/restaurant/orders/{order_id}/ready", headers=owner_headers)

        # Customer can no longer self-cancel once past CONFIRMED.
        assert client.post(f"/api/v1/customer/orders/{order_id}/cancel", headers=customer_headers).status_code == 409

        accept = client.post(f"/api/v1/rider/deliveries/{order_id}/accept", headers=rider_headers)
        assert accept.status_code == 200

        # ---- Admin cancels a RIDER_ASSIGNED order ----
        cancel = client.post(
            f"/api/v1/admin/orders/{order_id}/cancel", headers=admin_headers, json={"reason": "Restaurant called in an issue"}
        )
        assert cancel.status_code == 200
        assert cancel.json()["status"] == "cancelled"

        # ---- Assignment cancelled ----
        order_uuid = UUID(order_id)
        db_gen = client.app.dependency_overrides[get_db]()
        db = next(db_gen)
        assignment = db.query(DeliveryAssignment).filter(
            DeliveryAssignment.order_id == order_uuid, DeliveryAssignment.rider_id == rider_id
        ).one()
        assert assignment.status == AssignmentStatus.CANCELLED

        # ---- Rider notified separately from the customer ----
        rider_notice = db.query(Notification).filter(
            Notification.user_id == rider_id, Notification.type == NotificationType.DELIVERY_CANCELLED,
        ).all()
        assert len(rider_notice) == 1

        # ---- The rider can no longer act on it ----
        for action in ("pickup", "start", "complete", "cod-collect"):
            response = client.post(f"/api/v1/rider/deliveries/{order_id}/{action}", headers=rider_headers)
            assert response.status_code == 409

        # ---- Every portal agrees ----
        assert client.get(f"/api/v1/customer/orders/{order_id}", headers=customer_headers).json()["status"] == "cancelled"
        assert client.get(f"/api/v1/restaurant/orders/{order_id}", headers=owner_headers).json()["status"] == "cancelled"
        assert client.get(f"/api/v1/admin/orders/{order_id}", headers=admin_headers).json()["status"] == "cancelled"
        db.close()
