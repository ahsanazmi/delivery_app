"""Admin Portal — Phase 11: Order Intervention.

Every intervention here must validate current state, validate the target
state, record the acting admin's id, require a reason, and write an audit
log entry — atomically with the mutation itself, never as an afterthought.
"""

import uuid
from decimal import Decimal

from app.core.security import create_access_token, hash_password
from app.db.session import get_db
from app.models.admin_audit_log import AdminAuditLog
from app.models.delivery_assignment import AssignmentStatus, DeliveryAssignment
from app.models.delivery_partner import ApprovalStatus, DeliveryPartner
from app.models.order import Order, OrderStatus
from app.models.user import User, UserRole

ORDERS_URL = "/api/v1/admin/orders"


def _db(client):
    return next(client.app.dependency_overrides[get_db]())


def _make_user(db, *, name, email, phone, role):
    user = User(name=name, email=email, phone=phone, password_hash=hash_password("x"), role=role)
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _make_admin(db):
    return _make_user(db, name="Admin", email=f"admin-p11-{uuid.uuid4().hex[:8]}@example.com", phone=f"88{uuid.uuid4().hex[:8]}", role=UserRole.ADMIN)


def _admin_headers(db):
    admin = _make_admin(db)
    return admin, {"Authorization": f"Bearer {create_access_token(admin.id)}"}


def _make_order(db, *, status=OrderStatus.PLACED, rider_id=None):
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


def _make_rider(db, suffix):
    """Rider Assignment Integration — reassign-rider now requires an
    APPROVED DeliveryPartner record on the incoming rider, same standing
    the self-service accept flow already required."""
    rider = _make_user(db, name=f"Rider {suffix}", email=f"rider-{suffix}-p11@example.com", phone=f"87000000{suffix}", role=UserRole.RIDER)
    db.add(DeliveryPartner(user_id=rider.id, approval_status=ApprovalStatus.APPROVED))
    db.commit()
    return rider


# --------------------------- Cancel ---------------------------


def test_cancel_requires_admin(client):
    db = _db(client)
    order = _make_order(db)
    customer = _make_user(db, name="Not Admin", email="not-admin-p11@example.com", phone="8700000001", role=UserRole.CUSTOMER)
    token = create_access_token(customer.id)

    assert client.post(f"{ORDERS_URL}/{order.id}/cancel", headers={"Authorization": f"Bearer {token}"}, json={"reason": "x"}).status_code == 403
    assert client.post(f"{ORDERS_URL}/{order.id}/cancel", json={"reason": "x"}).status_code == 401


def test_cancel_requires_reason(client):
    db = _db(client)
    admin, headers = _admin_headers(db)
    order = _make_order(db)

    assert client.post(f"{ORDERS_URL}/{order.id}/cancel", headers=headers, json={}).status_code == 422
    assert client.post(f"{ORDERS_URL}/{order.id}/cancel", headers=headers, json={"reason": ""}).status_code == 422


def test_cancel_valid_from_each_pre_pickup_status(client):
    db = _db(client)
    admin, headers = _admin_headers(db)

    for order_status in (
        OrderStatus.PLACED, OrderStatus.CONFIRMED, OrderStatus.PREPARING,
        OrderStatus.READY_FOR_PICKUP, OrderStatus.RIDER_ASSIGNED,
    ):
        order = _make_order(db, status=order_status)
        response = client.post(f"{ORDERS_URL}/{order.id}/cancel", headers=headers, json={"reason": "Test cancel"})
        assert response.status_code == 200, order_status
        assert response.json()["status"] == "cancelled"


def test_cancel_invalid_from_post_pickup_or_terminal_statuses(client):
    db = _db(client)
    admin, headers = _admin_headers(db)

    for order_status in (
        OrderStatus.PICKED_UP, OrderStatus.OUT_FOR_DELIVERY, OrderStatus.DELIVERED,
        OrderStatus.CANCELLED, OrderStatus.REJECTED,
    ):
        order = _make_order(db, status=order_status)
        response = client.post(f"{ORDERS_URL}/{order.id}/cancel", headers=headers, json={"reason": "Test cancel"})
        assert response.status_code == 409, order_status


def test_cancel_404_for_missing_order(client):
    db = _db(client)
    admin, headers = _admin_headers(db)
    response = client.post(f"{ORDERS_URL}/00000000-0000-0000-0000-000000000000/cancel", headers=headers, json={"reason": "x"})
    assert response.status_code == 404


