"""E2E Validation Phase 18 — a rider step (pickup/start/complete) commits the
order transition and the assignment move together. Previously the order
transition committed first and the assignment move ran after: when that
failed the rider got a 409 for an order that had already advanced, and on
completion the delivery-fee earning was never recorded (a retry then hit the
already-DELIVERED early return, so the rider was never paid)."""

from app.db.session import get_db
from app.models.delivery_assignment import AssignmentStatus, DeliveryAssignment
from app.models.order import Order, OrderStatus
from app.models.rider_earning import RiderEarning
from tests.test_rider_concurrency_and_failure_handling import (
    _make_admin,
    _make_rider_online,
    _register_and_login_rider,
    _rider_id,
    _seed_ready_order,
)


def _assigned_order(client, email, phone):
    token, _ = _register_and_login_rider(client, email=email, phone=phone)
    rider_id = _rider_id(client, token)
    _make_rider_online(client, token, _make_admin(client, email=f"admin-{email}", phone=f"8{phone[1:]}"), rider_id)
    db = next(client.app.dependency_overrides[get_db]())
    order = _seed_ready_order(db, payment_method="online")
    order_id = order.id
    db.close()
    headers = {"Authorization": f"Bearer {token}"}
    assert client.post(f"/api/v1/rider/deliveries/{order_id}/accept", headers=headers).status_code == 200
    return headers, order_id


def _force(client, order_id, order_status, assignment_status):
    db = next(client.app.dependency_overrides[get_db]())
    db.get(Order, order_id).status = order_status
    db.query(DeliveryAssignment).filter(DeliveryAssignment.order_id == order_id).update({"status": assignment_status})
    db.commit()
    db.close()


def _state(client, order_id):
    db = next(client.app.dependency_overrides[get_db]())
    order_status = db.get(Order, order_id).status
    assignment = db.query(DeliveryAssignment).filter(DeliveryAssignment.order_id == order_id).one().status
    earnings = db.query(RiderEarning).filter(RiderEarning.order_id == order_id).count()
    db.close()
    return order_status, assignment, earnings


def test_a_failed_complete_leaves_the_order_undelivered_and_retryable(client):
    headers, order_id = _assigned_order(client, "atomic-complete@example.com", "9940000201")
    # An assignment that lags its order (e.g. left behind by an earlier partial failure).
    _force(client, order_id, OrderStatus.OUT_FOR_DELIVERY, AssignmentStatus.ACCEPTED)

    response = client.post(f"/api/v1/rider/deliveries/{order_id}/complete", headers=headers)

    assert response.status_code == 409
    assert _state(client, order_id) == (OrderStatus.OUT_FOR_DELIVERY, AssignmentStatus.ACCEPTED, 0)


def test_a_failed_start_does_not_advance_the_order(client):
    headers, order_id = _assigned_order(client, "atomic-start@example.com", "9940000202")
    _force(client, order_id, OrderStatus.PICKED_UP, AssignmentStatus.ACCEPTED)

    response = client.post(f"/api/v1/rider/deliveries/{order_id}/start", headers=headers)

    assert response.status_code == 409
    assert _state(client, order_id)[0] == OrderStatus.PICKED_UP


def test_the_normal_path_still_moves_order_and_assignment_together_and_pays_once(client):
    headers, order_id = _assigned_order(client, "atomic-happy@example.com", "9940000203")
    for step, order_status, assignment_status in (
        ("pickup", OrderStatus.PICKED_UP, AssignmentStatus.PICKED_UP),
        ("start", OrderStatus.OUT_FOR_DELIVERY, AssignmentStatus.OUT_FOR_DELIVERY),
        ("complete", OrderStatus.DELIVERED, AssignmentStatus.DELIVERED),
    ):
        assert client.post(f"/api/v1/rider/deliveries/{order_id}/{step}", headers=headers).status_code == 200
        assert _state(client, order_id)[:2] == (order_status, assignment_status)
    assert client.post(f"/api/v1/rider/deliveries/{order_id}/complete", headers=headers).status_code == 200  # idempotent retry
    assert _state(client, order_id)[2] == 1
