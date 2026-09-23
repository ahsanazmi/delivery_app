"""Admin Portal — Phase 12: Delivery Assignment Management (view-only)."""

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from app.core.security import create_access_token, hash_password
from app.db.session import get_db
from app.models.delivery_assignment import AssignmentStatus, DeliveryAssignment
from app.models.order import Order, OrderStatus
from app.models.user import User, UserRole

ASSIGNMENTS_URL = "/api/v1/admin/delivery-assignments"


def _db(client):
    return next(client.app.dependency_overrides[get_db]())


def _make_user(db, *, name, email, phone, role):
    user = User(name=name, email=email, phone=phone, password_hash=hash_password("x"), role=role)
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _admin_headers(db):
    admin = _make_user(db, name="Admin", email=f"admin-p12-{uuid.uuid4().hex[:8]}@example.com", phone=f"86{uuid.uuid4().hex[:8]}", role=UserRole.ADMIN)
    return admin, {"Authorization": f"Bearer {create_access_token(admin.id)}"}


def _make_order(db, *, status=OrderStatus.READY_FOR_PICKUP, rider_id=None, order_number=None):
    order = Order(
        user_id=uuid.uuid4(), rider_id=rider_id, customer_name="Cust", customer_email="cust@example.com",
        restaurant_id="rest-1", restaurant_name="Some Restaurant",
        order_number=order_number or f"ORD-{uuid.uuid4().hex[:20]}", status=status,
        subtotal=Decimal("100.00"), delivery_fee=Decimal("30.00"), total=Decimal("130.00"),
        payment_method="cod", address_line="123 Main St", city="Testville", postal_code="123456",
    )
    db.add(order)
    db.commit()
    db.refresh(order)
    return order


def _make_rider(db, suffix):
    return _make_user(db, name=f"Delivery Rider {suffix}", email=f"delivery-rider-{suffix}-p12@example.com", phone=f"85000000{suffix}", role=UserRole.RIDER)


def _make_assignment(db, *, order, rider, assignment_status, **timestamps):
    assignment = DeliveryAssignment(order_id=order.id, rider_id=rider.id, status=assignment_status, **timestamps)
    db.add(assignment)
    db.commit()
    db.refresh(assignment)
    return assignment


def test_list_requires_admin(client):
    db = _db(client)
    customer = _make_user(db, name="Not Admin", email="not-admin-p12@example.com", phone="8500000001", role=UserRole.CUSTOMER)
    token = create_access_token(customer.id)
    assert client.get(ASSIGNMENTS_URL, headers={"Authorization": f"Bearer {token}"}).status_code == 403
    assert client.get(ASSIGNMENTS_URL).status_code == 401


def test_list_includes_real_assignment_with_rider_and_order_details(client):
    db = _db(client)
    _, headers = _admin_headers(db)
    rider = _make_rider(db, "10")
    order = _make_order(db, status=OrderStatus.PICKED_UP, rider_id=rider.id, order_number="ORD-REAL-001")
    picked_up_time = datetime.now(UTC)
    assignment = _make_assignment(
        db, order=order, rider=rider, assignment_status=AssignmentStatus.PICKED_UP,
        accepted_at=picked_up_time - timedelta(minutes=10), picked_up_at=picked_up_time,
    )

    response = client.get(ASSIGNMENTS_URL, headers=headers)
    assert response.status_code == 200
    match = next(item for item in response.json()["items"] if item["id"] == str(assignment.id))
    assert match["order_number"] == "ORD-REAL-001"
    assert match["rider_name"] == "Delivery Rider 10"
    assert match["status"] == "PICKED_UP"
    assert match["picked_up_at"] is not None


def test_list_synthesizes_pending_entries_for_unclaimed_orders(client):
    db = _db(client)
    _, headers = _admin_headers(db)
    unclaimed = _make_order(db, status=OrderStatus.READY_FOR_PICKUP, order_number="ORD-UNCLAIMED-001")

    response = client.get(ASSIGNMENTS_URL, headers=headers)
    assert response.status_code == 200
    match = next(item for item in response.json()["items"] if item["order_id"] == str(unclaimed.id))
    assert match["id"] is None
    assert match["status"] == "PENDING"
    assert match["rider_id"] is None
    assert match["rider_name"] is None


def test_list_status_filter_pending_returns_only_synthesized_entries(client):
    db = _db(client)
    _, headers = _admin_headers(db)
    rider = _make_rider(db, "20")
    claimed = _make_order(db, status=OrderStatus.RIDER_ASSIGNED, rider_id=rider.id)
    _make_assignment(db, order=claimed, rider=rider, assignment_status=AssignmentStatus.ACCEPTED, accepted_at=datetime.now(UTC))
    unclaimed = _make_order(db, status=OrderStatus.READY_FOR_PICKUP)

    response = client.get(ASSIGNMENTS_URL, headers=headers, params={"status": "PENDING"})
    items = response.json()["items"]
    order_ids = [item["order_id"] for item in items]
    assert str(unclaimed.id) in order_ids
    assert str(claimed.id) not in order_ids
    assert all(item["status"] == "PENDING" for item in items)


def test_list_status_filter_real_status_excludes_pending(client):
    db = _db(client)
    _, headers = _admin_headers(db)
    rider = _make_rider(db, "30")
    order = _make_order(db, status=OrderStatus.DELIVERED, rider_id=rider.id)
    assignment = _make_assignment(db, order=order, rider=rider, assignment_status=AssignmentStatus.DELIVERED, delivered_at=datetime.now(UTC))
    _make_order(db, status=OrderStatus.READY_FOR_PICKUP)

    response = client.get(ASSIGNMENTS_URL, headers=headers, params={"status": "DELIVERED"})
    items = response.json()["items"]
    assert [item["id"] for item in items] == [str(assignment.id)]