def test_cancel_sets_cancelled_reason_and_creates_audit_log(client):
    db = _db(client)
    admin, headers = _admin_headers(db)
    order = _make_order(db, status=OrderStatus.CONFIRMED)

    response = client.post(f"{ORDERS_URL}/{order.id}/cancel", headers=headers, json={"reason": "Customer requested via phone"})
    assert response.status_code == 200

    db.refresh(order)
    assert order.cancelled_reason == "Customer requested via phone"
    assert order.status == OrderStatus.CANCELLED

    log = db.query(AdminAuditLog).filter(
        AdminAuditLog.target_type == "order", AdminAuditLog.target_id == str(order.id), AdminAuditLog.action == "order.cancel",
    ).one()
    assert log.admin_id == admin.id
    assert log.reason == "Customer requested via phone"
    assert log.previous_state == "confirmed"
    assert log.new_state == "cancelled"


def test_cancel_does_not_orphan_audit_log_on_invalid_transition(client):
    """The mutation and its audit entry are atomic — a rejected
    intervention must never leave a log entry behind for something that
    never actually happened."""
    db = _db(client)
    admin, headers = _admin_headers(db)
    order = _make_order(db, status=OrderStatus.DELIVERED)

    response = client.post(f"{ORDERS_URL}/{order.id}/cancel", headers=headers, json={"reason": "x"})
    assert response.status_code == 409

    count = db.query(AdminAuditLog).filter(AdminAuditLog.target_id == str(order.id)).count()
    assert count == 0


def test_cancel_closes_out_existing_delivery_assignment(client):
    db = _db(client)
    admin, headers = _admin_headers(db)
    rider = _make_rider(db, "10")
    order = _make_order(db, status=OrderStatus.RIDER_ASSIGNED, rider_id=rider.id)
    db.add(DeliveryAssignment(order_id=order.id, rider_id=rider.id, status=AssignmentStatus.ACCEPTED))
    db.commit()

    response = client.post(f"{ORDERS_URL}/{order.id}/cancel", headers=headers, json={"reason": "Restaurant out of stock"})
    assert response.status_code == 200

    assignment = db.query(DeliveryAssignment).filter(DeliveryAssignment.order_id == order.id).one()
    assert assignment.status == AssignmentStatus.CANCELLED


# --------------------------- Reassign rider ---------------------------


def test_reassign_requires_admin(client):
    db = _db(client)
    rider_a = _make_rider(db, "20")
    rider_b = _make_rider(db, "21")
    order = _make_order(db, status=OrderStatus.RIDER_ASSIGNED, rider_id=rider_a.id)
    token = create_access_token(rider_a.id)

    response = client.post(
        f"{ORDERS_URL}/{order.id}/reassign-rider",
        headers={"Authorization": f"Bearer {token}"},
        json={"new_rider_id": str(rider_b.id), "reason": "x"},
    )
    assert response.status_code == 403
    assert client.post(f"{ORDERS_URL}/{order.id}/reassign-rider", json={"new_rider_id": str(rider_b.id), "reason": "x"}).status_code == 401


def test_reassign_requires_reason(client):
    db = _db(client)
    admin, headers = _admin_headers(db)
    rider_a = _make_rider(db, "30")
    rider_b = _make_rider(db, "31")
    order = _make_order(db, status=OrderStatus.RIDER_ASSIGNED, rider_id=rider_a.id)

    response = client.post(f"{ORDERS_URL}/{order.id}/reassign-rider", headers=headers, json={"new_rider_id": str(rider_b.id)})
    assert response.status_code == 422


def test_reassign_valid_from_rider_assigned(client):
    db = _db(client)
    admin, headers = _admin_headers(db)
    rider_a = _make_rider(db, "40")
    rider_b = _make_rider(db, "41")
    order = _make_order(db, status=OrderStatus.RIDER_ASSIGNED, rider_id=rider_a.id)

    response = client.post(
        f"{ORDERS_URL}/{order.id}/reassign-rider", headers=headers,
        json={"new_rider_id": str(rider_b.id), "reason": "Original rider went offline"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["rider_id"] == str(rider_b.id)
    assert body["status"] == "rider_assigned"


def test_reassign_invalid_when_no_rider_assigned(client):
    db = _db(client)
    admin, headers = _admin_headers(db)
    rider_b = _make_rider(db, "50")
    order = _make_order(db, status=OrderStatus.READY_FOR_PICKUP)

    response = client.post(
        f"{ORDERS_URL}/{order.id}/reassign-rider", headers=headers, json={"new_rider_id": str(rider_b.id), "reason": "x"}
    )
    assert response.status_code == 409


def test_reassign_invalid_after_pickup(client):
    db = _db(client)
    admin, headers = _admin_headers(db)
    rider_a = _make_rider(db, "60")
    rider_b = _make_rider(db, "61")
    order = _make_order(db, status=OrderStatus.PICKED_UP, rider_id=rider_a.id)

    response = client.post(
        f"{ORDERS_URL}/{order.id}/reassign-rider", headers=headers, json={"new_rider_id": str(rider_b.id), "reason": "x"}
    )
    assert response.status_code == 409


def test_reassign_rejects_invalid_or_non_rider_target(client):
    db = _db(client)
    admin, headers = _admin_headers(db)
    rider_a = _make_rider(db, "70")
    customer = _make_user(db, name="Not A Rider", email="not-rider-p11@example.com", phone="8700000071", role=UserRole.CUSTOMER)
    order = _make_order(db, status=OrderStatus.RIDER_ASSIGNED, rider_id=rider_a.id)

    response = client.post(
        f"{ORDERS_URL}/{order.id}/reassign-rider", headers=headers, json={"new_rider_id": str(customer.id), "reason": "x"}
    )
    assert response.status_code == 400

    missing = client.post(
        f"{ORDERS_URL}/{order.id}/reassign-rider", headers=headers,
        json={"new_rider_id": "00000000-0000-0000-0000-000000000000", "reason": "x"},
    )
    assert missing.status_code == 400


def test_reassign_to_same_rider_is_conflict(client):
    db = _db(client)
    admin, headers = _admin_headers(db)
    rider_a = _make_rider(db, "80")
    order = _make_order(db, status=OrderStatus.RIDER_ASSIGNED, rider_id=rider_a.id)

    response = client.post(
        f"{ORDERS_URL}/{order.id}/reassign-rider", headers=headers, json={"new_rider_id": str(rider_a.id), "reason": "x"}
    )
    assert response.status_code == 409


def test_reassign_404_for_missing_order(client):
    db = _db(client)
    admin, headers = _admin_headers(db)
    rider = _make_rider(db, "90")
    response = client.post(
        f"{ORDERS_URL}/00000000-0000-0000-0000-000000000000/reassign-rider", headers=headers,
        json={"new_rider_id": str(rider.id), "reason": "x"},
    )
    assert response.status_code == 404


def test_reassign_creates_audit_log_and_closes_old_assignment(client):
    db = _db(client)
    admin, headers = _admin_headers(db)
    rider_a = _make_rider(db, "91")
    rider_b = _make_rider(db, "92")
    order = _make_order(db, status=OrderStatus.RIDER_ASSIGNED, rider_id=rider_a.id)
    db.add(DeliveryAssignment(order_id=order.id, rider_id=rider_a.id, status=AssignmentStatus.ACCEPTED))
    db.commit()

    response = client.post(
        f"{ORDERS_URL}/{order.id}/reassign-rider", headers=headers,
        json={"new_rider_id": str(rider_b.id), "reason": "Rider A reported vehicle breakdown"},
    )
    assert response.status_code == 200

    log = db.query(AdminAuditLog).filter(
        AdminAuditLog.target_type == "order", AdminAuditLog.target_id == str(order.id), AdminAuditLog.action == "order.reassign_rider",
    ).one()
    assert log.admin_id == admin.id
    assert log.reason == "Rider A reported vehicle breakdown"
    assert log.previous_state == str(rider_a.id)
    assert log.new_state == str(rider_b.id)

    old_assignment = db.query(DeliveryAssignment).filter(
        DeliveryAssignment.order_id == order.id, DeliveryAssignment.rider_id == rider_a.id
    ).one()
    assert old_assignment.status == AssignmentStatus.CANCELLED

    db.refresh(order)
    history_notes = [h.note for h in order.status_history]
    assert any("Reassigned" in (note or "") for note in history_notes)


def test_reassign_does_not_orphan_audit_log_on_invalid_transition(client):
    db = _db(client)
    admin, headers = _admin_headers(db)
    rider_a = _make_rider(db, "93")
    rider_b = _make_rider(db, "94")
    order = _make_order(db, status=OrderStatus.DELIVERED, rider_id=rider_a.id)

    response = client.post(
        f"{ORDERS_URL}/{order.id}/reassign-rider", headers=headers, json={"new_rider_id": str(rider_b.id), "reason": "x"}
    )
    assert response.status_code == 409

    count = db.query(AdminAuditLog).filter(AdminAuditLog.target_id == str(order.id)).count()
    assert count == 0