def test_list_search_matches_order_number_and_rider_name(client):
    db = _db(client)
    _, headers = _admin_headers(db)
    rider = _make_rider(db, "40")
    order = _make_order(db, status=OrderStatus.PICKED_UP, rider_id=rider.id, order_number="ORD-FINDME-002")
    assignment = _make_assignment(db, order=order, rider=rider, assignment_status=AssignmentStatus.PICKED_UP, picked_up_at=datetime.now(UTC))
    _make_order(db, status=OrderStatus.READY_FOR_PICKUP, order_number="ORD-OTHER-003")

    r1 = client.get(ASSIGNMENTS_URL, headers=headers, params={"search": "FINDME"})
    assert [i["id"] for i in r1.json()["items"]] == [str(assignment.id)]

    r2 = client.get(ASSIGNMENTS_URL, headers=headers, params={"search": "Delivery Rider 40"})
    assert [i["id"] for i in r2.json()["items"]] == [str(assignment.id)]


def test_list_pagination_across_merged_sources(client):
    db = _db(client)
    _, headers = _admin_headers(db)
    rider = _make_rider(db, "50")
    for _ in range(2):
        order = _make_order(db, status=OrderStatus.RIDER_ASSIGNED, rider_id=rider.id)
        _make_assignment(db, order=order, rider=rider, assignment_status=AssignmentStatus.ACCEPTED, accepted_at=datetime.now(UTC))
    for _ in range(2):
        _make_order(db, status=OrderStatus.READY_FOR_PICKUP)

    response = client.get(ASSIGNMENTS_URL, headers=headers, params={"page": 1, "limit": 2})
    body = response.json()
    assert body["total"] >= 4
    assert len(body["items"]) == 2
    assert body["page"] == 1
    assert body["limit"] == 2


def test_get_detail_includes_full_timeline(client):
    db = _db(client)
    _, headers = _admin_headers(db)
    rider = _make_rider(db, "60")
    order = _make_order(db, status=OrderStatus.DELIVERED, rider_id=rider.id)
    now = datetime.now(UTC)
    assignment = _make_assignment(
        db, order=order, rider=rider, assignment_status=AssignmentStatus.DELIVERED,
        accepted_at=now - timedelta(minutes=30), arrived_at=now - timedelta(minutes=20),
        picked_up_at=now - timedelta(minutes=15), out_for_delivery_at=now - timedelta(minutes=14),
        delivered_at=now,
    )

    response = client.get(f"{ASSIGNMENTS_URL}/{assignment.id}", headers=headers)
    assert response.status_code == 200
    body = response.json()
    assert body["order_number"] == order.order_number
    assert body["rider_name"] == "Delivery Rider 60"
    assert body["restaurant_name"] == "Some Restaurant"
    assert body["customer_name"] == "Cust"
    assert body["accepted_at"] is not None
    assert body["arrived_at"] is not None
    assert body["picked_up_at"] is not None
    assert body["out_for_delivery_at"] is not None
    assert body["delivered_at"] is not None


def test_get_detail_includes_rejection_reason(client):
    db = _db(client)
    _, headers = _admin_headers(db)
    rider = _make_rider(db, "70")
    order = _make_order(db, status=OrderStatus.READY_FOR_PICKUP)
    assignment = _make_assignment(
        db, order=order, rider=rider, assignment_status=AssignmentStatus.REJECTED,
        rejected_at=datetime.now(UTC), rejection_reason="Too far away",
    )

    response = client.get(f"{ASSIGNMENTS_URL}/{assignment.id}", headers=headers)
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "REJECTED"
    assert body["rejection_reason"] == "Too far away"


def test_get_detail_404_for_missing_assignment(client):
    db = _db(client)
    _, headers = _admin_headers(db)
    response = client.get(f"{ASSIGNMENTS_URL}/00000000-0000-0000-0000-000000000000", headers=headers)
    assert response.status_code == 404


def test_get_detail_requires_admin(client):
    db = _db(client)
    rider = _make_rider(db, "80")
    order = _make_order(db, status=OrderStatus.RIDER_ASSIGNED, rider_id=rider.id)
    assignment = _make_assignment(db, order=order, rider=rider, assignment_status=AssignmentStatus.ACCEPTED, accepted_at=datetime.now(UTC))
    token = create_access_token(rider.id)

    response = client.get(f"{ASSIGNMENTS_URL}/{assignment.id}", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 403


def test_no_mutation_routes_exist(client):
    """This phase is explicitly view-only — confirm there is no PATCH/POST
    surface here at all; the only sanctioned rider-reassignment path is
    still POST /admin/orders/{id}/reassign-rider from Phase 11."""
    db = _db(client)
    _, headers = _admin_headers(db)
    rider = _make_rider(db, "90")
    order = _make_order(db, status=OrderStatus.RIDER_ASSIGNED, rider_id=rider.id)
    assignment = _make_assignment(db, order=order, rider=rider, assignment_status=AssignmentStatus.ACCEPTED, accepted_at=datetime.now(UTC))

    assert client.patch(f"{ASSIGNMENTS_URL}/{assignment.id}", headers=headers, json={"status": "DELIVERED"}).status_code == 405
    assert client.post(f"{ASSIGNMENTS_URL}/{assignment.id}", headers=headers, json={}).status_code == 405
